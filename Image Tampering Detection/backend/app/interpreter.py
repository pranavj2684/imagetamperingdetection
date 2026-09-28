"""Rule-based 'AI Interpreter': a mock RAG layer.

Retrieval: computed image features are matched against a local knowledge
base of forensic ELA heuristics (KNOWLEDGE_BASE) to find applicable entries.
Generation: matched entries are turned into natural-language findings,
templated with the specific region/feature values that triggered them.
"""
from __future__ import annotations

from .pipeline import BlurRegion, NoiseRegion, PipelineResult, Region

SOFTWARE_ARTIFACT_MARKERS = ("photoshop", "gimp", "adobe", "lightroom", "affinity")

KNOWLEDGE_BASE = [
    {
        "id": "software-artifact",
        "trigger": "exif_software",
        "explanation": (
            "EXIF Software tag reports '{software}'. Editing tools like this "
            "often sharpen edges and boost contrast on save, which raises ELA "
            "brightness uniformly — this alone indicates the tool was used, "
            "not that tampering occurred."
        ),
    },
    {
        "id": "high-contrast-splice",
        "trigger": "region_high_contrast",
        "explanation": (
            "Region at ({x}, {y}) sized {w}x{h}px shows ELA brightness "
            "{mean_ela:.1f}, about {ratio:.1f}x its immediate surroundings "
            "({surrounding_mean_ela:.1f}). Consistently similar textures "
            "should error-level the same way as their neighbors, so this "
            "local contrast jump suggests a digital splice or paste from a "
            "differently-compressed source."
        ),
    },
    {
        "id": "moderate-contrast",
        "trigger": "region_moderate_contrast",
        "explanation": (
            "Region at ({x}, {y}) sized {w}x{h}px is mildly brighter than its "
            "surroundings ({ratio:.1f}x average). Could be a genuine edit, or "
            "could be an edge/texture naturally prone to higher ELA response "
            "(e.g. fine detail or a high-contrast color boundary) — treat as "
            "inconclusive without corroborating evidence."
        ),
    },
    {
        "id": "yuv-color-caveat",
        "trigger": "always",
        "explanation": (
            "Note: JPEG compresses in YUV space, so naturally high-contrast "
            "color boundaries (e.g. green against purple/magenta) can show "
            "elevated ELA values without any tampering. Cross-check flagged "
            "regions against the original image before concluding splice."
        ),
    },
    {
        "id": "low-signal",
        "trigger": "no_regions",
        "explanation": (
            "No regions crossed the tamper-localization threshold. Either the "
            "image is unmodified, or modifications were too subtle "
            "(single-pixel edits, minor color adjustments) for ELA to "
            "surface — ELA has known blind spots here."
        ),
    },
    {
        "id": "blur-deficit",
        "trigger": "region_blur_deficit",
        "explanation": (
            "Region at ({x}, {y}) sized {w}x{h}px is about {ratio:.1f}x "
            "blurrier than its immediate surroundings, which are otherwise "
            "sharply detailed. Unlike the compression-error findings above, "
            "this doesn't rely on JPEG artifacts at all — it's a sharpness "
            "mismatch, the kind of signature AI content-aware fill/inpainting "
            "('smart eraser'-style tools) can leave behind even when it "
            "produces no ELA anomaly whatsoever."
        ),
    },
    {
        "id": "blur-excess",
        "trigger": "region_blur_excess",
        "explanation": (
            "Region at ({x}, {y}) sized {w}x{h}px is about {ratio:.1f}x "
            "sharper/blockier than its immediate surroundings — the opposite "
            "anomaly from the sharpness-deficit case above. This pattern "
            "shows up when an element is pasted in at a different native "
            "resolution than its new background and force-scaled to fit: "
            "the upscale/interpolation leaves a mosaic-like block pattern "
            "that reads as artificially high local contrast."
        ),
    },
    {
        "id": "mrz-mismatch",
        "trigger": "mrz_mismatch",
        "explanation": (
            "MRZ check-digit mismatch on field '{field}': printed data "
            "'{data}' encodes check digit {expected}, but the document "
            "prints {actual}. Unlike every other finding here, this doesn't "
            "come from pixel analysis at all — it's a deterministic "
            "cross-check against the document's own embedded checksum. "
            "Editing visible MRZ-adjacent text without recomputing this "
            "digit is exactly the kind of edit that stays invisible to ELA/"
            "blur/noise but breaks this check every time."
        ),
    },
    {
        "id": "mrz-valid",
        "trigger": "mrz_valid",
        "explanation": (
            "MRZ checksum validation passed on all {count} checkable "
            "fields — no evidence of tampering in the document's "
            "machine-readable zone specifically (this doesn't rule out "
            "edits elsewhere on the document outside the MRZ)."
        ),
    },
    {
        "id": "noise-deficit",
        "trigger": "region_noise_deficit",
        "explanation": (
            "Region at ({x}, {y}) sized {w}x{h}px has a noise-residual floor "
            "about {ratio:.1f}x cleaner than its immediate surroundings, "
            "which otherwise carry a consistent camera/JPEG noise floor. "
            "This is a third, independent channel from the two above: it "
            "doesn't rely on compression mismatch or a sharpness dip, so it "
            "can catch generative-fill content that is both ELA-silent and "
            "locally sharp, but fails to reproduce the sensor noise floor of "
            "the surrounding photograph."
        ),
    },
    {
        "id": "noise-excess",
        "trigger": "region_noise_excess",
        "explanation": (
            "Region at ({x}, {y}) sized {w}x{h}px has a noise-residual floor "
            "about {ratio:.1f}x noisier than its immediate surroundings — "
            "the opposite anomaly from the noise-deficit case above. Like "
            "the sharpness-excess finding, this is consistent with a "
            "resampling/upscale splice: the block-quantization pattern left "
            "by forcing a differently-sized element to fit reads as elevated "
            "high-frequency residual, not a clean noise floor."
        ),
    },
    {
        "id": "cross-channel-corroboration",
        "trigger": "corroborated",
        "explanation": (
            "Two or more independently-computed channels above (compression "
            "error, sharpness, and/or noise-residual variance) flagged "
            "overlapping regions. Each channel measures a completely "
            "different signal, so agreement between them is much stronger "
            "evidence of tampering than any single channel's ratio alone — "
            "this bumped the overall tamper score up accordingly."
        ),
    },
]


