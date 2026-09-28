from __future__ import annotations

import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .interpreter import generate_report, verdict
from .pipeline import run_pipeline

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png"}

app = FastAPI(title="Image Tampering Detection POC")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/results", StaticFiles(directory=RESULTS_DIR), name="results")


def _save_rgb(arr: np.ndarray, path: Path) -> None:
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(path), bgr)


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(415, f"Unsupported content type: {file.content_type}")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(400, "Empty file")

    try:
        result = run_pipeline(image_bytes, file.filename or "upload")
    except Exception as exc:  # surface a readable error to the client
        raise HTTPException(422, f"Could not process image: {exc}") from exc

    job_id = uuid.uuid4().hex[:12]
    job_dir = RESULTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    _save_rgb(result.original_rgb, job_dir / "original.png")
    _save_rgb(result.ela_rgb, job_dir / "ela.png")
    _save_rgb(result.morph_rgb, job_dir / "morph.png")

    report = generate_report(result)

    return {
        "job_id": job_id,
        "images": {
            "original": f"/results/{job_id}/original.png",
            "ela": f"/results/{job_id}/ela.png",
            "morphological": f"/results/{job_id}/morph.png",
        },
        "tamper_score": result.tamper_score,
        "verdict": verdict(result.tamper_score),
        "exif": result.exif,
        "was_png_synthetic": result.was_png_synthetic,
        "ela_max_diff": result.ela_max_diff,
        "luminosity_std": round(result.luminosity_std, 2),
        "regions": [
            {
                "x": r.x,
                "y": r.y,
                "w": r.w,
                "h": r.h,
                "mean_ela": round(r.mean_ela, 2),
                "contrast_ratio": round(r.contrast_ratio, 2),
            }
            for r in result.regions
        ],
        "blur_regions": [
            {
                "x": r.x,
                "y": r.y,
                "w": r.w,
                "h": r.h,
                "deficit_ratio": round(r.deficit_ratio, 2),
                "polarity": r.polarity,
            }
            for r in result.blur_regions
        ],
        "noise_regions": [
            {
                "x": r.x,
                "y": r.y,
                "w": r.w,
                "h": r.h,
                "deficit_ratio": round(r.deficit_ratio, 2),
                "polarity": r.polarity,
            }
            for r in result.noise_regions
        ],
        "corroborated": result.corroborated,
        "warnings": result.warnings,
        "report": report,
        "mrz": (
            {
                "ocr_available": result.mrz.ocr_available,
                "parse_error": result.mrz.parse_error,
                "all_valid": result.mrz.all_valid,
                "checks": [
                    {
                        "field": c.field,
                        "expected": c.expected,
                        "actual": c.actual,
                        "matches": c.matches,
                    }
                    for c in result.mrz.checks
                ],
            }
            if result.mrz is not None
            else None
        ),
    }


@app.get("/api/health")
async def health():
    return {"status": "ok"}
