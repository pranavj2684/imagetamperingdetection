"""MRZ (machine-readable zone) checksum validation — ICAO Doc 9303 TD1 format.

Unlike every other channel in pipeline.py, this doesn't look at pixels at
all. It OCRs the bottom three lines of an ID document, parses the standard
TD1 MRZ layout, and recomputes each embedded check digit. A checksum
mismatch is a near-certain tamper signal *for the fields it covers*: editing
visible text in an image editor changes the printed characters but not the
check digits encoded elsewhere in the same MRZ, so a naive edit — exactly
the failure mode that turned out to be invisible to ELA/blur/noise in
testing — breaks the checksum deterministically.

This is intentionally scoped to TD1 (3 lines x 30 chars, used on ID cards
and residence permits). TD3 (passports, 2 lines x 44 chars) uses the same
check-digit algorithm but a different field layout and isn't handled here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import pytesseract
    _PYTESSERACT_AVAILABLE = True
except ImportError:
    _PYTESSERACT_AVAILABLE = False

if _PYTESSERACT_AVAILABLE:
    import shutil

    # pytesseract only finds the binary via PATH. On Windows the official
    # installer doesn't add it to PATH by default, so fall back to the
    # standard install location rather than requiring a system-wide PATH
    # edit just to run this POC.
    _WINDOWS_DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if not shutil.which("tesseract") and Path(_WINDOWS_DEFAULT_TESSERACT).exists():
        pytesseract.pytesseract.tesseract_cmd = _WINDOWS_DEFAULT_TESSERACT

MRZ_LINE_LENGTH = 30
MRZ_LINE_COUNT = 3
CHECK_DIGIT_WEIGHTS = (7, 3, 1)
MRZ_CHAR_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"


@dataclass
class CheckDigitResult:
    field: str
    data: str
    expected: int
    actual: int

    @property
    def matches(self) -> bool:
        return self.expected == self.actual


@dataclass
class MrzResult:
    raw_lines: list[str]
    checks: list[CheckDigitResult]
    ocr_available: bool
    parse_error: str | None = None

    @property
    def all_valid(self) -> bool:
        return bool(self.checks) and all(c.matches for c in self.checks)

    @property
    def any_mismatch(self) -> bool:
        return any(not c.matches for c in self.checks)


def _char_value(c: str) -> int:
    if c == "<":
        return 0
    if c.isdigit():
        return int(c)
    if c.isalpha():
        return ord(c.upper()) - ord("A") + 10
    raise ValueError(f"Invalid MRZ character: {c!r}")


def _compute_check_digit(data: str) -> int:
    total = 0
    for i, c in enumerate(data):
        total += _char_value(c) * CHECK_DIGIT_WEIGHTS[i % 3]
    return total % 10


def _parse_check_digit_char(c: str) -> int | None:
    # The printed check digit is occasionally '<' on some issuers' optional
    # fields when that field is unused; treat as "not checkable" rather than
    # a hard parse error.
    if c == "<":
        return None
    if not c.isdigit():
        return None
    return int(c)


class TesseractBinaryMissing(Exception):
    pass


def _extract_mrz_text(image_rgb: np.ndarray) -> list[str]:
    """OCR the bottom band of the image, where a TD1 MRZ is printed."""
    if not _PYTESSERACT_AVAILABLE:
        raise TesseractBinaryMissing("pytesseract package not installed")

    height, width = image_rgb.shape[:2]
    # MRZ occupies roughly the bottom third of a TD1-format card. Verified
    # empirically against a real IRP card render: 0.72 sliced through the
    # top MRZ line's ascenders, silently dropping it and leaving only 2 of
    # 3 lines; 0.63 captures the full 3-line block with margin to spare.
    band = image_rgb[int(height * 0.63):, :]

    import cv2
    gray = cv2.cvtColor(band, cv2.COLOR_RGB2GRAY)
    # Upscale + threshold: OCR accuracy on small monospace MRZ text benefits
    # heavily from both, since source photos are rarely shot MRZ-first.
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    config = (
        "--psm 6 "
        f"-c tessedit_char_whitelist={MRZ_CHAR_WHITELIST}"
    )
    try:
        text = pytesseract.image_to_string(thresh, config=config)
    except pytesseract.TesseractNotFoundError as exc:
        raise TesseractBinaryMissing(
            "Tesseract binary not found on PATH"
        ) from exc

    lines = [ln.strip().upper() for ln in text.splitlines() if ln.strip()]
    # Keep only lines that look MRZ-shaped (mostly whitelist chars, close to
    # the expected length) — OCR on a non-MRZ image produces noise lines we
    # don't want to feed into the checksum parser.
    candidates = [
        ln for ln in lines
        if len(ln) >= MRZ_LINE_LENGTH - 4
        and all(c in MRZ_CHAR_WHITELIST for c in ln)
    ]
    return candidates[-MRZ_LINE_COUNT:] if len(candidates) >= MRZ_LINE_COUNT else []


def _normalize_line(line: str) -> str:
    # OCR frequently drops or adds a trailing/leading filler character;
    # pad/truncate to the fixed TD1 width rather than rejecting the whole
    # line outright.
    line = line[:MRZ_LINE_LENGTH]
    return line.ljust(MRZ_LINE_LENGTH, "<")


def validate_mrz(image_rgb: np.ndarray) -> MrzResult:
    try:
        lines = _extract_mrz_text(image_rgb)
    except TesseractBinaryMissing as exc:
        return MrzResult(
            raw_lines=[],
            checks=[],
            ocr_available=_PYTESSERACT_AVAILABLE,
            parse_error=f"{exc} — MRZ validation skipped",
        )

    if len(lines) != MRZ_LINE_COUNT:
        return MrzResult(
            raw_lines=lines,
            checks=[],
            ocr_available=_PYTESSERACT_AVAILABLE,
            parse_error="OCR did not find a 3-line TD1 MRZ block",
        )

    line1, line2, _line3 = (_normalize_line(ln) for ln in lines)
    checks: list[CheckDigitResult] = []

    try:
        doc_number_field = line1[5:14]
        doc_number_check = _parse_check_digit_char(line1[14])
        if doc_number_check is not None:
            checks.append(CheckDigitResult(
                "document_number", doc_number_field,
                doc_number_check, _compute_check_digit(doc_number_field),
            ))

        birth_date_field = line2[0:6]
        birth_date_check = _parse_check_digit_char(line2[6])
        if birth_date_check is not None:
            checks.append(CheckDigitResult(
                "birth_date", birth_date_field,
                birth_date_check, _compute_check_digit(birth_date_field),
            ))

        expiry_date_field = line2[8:14]
        expiry_date_check = _parse_check_digit_char(line2[14])
        if expiry_date_check is not None:
            checks.append(CheckDigitResult(
                "expiry_date", expiry_date_field,
                expiry_date_check, _compute_check_digit(expiry_date_field),
            ))

        composite_field = line1[5:30] + line2[0:7] + line2[8:15] + line2[18:29]
        composite_check = _parse_check_digit_char(line2[29])
        if composite_check is not None:
            checks.append(CheckDigitResult(
                "composite", composite_field,
                composite_check, _compute_check_digit(composite_field),
            ))
    except (IndexError, ValueError) as exc:
        return MrzResult(
            raw_lines=[line1, line2, _line3],
            checks=[],
            ocr_available=_PYTESSERACT_AVAILABLE,
            parse_error=f"MRZ parse failed: {exc}",
        )

    return MrzResult(
        raw_lines=[line1, line2, _line3],
        checks=checks,
        ocr_available=_PYTESSERACT_AVAILABLE,
    )