def _retrieve(result: PipelineResult) -> list[dict]:
    matched: list[dict] = []
    software = str(result.exif.get("Software", ""))
    if any(marker in software.lower() for marker in SOFTWARE_ARTIFACT_MARKERS):
        matched.append(
            {**_by_id("software-artifact"), "software": software}
        )

    for region in result.regions[:5]:  # cap report length to top regions
        ratio = region.contrast_ratio
        if ratio >= 10.0:
            matched.append(
                {
                    **_by_id("high-contrast-splice"),
                    **_region_fields(region),
                    "ratio": ratio,
                }
            )
        elif ratio >= 5.0:
            matched.append(
                {
                    **_by_id("moderate-contrast"),
                    **_region_fields(region),
                    "ratio": ratio,
                }
            )

    if not result.regions:
        matched.append(_by_id("low-signal"))

    for region in result.blur_regions[:5]:
        entry_id = "blur-excess" if region.polarity == "excess" else "blur-deficit"
        matched.append(
            {
                **_by_id(entry_id),
                **_blur_region_fields(region),
                "ratio": region.deficit_ratio,
            }
        )

    for region in result.noise_regions[:5]:
        entry_id = "noise-excess" if region.polarity == "excess" else "noise-deficit"
        matched.append(
            {
                **_by_id(entry_id),
                **_noise_region_fields(region),
                "ratio": region.deficit_ratio,
            }
        )

    if result.corroborated:
        matched.append(_by_id("cross-channel-corroboration"))

    if result.mrz is not None and not result.mrz.parse_error:
        if result.mrz.any_mismatch:
            for check in result.mrz.checks:
                if not check.matches:
                    matched.append({
                        **_by_id("mrz-mismatch"),
                        "field": check.field,
                        "data": check.data,
                        "expected": check.expected,
                        "actual": check.actual,
                    })
        elif result.mrz.checks:
            matched.append({
                **_by_id("mrz-valid"),
                "count": len(result.mrz.checks),
            })

    matched.append(_by_id("yuv-color-caveat"))
    return matched


def _by_id(entry_id: str) -> dict:
    return next(e for e in KNOWLEDGE_BASE if e["id"] == entry_id).copy()


def _region_fields(region: Region) -> dict:
    return {
        "x": region.x,
        "y": region.y,
        "w": region.w,
        "h": region.h,
        "mean_ela": region.mean_ela,
        "surrounding_mean_ela": region.surrounding_mean_ela,
    }


def _blur_region_fields(region: BlurRegion) -> dict:
    return {
        "x": region.x,
        "y": region.y,
        "w": region.w,
        "h": region.h,
    }


def _noise_region_fields(region: NoiseRegion) -> dict:
    return {
        "x": region.x,
        "y": region.y,
        "w": region.w,
        "h": region.h,
    }


def generate_report(result: PipelineResult) -> list[str]:
    entries = _retrieve(result)
    report = []
    for entry in entries:
        try:
            report.append(entry["explanation"].format(**entry))
        except KeyError:
            report.append(entry["explanation"])
    return report


def verdict(tamper_score: float) -> str:
    if tamper_score >= 60:
        return "Likely tampered"
    if tamper_score >= 30:
        return "Possibly tampered — inconclusive"
    return "No strong evidence of tampering"
