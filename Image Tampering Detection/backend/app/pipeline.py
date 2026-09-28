"""Image tampering detection pipeline: EXIF -> ELA -> luminosity -> Wiener
denoise -> Tophat/Bothat morphological localization.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageChops, ExifTags
from scipy.signal import wiener

from .mrz import MrzResult, validate_mrz

# All localization constants below are tuned against images with a longest
# side of REFERENCE_DIMENSION. ELA must run at the image's *native*
# resolution — downscaling pixels before computing it blurs away the exact
# JPEG block-boundary artifacts ELA depends on. So instead of resizing the
# image, every pixel-based constant is scaled by (actual longest side /
# REFERENCE_DIMENSION) at analysis time, keeping thresholds meaningful
# whether the input is a 500px test image or a 4000px camera photo.
REFERENCE_DIMENSION = 500
ELA_QUALITY = 95
SYNTHETIC_ELA_RESAVE_QUALITY = 90  # second-generation quality used for PNG synthetic ELA
MORPH_KERNEL_SIZE = 9  # scaled by linear image-scale factor
TAMPER_AREA_THRESHOLD = 75  # 0-255 grayscale threshold on the reconstructed map
MIN_REGION_AREA_FLOOR = 150  # px^2 at REFERENCE_DIMENSION; scaled by scale_factor^2
LOCAL_RING_PAD = 25  # px at REFERENCE_DIMENSION; scaled by linear image-scale factor
SUSPICIOUS_CONTRAST_RATIO = 5.0  # region must be this many x its local surroundings
RATIO_DENOMINATOR_FLOOR = 4.0  # avoids explosive ratios when the local baseline is near-zero noise
ABSOLUTE_ELA_FLOOR = 30.0  # 0-255; region brightness must be meaningful, not just noise-floor

# Sharpness-deficit detection: a second, independent channel alongside ELA.
# AI generative-fill/inpainting edits ("smart eraser" tools) often leave no
# compression-error signature at all (they resynthesize pixels rather than
# pasting differently-compressed content), but they do tend to be locally
# *blurrier* than genuinely photographed/printed detail nearby. This measures
# local Laplacian variance (a standard sharpness/texture proxy) instead of
# JPEG error, so it can catch edits ELA is structurally blind to.
SHARPNESS_WINDOW = 4  # px at REFERENCE_DIMENSION; scaled by linear scale factor.
# Kept small deliberately: this window must stay smaller than the smallest
# tampered feature we want to catch (e.g. a single erased word), or the box
# filter blends in neighboring sharp content at every pixel of the edit and
# erases the exact contrast we're measuring. Verified empirically against a
# real "smart eraser" edit — window=9 (at ~2x REFERENCE_DIMENSION scale)
# preserved a ~3.5x sharpness contrast that window=33 diluted to ~2.2x.
BLUR_TAMPER_THRESHOLD = 40  # 0-255-equivalent threshold on the sharpness blackhat map
MIN_BLUR_REGION_AREA_FLOOR = 150  # px^2 at REFERENCE_DIMENSION; scaled by scale_factor^2
BLUR_RING_PAD = 25  # px at REFERENCE_DIMENSION; scaled by linear scale factor
ABSOLUTE_SURROUNDING_SHARPNESS_FLOOR = 40.0  # surrounding area must be this textured for a dip to be meaningful
BLUR_DEFICIT_RATIO = 3.0  # surrounding must be this many x sharper than the blob itself
BLUR_MORPH_KERNEL_SIZE = 55  # scaled by linear scale factor. Deliberately much larger than
# MORPH_KERNEL_SIZE (ELA's kernel): blackhat can only "see" a deficit within
# reach of its kernel — a kernel smaller than the inpainted region itself
# leaves its interior with no bright neighbor to compare against, reading as
# near-zero. This must span plausible inpainted-patch sizes, not fine
# compression-error scale. (This is too coarse for dense printed text, where
# it merges whole lines into one blob — see the module-level note on why
# blur-deficit detection is scoped to photographic content, not documents.)

# Noise-residual-variance deficit detection: a third, independent channel.
# Diffusion-based generative-fill (e.g. "Generative Erase") can resynthesize
# content that is neither compression-mismatched (ELA-blind, see above) nor
# locally blurry (can defeat the sharpness-deficit channel too, since modern
# diffusion fill is often just as textured as its surroundings). But it
# rarely reproduces the fine sensor-read-noise + JPEG-quantization noise
# floor of the surrounding photograph — that residual noise is what's left
# over after Wiener-denoising, so an inpainted patch tends to look
# unnaturally "clean" in the residual even when it looks sharp in the image
# itself. This measures local residual variance instead of Laplacian
# sharpness or JPEG error, targeting a failure mode the other two channels
# structurally can't see.
NOISE_WINDOW = 21  # px at REFERENCE_DIMENSION; scaled by linear scale factor.
# Unlike SHARPNESS_WINDOW, this can't be as small as the tampered patch:
# variance is itself an estimate, and at very small windows (e.g. 7px, ~49
# samples) that estimate is noisy enough on its own to produce spurious
# "deficit" spikes throughout a normal, untampered photo (verified
# empirically — window=7 left a surrounding std of ~27 variance-units
# against a target gap of ~137, causing >60% of a test image to false-flag;
# window=21 cut that estimator noise to ~11 while still fitting well inside
# a plausible inpainted-patch size).
NOISE_TAMPER_THRESHOLD = 40  # 0-255-equivalent threshold on the noise blackhat map
MIN_NOISE_REGION_AREA_FLOOR = 150  # px^2 at REFERENCE_DIMENSION; scaled by scale_factor^2
NOISE_RING_PAD = 25  # px at REFERENCE_DIMENSION; scaled by linear scale factor
ABSOLUTE_SURROUNDING_NOISE_FLOOR = 15.0  # surrounding noise floor must be meaningful, or a
# "deficit" is just two equally-flat/denoised patches compared against each other
NOISE_DEFICIT_RATIO = 3.0  # surrounding must be this many x noisier than the blob itself
NOISE_MORPH_KERNEL_SIZE = 55  # scaled by linear scale factor; same reasoning as
# BLUR_MORPH_KERNEL_SIZE — must span plausible inpainted-patch sizes.

# Cross-channel spatial corroboration: when two *independently computed*
# channels (ELA, blur, noise) each flag a region and those regions overlap,
# that agreement is much stronger evidence than either channel's score
# alone — two unrelated forensic techniques landing on the same spot isn't
# a coincidence a single weak per-channel ratio can capture. Verified
# against a real partial/failed generative-erase edit: ELA (ratio 5.21,
# barely over its 5.0 gate) and noise-deficit (ratio 3.76, barely over its
# 3.0 gate) both fired at the same location, but max()-based fusion buried
# the combined evidence at a score of 22 ("no strong evidence") because
# neither ratio alone was compelling.
CORROBORATION_PAD = 20  # px at REFERENCE_DIMENSION; scaled by linear scale factor.
# Regions don't need pixel-identical boxes to corroborate each other — each
# channel's kernel/thresholding draws boxes slightly differently around the
# same underlying edit — so overlap is tested after expanding by this pad.
CORROBORATION_BONUS = 20.0  # flat score bump applied once when any two channels agree

EXCESS_MORPH_KERNEL_SIZE = 15  # scaled by linear scale factor. Deliberately much
# smaller than BLUR_MORPH_KERNEL_SIZE/NOISE_MORPH_KERNEL_SIZE (55): those are
# sized to span a whole inpainted *patch* (a coarse, object-scale phenomenon).
# A resampling/upscale splice's block-quantization pattern is fine-grained —
# individual interpolation blocks, not object-sized regions. Verified this
# distinction is load-bearing, not cosmetic: reusing the large kernel for
# tophat (excess) on a real bokeh-style photo (sharp foreground subject
# against a smoothly blurred background — extremely common in ordinary,
# untampered photography) flagged 68-74% of the image as one giant "excess"
# blob, because a wide kernel simply sees "busier than a distant smooth
# surround," which is true of nearly any in-focus subject. The small kernel
# can only "see" genuine block-scale texture, not whole-object contrast.
MAX_EXCESS_AREA_FRACTION = 0.2  # reject an "excess" region wider than this share of
# the image outright, regardless of kernel behavior — a genuine pasted/resampled
# element is a bounded sub-region, not most of the frame. Deficit regions get no
# such cap: a diffusion-inpainted patch replacing most of a photo isn't a
# plausible false-positive shape the way "whole sharp subject vs. blurred
# background" is for excess.


def _scale_factor(image_size: tuple[int, int]) -> float:
    return max(image_size) / REFERENCE_DIMENSION


@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int
    mean_ela: float
    surrounding_mean_ela: float

    @property
    def contrast_ratio(self) -> float:
        # Floor the denominator so a near-zero (noise-floor) surrounding
        # mean doesn't produce an explosive, meaningless ratio.
        denom = max(self.surrounding_mean_ela, RATIO_DENOMINATOR_FLOOR)
        return self.mean_ela / denom


@dataclass
class BlurRegion:
    x: int
    y: int
    w: int
    h: int
    mean_sharpness: float
    surrounding_sharpness: float
    # "deficit" = blurrier than surroundings (diffusion-inpainting signature).
    # "excess" = sharper/blockier than surroundings — e.g. a resampling/
    # upscale splice, which a blackhat-only pass is structurally blind to.
    polarity: str = "deficit"

    @property
    def deficit_ratio(self) -> float:
        # Direction-aware anomaly-magnitude ratio: however the blob departs
        # from its surroundings, how many times more extreme that departure
        # is. Named `deficit_ratio` for API/UI backward compatibility even
        # though it also covers the "excess" polarity.
        if self.polarity == "excess":
            denom = max(self.surrounding_sharpness, 1.0)
            return self.mean_sharpness / denom
        denom = max(self.mean_sharpness, 1.0)
        return self.surrounding_sharpness / denom


@dataclass
class NoiseRegion:
    x: int
    y: int
    w: int
    h: int
    mean_noise_var: float
    surrounding_noise_var: float
    # "deficit" = cleaner than surroundings (diffusion-inpainting signature).
    # "excess" = noisier than surroundings — e.g. a resampling/upscale
    # splice's block-quantization pattern, invisible to a blackhat-only pass.
    polarity: str = "deficit"

    @property
    def deficit_ratio(self) -> float:
        # Direction-aware anomaly-magnitude ratio; see BlurRegion.deficit_ratio.
        if self.polarity == "excess":
            denom = max(self.surrounding_noise_var, 1.0)
            return self.mean_noise_var / denom
        denom = max(self.mean_noise_var, 1.0)
        return self.surrounding_noise_var / denom


@dataclass
class PipelineResult:
    original_rgb: np.ndarray
    ela_rgb: np.ndarray
    morph_rgb: np.ndarray
    exif: dict
    was_png_synthetic: bool
    ela_max_diff: int
    luminosity_std: float
    regions: list[Region] = field(default_factory=list)
    blur_regions: list[BlurRegion] = field(default_factory=list)
    noise_regions: list[NoiseRegion] = field(default_factory=list)
    mrz: MrzResult | None = None
    corroborated: bool = False
    tamper_score: float = 0.0
    warnings: list[str] = field(default_factory=list)


def _extract_exif(image: Image.Image) -> dict:
    raw = image.getexif()
    if not raw:
        return {}
    out = {}
    for tag_id, value in raw.items():
        tag = ExifTags.TAGS.get(tag_id, str(tag_id))
        try:
            if isinstance(value, bytes):
                value = value.decode(errors="replace")
            out[tag] = value
        except Exception:
            continue
    return out


def _compute_ela(image: Image.Image, quality: int) -> tuple[Image.Image, int]:
    """Standard ELA: diff image against a JPEG resave at `quality`."""
    rgb = image.convert("RGB")
    buffer = BytesIO()
    rgb.save(buffer, "JPEG", quality=quality)
    buffer.seek(0)
    resaved = Image.open(buffer).convert("RGB")

    ela = ImageChops.difference(rgb, resaved)
    extrema = ela.getextrema()
    max_diff = max(channel[1] for channel in extrema) or 1
    scale = 255.0 / max_diff

    ela_arr = np.asarray(ela, dtype=np.float32) * scale
    ela_arr = np.clip(ela_arr, 0, 255).astype(np.uint8)
    return Image.fromarray(ela_arr), max_diff


def _luminosity_map(rgb_arr: np.ndarray) -> np.ndarray:
    """Max-channel luminosity per pixel, per the ELA methodology."""
    return rgb_arr.max(axis=2).astype(np.float32)


def _wiener_denoise(gray: np.ndarray) -> np.ndarray:
    """2-D adaptive Wiener filter to strip constant-power additive noise."""
    gray_f = gray.astype(np.float64)
    # wiener() divides by local variance, which is 0 on flat patches (e.g. a
    # plain background) — that's an expected, harmless nan/inf we clean up.
    with np.errstate(divide="ignore", invalid="ignore"):
        denoised = wiener(gray_f, mysize=5)
    denoised = np.nan_to_num(denoised, nan=0.0, posinf=255.0, neginf=0.0)
    denoised = np.clip(denoised, 0, 255)
    return denoised.astype(np.uint8)


def _scaled_odd_size(base: float, scale: float, minimum: int = 3) -> int:
    size = round(base * scale)
    size = max(minimum, size)
    return size if size % 2 == 1 else size + 1


def _morphological_reconstruction(
    gray: np.ndarray, scale: float
) -> tuple[np.ndarray, np.ndarray]:
    """Tophat + Bothat to reconstruct tampered-region contours.

    Tophat highlights bright anomalies against a locally-opened background;
    bothat (blackhat) highlights dark anomalies against a locally-closed
    background. Summing both surfaces suspicious regions regardless of
    polarity, which is what localizes the tamper contours.
    """
    kernel_size = _scaled_odd_size(MORPH_KERNEL_SIZE, scale)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
    bothat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    reconstructed = cv2.add(tophat, bothat)
    reconstructed = cv2.normalize(reconstructed, None, 0, 255, cv2.NORM_MINMAX)
    return reconstructed.astype(np.uint8), kernel


def _local_surrounding_mean(
    ela_gray: np.ndarray, x: int, y: int, w: int, h: int, pad: int
) -> float:
    """Mean ELA brightness of the ring immediately around a region.

    Forensic ELA comparison is local ("similar textures near each other
    should error-level similarly"), not global — a photo's flat background
    and its busy foreground are never expected to match.
    """
    height, width = ela_gray.shape
    x0, y0 = max(x - pad, 0), max(y - pad, 0)
    x1, y1 = min(x + w + pad, width), min(y + h + pad, height)

    ring_mask = np.ones((y1 - y0, x1 - x0), dtype=bool)
    inner_y0, inner_y1 = max(y - y0, 0), min(y - y0 + h, y1 - y0)
    inner_x0, inner_x1 = max(x - x0, 0), min(x - x0 + w, x1 - x0)
    ring_mask[inner_y0:inner_y1, inner_x0:inner_x1] = False

    ring_vals = ela_gray[y0:y1, x0:x1][ring_mask]
    if ring_vals.size == 0:
        return float(ela_gray.mean())
    return float(ring_vals.mean())


def _find_regions(
    reconstructed: np.ndarray, ela_gray: np.ndarray, scale: float
) -> list[Region]:
    min_region_area = MIN_REGION_AREA_FLOOR * (scale**2)
    ring_pad = max(10, round(LOCAL_RING_PAD * scale))

    _, binary = cv2.threshold(
        reconstructed, TAMPER_AREA_THRESHOLD, 255, cv2.THRESH_BINARY
    )
    binary = cv2.dilate(binary, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(
        binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    regions: list[Region] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_region_area:
            continue
        x, y, w, h = cv2.boundingRect(c)

        # Measure the mean over the actual flagged pixels, not the bounding
        # box — Tophat/Bothat often light up only a splice's edges (its
        # interior can be flat and near-zero), so averaging over the full
        # rectangle dilutes that signal with non-flagged pixels. Filling the
        # outer contour alone would still include any hollow interior, so
        # intersect with the thresholded binary mask to keep only pixels
        # that were actually flagged.
        contour_mask = np.zeros(ela_gray.shape, dtype=np.uint8)
        cv2.drawContours(contour_mask, [c], -1, 255, thickness=cv2.FILLED)
        flagged_mask = cv2.bitwise_and(contour_mask, binary)
        patch_mean = float(ela_gray[flagged_mask == 255].mean())

        local_mean = _local_surrounding_mean(ela_gray, x, y, w, h, pad=ring_pad)
        region = Region(
            x=x,
            y=y,
            w=w,
            h=h,
            mean_ela=patch_mean,
            surrounding_mean_ela=local_mean,
        )
        if region.mean_ela < ABSOLUTE_ELA_FLOOR:
            continue  # too faint in absolute terms — likely JPEG block noise
        if region.contrast_ratio < SUSPICIOUS_CONTRAST_RATIO:
            continue  # blends into its local neighborhood — not suspicious
        regions.append(region)

    regions.sort(key=lambda r: r.w * r.h, reverse=True)
    return regions


def _tamper_score(
    regions: list[Region], ela_max_diff: int, image_area: int
) -> float:
    if not regions:
        base = min(ela_max_diff / 255.0, 1.0) * 10  # faint baseline signal only
        return round(base, 1)

    area_fraction = sum(r.w * r.h for r in regions) / image_area
    strongest_contrast = max(r.contrast_ratio for r in regions)
    contrast_signal = min(max(strongest_contrast - SUSPICIOUS_CONTRAST_RATIO, 0), 2.0)
    score = 100 * min(area_fraction * 4, 0.4) + contrast_signal * 30
    return round(min(max(score, 0), 100), 1)


def _sharpness_map(gray: np.ndarray, scale: float) -> np.ndarray:
    """Local variance of the Laplacian — a texture/sharpness proxy.

    Crisp printed or photographed detail has high local Laplacian variance;
    smoothed/inpainted content has low variance. This has nothing to do with
    JPEG compression, so it can catch edits that leave no ELA signature at
    all. The raw variance is rescaled against this image's own 99th
    percentile (mirroring how ELA rescales against its own max diff), so a
    fixed absolute floor stays meaningful across images of very different
    contrast/detail levels.
    """
    lap = cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F)
    window = _scaled_odd_size(SHARPNESS_WINDOW, scale)
    mean = cv2.boxFilter(lap, -1, (window, window))
    mean_sq = cv2.boxFilter(lap * lap, -1, (window, window))
    local_var = np.clip(mean_sq - mean * mean, 0, None)

    reference = np.percentile(local_var, 99) or 1.0
    return np.clip(local_var / reference * 255.0, 0, 255).astype(np.float32)


def _find_blur_regions(
    sharpness: np.ndarray, scale: float
) -> tuple[list[BlurRegion], np.ndarray]:
    """Contours where local sharpness departs — either direction — from its surroundings.

    Tophat catches content *sharper/blockier* than its surroundings (e.g. a
    resampling/upscale splice's mosaic pattern); blackhat catches content
    *blurrier* than its surroundings (the diffusion-inpainting signature
    this channel originally targeted). Summing both, mirroring how
    `_morphological_reconstruction` treats the ELA map, means a region isn't
    structurally invisible just because its anomaly runs the "wrong" way —
    verified against a real resampling-composite image where the pasted
    element's canopy was measurably *noisier and sharper* than its
    surroundings, which a blackhat-only pass could never have flagged.
    """
    min_region_area = MIN_BLUR_REGION_AREA_FLOOR * (scale**2)
    ring_pad = max(10, round(BLUR_RING_PAD * scale))
    kernel_size = _scaled_odd_size(BLUR_MORPH_KERNEL_SIZE, scale)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    excess_kernel_size = _scaled_odd_size(EXCESS_MORPH_KERNEL_SIZE, scale)
    excess_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (excess_kernel_size, excess_kernel_size))

    sharpness_u8 = sharpness.astype(np.uint8)
    # Deliberately different kernels: see EXCESS_MORPH_KERNEL_SIZE note above.
    tophat = cv2.morphologyEx(sharpness_u8, cv2.MORPH_TOPHAT, excess_kernel)
    blackhat = cv2.morphologyEx(sharpness_u8, cv2.MORPH_BLACKHAT, kernel)
    combined = cv2.add(tophat, blackhat)

    _, binary = cv2.threshold(combined, BLUR_TAMPER_THRESHOLD, 255, cv2.THRESH_BINARY)
    binary = cv2.dilate(binary, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions: list[BlurRegion] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_region_area:
            continue
        x, y, w, h = cv2.boundingRect(c)

        contour_mask = np.zeros(sharpness.shape, dtype=np.uint8)
        cv2.drawContours(contour_mask, [c], -1, 255, thickness=cv2.FILLED)
        flagged_mask = cv2.bitwise_and(contour_mask, binary)
        blob_sharpness = float(sharpness[flagged_mask == 255].mean())

        surrounding = _local_surrounding_mean(sharpness, x, y, w, h, pad=ring_pad)
        polarity = "excess" if blob_sharpness > surrounding else "deficit"
        region = BlurRegion(
            x=x, y=y, w=w, h=h,
            mean_sharpness=blob_sharpness,
            surrounding_sharpness=surrounding,
            polarity=polarity,
        )
        # The value that must be "meaningfully high" to trust the anomaly is
        # whichever side is the anomalous one: surrounding for a deficit
        # (otherwise a dip against a near-zero baseline is meaningless),
        # the blob itself for an excess (otherwise a spike against noise is
        # meaningless).
        floor_value = blob_sharpness if polarity == "excess" else surrounding
        if floor_value < ABSOLUTE_SURROUNDING_SHARPNESS_FLOOR:
            continue
        if region.deficit_ratio < BLUR_DEFICIT_RATIO:
            continue  # not meaningfully anomalous vs. what's around it
        if polarity == "excess" and area > MAX_EXCESS_AREA_FRACTION * sharpness.size:
            continue  # too large to be a plausible pasted/resampled element
        regions.append(region)

    regions.sort(key=lambda r: r.w * r.h, reverse=True)
    return regions, combined


def _blur_tamper_score(regions: list[BlurRegion], image_area: int) -> float:
    if not regions:
        return 0.0
    area_fraction = sum(r.w * r.h for r in regions) / image_area
    strongest_deficit = max(r.deficit_ratio for r in regions)
    deficit_signal = min(max(strongest_deficit - BLUR_DEFICIT_RATIO, 0), 4.0)
    score = 100 * min(area_fraction * 4, 0.4) + deficit_signal * 15
    return round(min(max(score, 0), 100), 1)


def _noise_residual_variance_map(gray: np.ndarray, scale: float) -> np.ndarray:
    """Local variance of the Wiener-denoise residual — a noise-floor proxy.

    A genuine photograph carries a fairly consistent sensor-read-noise +
    JPEG-quantization noise floor everywhere. Reusing the same Wiener
    denoiser as the ELA channel (but run on the actual image, not the ELA
    map) isolates that noise as `original - denoised`; its local variance is
    largely independent of Laplacian sharpness, so it can catch inpainted
    content that is *texturally* sharp but has an unnaturally clean residual.
    Rescaled against this image's own 99th percentile, mirroring the
    sharpness map, so a fixed absolute floor stays meaningful across images.
    """
    denoised = _wiener_denoise(gray).astype(np.float32)
    residual = gray.astype(np.float32) - denoised

    window = _scaled_odd_size(NOISE_WINDOW, scale)
    mean = cv2.boxFilter(residual, -1, (window, window))
    mean_sq = cv2.boxFilter(residual * residual, -1, (window, window))
    local_var = np.clip(mean_sq - mean * mean, 0, None)

    reference = np.percentile(local_var, 99) or 1.0
    return np.clip(local_var / reference * 255.0, 0, 255).astype(np.float32)


def _find_noise_regions(
    noise_var: np.ndarray, scale: float
) -> tuple[list[NoiseRegion], np.ndarray]:
    """Contours where local noise-residual variance departs — either direction — from its surroundings.

    Tophat catches content *noisier* than its surroundings (e.g. a
    resampling/upscale splice's block-quantization pattern reading as
    elevated high-frequency residual); blackhat catches content *cleaner*
    than its surroundings (the diffusion-inpainting signature this channel
    originally targeted). See `_find_blur_regions` for the same reasoning —
    a blackhat-only pass is structurally blind to the opposite polarity.
    """
    min_region_area = MIN_NOISE_REGION_AREA_FLOOR * (scale**2)
    ring_pad = max(10, round(NOISE_RING_PAD * scale))
    kernel_size = _scaled_odd_size(NOISE_MORPH_KERNEL_SIZE, scale)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    excess_kernel_size = _scaled_odd_size(EXCESS_MORPH_KERNEL_SIZE, scale)
    excess_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (excess_kernel_size, excess_kernel_size))

    noise_u8 = noise_var.astype(np.uint8)
    # Deliberately different kernels: see EXCESS_MORPH_KERNEL_SIZE note above.
    tophat = cv2.morphologyEx(noise_u8, cv2.MORPH_TOPHAT, excess_kernel)
    blackhat = cv2.morphologyEx(noise_u8, cv2.MORPH_BLACKHAT, kernel)
    combined = cv2.add(tophat, blackhat)

    _, binary = cv2.threshold(combined, NOISE_TAMPER_THRESHOLD, 255, cv2.THRESH_BINARY)
    binary = cv2.dilate(binary, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions: list[NoiseRegion] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_region_area:
            continue
        x, y, w, h = cv2.boundingRect(c)

        contour_mask = np.zeros(noise_var.shape, dtype=np.uint8)
        cv2.drawContours(contour_mask, [c], -1, 255, thickness=cv2.FILLED)
        flagged_mask = cv2.bitwise_and(contour_mask, binary)
        blob_noise = float(noise_var[flagged_mask == 255].mean())

        surrounding = _local_surrounding_mean(noise_var, x, y, w, h, pad=ring_pad)
        polarity = "excess" if blob_noise > surrounding else "deficit"
        region = NoiseRegion(
            x=x, y=y, w=w, h=h,
            mean_noise_var=blob_noise,
            surrounding_noise_var=surrounding,
            polarity=polarity,
        )
        floor_value = blob_noise if polarity == "excess" else surrounding
        if floor_value < ABSOLUTE_SURROUNDING_NOISE_FLOOR:
            continue
        if region.deficit_ratio < NOISE_DEFICIT_RATIO:
            continue  # not meaningfully anomalous vs. what's around it
        if polarity == "excess" and area > MAX_EXCESS_AREA_FRACTION * noise_var.size:
            continue  # too large to be a plausible pasted/resampled element
        regions.append(region)

    regions.sort(key=lambda r: r.w * r.h, reverse=True)
    return regions, combined


def _noise_tamper_score(regions: list[NoiseRegion], image_area: int) -> float:
    if not regions:
        return 0.0
    area_fraction = sum(r.w * r.h for r in regions) / image_area
    strongest_deficit = max(r.deficit_ratio for r in regions)
    deficit_signal = min(max(strongest_deficit - NOISE_DEFICIT_RATIO, 0), 4.0)
    score = 100 * min(area_fraction * 4, 0.4) + deficit_signal * 15
    return round(min(max(score, 0), 100), 1)


def _boxes_overlap(
    a_x: int, a_y: int, a_w: int, a_h: int,
    b_x: int, b_y: int, b_w: int, b_h: int,
    pad: int,
) -> bool:
    ax0, ay0, ax1, ay1 = a_x - pad, a_y - pad, a_x + a_w + pad, a_y + a_h + pad
    bx0, by0, bx1, by1 = b_x, b_y, b_x + b_w, b_y + b_h
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)


def _has_cross_channel_corroboration(
    regions: list[Region],
    blur_regions: list[BlurRegion],
    noise_regions: list[NoiseRegion],
    pad: int,
) -> bool:
    """True if any two *different* channels flagged overlapping regions.

    Each channel is computed independently from a different signal (JPEG
    error, sharpness, noise-residual variance), so two of them agreeing on
    the same location is much stronger evidence than either channel's own
    ratio-above-threshold score — see the CORROBORATION_BONUS module note.
    """
    channels: list[list] = [regions, blur_regions, noise_regions]
    for i in range(len(channels)):
        for j in range(i + 1, len(channels)):
            for a in channels[i]:
                for b in channels[j]:
                    if _boxes_overlap(a.x, a.y, a.w, a.h, b.x, b.y, b.w, b.h, pad):
                        return True
    return False


def _build_overlay(
    base_gray: np.ndarray,
    ela_regions: list[Region],
    blur_regions: list[BlurRegion],
    noise_regions: list[NoiseRegion],
) -> np.ndarray:
    overlay = cv2.cvtColor(base_gray, cv2.COLOR_GRAY2RGB)
    for r in ela_regions:
        cv2.rectangle(overlay, (r.x, r.y), (r.x + r.w, r.y + r.h), (255, 60, 60), 2)
    for r in blur_regions:
        cv2.rectangle(overlay, (r.x, r.y), (r.x + r.w, r.y + r.h), (255, 165, 0), 2)
    for r in noise_regions:
        cv2.rectangle(overlay, (r.x, r.y), (r.x + r.w, r.y + r.h), (200, 0, 200), 2)
    return overlay


def run_pipeline(image_bytes: bytes, original_filename: str) -> PipelineResult:
    image = Image.open(BytesIO(image_bytes))
    exif = _extract_exif(image)
    warnings: list[str] = []
    scale = _scale_factor(image.size)

    was_png_synthetic = image.format == "PNG"
    resave_quality = ELA_QUALITY
    working_image = image
    if was_png_synthetic:
        # PNG is lossless -> no compression artifacts to diff against. Bake in
        # a first-generation JPEG so a second resave produces a meaningful
        # error-level signal ("synthetic ELA").
        buf = BytesIO()
        image.convert("RGB").save(buf, "JPEG", quality=ELA_QUALITY)
        buf.seek(0)
        working_image = Image.open(buf)
        resave_quality = SYNTHETIC_ELA_RESAVE_QUALITY
        warnings.append(
            "Source was PNG (lossless). Applied Synthetic ELA by baking in a "
            "first-generation JPEG before analysis — results are a weaker "
            "signal than native-JPEG ELA."
        )

    original_rgb = np.asarray(working_image.convert("RGB"))
    ela_image, ela_max_diff = _compute_ela(working_image, resave_quality)
    ela_rgb = np.asarray(ela_image)
    ela_gray = cv2.cvtColor(ela_rgb, cv2.COLOR_RGB2GRAY)

    luminosity = _luminosity_map(original_rgb)
    luminosity_std = float(luminosity.std())

    denoised = _wiener_denoise(ela_gray)
    reconstructed, _kernel = _morphological_reconstruction(denoised, scale)
    regions = _find_regions(reconstructed, ela_gray, scale)

    original_gray = cv2.cvtColor(original_rgb, cv2.COLOR_RGB2GRAY)
    sharpness = _sharpness_map(original_gray, scale)
    blur_regions, _blur_blackhat = _find_blur_regions(sharpness, scale)

    noise_var = _noise_residual_variance_map(original_gray, scale)
    noise_regions, _noise_blackhat = _find_noise_regions(noise_var, scale)

    morph_overlay = _build_overlay(reconstructed, regions, blur_regions, noise_regions)

    image_area = original_rgb.shape[0] * original_rgb.shape[1]
    ela_score = _tamper_score(regions, ela_max_diff, image_area)
    blur_score = _blur_tamper_score(blur_regions, image_area)
    noise_score = _noise_tamper_score(noise_regions, image_area)
    tamper_score = max(ela_score, blur_score, noise_score)

    corroboration_pad = max(10, round(CORROBORATION_PAD * scale))
    corroborated = _has_cross_channel_corroboration(
        regions, blur_regions, noise_regions, pad=corroboration_pad
    )
    if corroborated:
        tamper_score = min(100.0, tamper_score + CORROBORATION_BONUS)

    mrz_result = validate_mrz(original_rgb)
    if mrz_result.parse_error:
        warnings.append(
            f"MRZ checksum validation unavailable: {mrz_result.parse_error}"
        )
    elif mrz_result.any_mismatch:
        mismatched = sum(1 for c in mrz_result.checks if not c.matches)
        # A single mismatch could be an OCR misread rather than tampering;
        # two or more independent check digits failing together is much
        # harder to explain as OCR noise, so it's weighted as near-certain.
        mrz_score = 90.0 if mismatched >= 2 else 55.0
        tamper_score = max(tamper_score, mrz_score)
        if mismatched < 2:
            warnings.append(
                "MRZ check-digit mismatch found on a single field — this is "
                "strong evidence of tampering, but could rarely be an OCR "
                "misread rather than a genuine edit. Verify visually."
            )

    if ela_max_diff < 6:
        warnings.append(
            "ELA max error is extremely low — the image may have been "
            "resaved many times at low quality, which can wash out tampering "
            "evidence entirely."
        )
    if luminosity.mean() < 35:
        warnings.append(
            "Image is very dark overall; ELA and luminosity analysis are "
            "less reliable on underexposed regions."
        )

    return PipelineResult(
        original_rgb=original_rgb,
        ela_rgb=ela_rgb,
        morph_rgb=morph_overlay,
        exif=exif,
        was_png_synthetic=was_png_synthetic,
        ela_max_diff=ela_max_diff,
        luminosity_std=luminosity_std,
        regions=regions,
        blur_regions=blur_regions,
        noise_regions=noise_regions,
        mrz=mrz_result,
        corroborated=corroborated,
        tamper_score=tamper_score,
        warnings=warnings,
    )
