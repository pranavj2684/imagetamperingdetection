# Image Tampering Detection & Localization — Local POC

A local proof of concept that analyzes an uploaded image, localizes suspicious
regions via Error Level Analysis (ELA) and morphological reconstruction, and
generates a plain-English interpretation of the findings.

## Architecture

```
Image Tampering Detection/
├── backend/            FastAPI service (image processing pipeline)
│   ├── app/
│   │   ├── main.py         API endpoints
│   │   ├── pipeline.py     EXIF → ELA → luminosity → Wiener denoise → bidirectional Tophat/Bothat
│   │   ├── mrz.py          MRZ OCR + ICAO 9303 checksum validation
│   │   └── interpreter.py  Rule-based "AI Interpreter" (mock RAG report generator)
│   ├── requirements.txt
│   └── results/         Generated images per analysis job (gitignored)
└── my-web-app/          React (Vite) + Tailwind dashboard, Material-inspired dark theme
    └── src/
        ├── App.jsx
        └── components/  Dropzone, ThreePane, ScoreBadge, ReportPanel, ExifPanel, Icon, Surface
```

### Processing pipeline (`backend/app/pipeline.py`)

1. **Metadata extraction** — pulls EXIF tags (e.g. `Software`) to flag known
   editing-tool traces (Photoshop, GIMP, Lightroom, …).
2. **Error Level Analysis** — resaves the image as JPEG at quality 95 and
   diffs it against the original. PNGs have no compression history to diff
   against, so they're first baked into a first-generation JPEG at quality 95
   ("Synthetic ELA") before a second resave at quality 90 produces the
   comparison signal.
3. **Luminosity analysis** — per-pixel max(R, G, B) intensity, used as a
   lighting-consistency signal.
4. **Adaptive Wiener filter** (`scipy.signal.wiener`) — removes constant-power
   additive noise from the ELA output before localization.
5. **Morphological reconstruction** — `cv2.morphologyEx` with `MORPH_TOPHAT`
   and `MORPH_BLACKHAT` reconstructs bright and dark contour anomalies; the
   combined map is thresholded into bounding-box regions.
6. **Sharpness-anomaly detection (bidirectional)** — local Laplacian-variance
   departure from surroundings, in *either* direction:
   - **Deficit** (blackhat): blurrier than surroundings — the signature of
     AI content-aware fill/inpainting edits that leave no ELA signature.
   - **Excess** (tophat, small dedicated kernel): sharper/blockier than
     surroundings — the signature of a resampling/upscale splice (an
     element pasted in at a different native resolution than its new
     background). Uses a much smaller kernel than the deficit pass and a
     hard area cap, because a wide kernel can't distinguish a genuine
     block-scale artifact from an ordinary sharp subject against a blurred
     background (verified against a real bokeh-style photo, where reusing
     the deficit kernel for both directions false-flagged 68% of the frame).
7. **Noise-residual-variance anomaly detection (bidirectional)** — same
   deficit/excess treatment as #6, applied to the local variance of the
   Wiener-denoise residual instead of Laplacian sharpness:
   - **Deficit**: cleaner than surroundings — inpainted content that's
     texturally sharp (defeating #6's deficit case) but fails to reproduce
     the sensor/JPEG noise floor of the surrounding photograph.
   - **Excess**: noisier than surroundings — a resampling splice's
     block-quantization pattern reading as elevated high-frequency residual.
   Independent of both ELA and sharpness either way.
8. **Cross-channel spatial corroboration** — when two *independently
   computed* channels (ELA, sharpness, noise) flag overlapping regions, that
   agreement is scored as materially stronger evidence than either channel's
   own ratio-above-threshold alone (a flat bonus, rather than the previous
   plain `max()` across channels, which silently discarded agreement).
   Verified against a real partial/failed generative-erase edit where ELA
   and noise-deficit each fired weakly at the same spot — the bonus moved
   the verdict from "no strong evidence" to "possibly tampered."
9. **MRZ checksum validation** (`backend/app/mrz.py`) — for ID-style
   documents with a TD1 machine-readable zone (3 lines × 30 chars): OCRs the
   MRZ band and recomputes its embedded ICAO 9303 check digits. This is the
   only channel that isn't pixel analysis — it catches naive text edits
   (e.g. changing a printed field without recomputing the checksum encoded
   elsewhere in the same MRZ) that are structurally invisible to every
   pixel-based channel above. Requires the Tesseract OCR binary to be
   installed and on `PATH` (see below) — degrades gracefully with a warning
   if unavailable. Scoped to fields the MRZ actually encodes (document
   number, birth date, sex, expiry date, nationality, name) — a free-text
   field elsewhere on the same document (e.g. a "Registration No." box) is
   out of scope by design; see Known limitations.

### AI Interpreter (`backend/app/interpreter.py`)

A rule-based "mock RAG" layer: a local knowledge base of forensic ELA
heuristics is *retrieved* against the computed features (EXIF software match,
per-region contrast ratio vs. the image-wide average, absence of any
flagged region), then *generated* into a templated natural-language report —
including the YUV-space caveat that high-contrast color boundaries can
produce elevated ELA values without any tampering.

## Multi-agent development workflow

Several of the changes above weren't designed solo — before implementing a
nontrivial pipeline change, this project routes the proposed approach
through specialized reviewer agents first, and only implements after (or
while incorporating) their pushback. Two roles recur:

- **Classical image-forensics reviewer** — a persona briefed on the exact
  pipeline code and a specific proposed change, asked to critique it from a
  signal-processing/forensics standpoint: is the technique sound at the
  image sizes actually in play, what's the false-positive mode, is there a
  simpler/more reliable classical alternative.
- **Deep-learning/CV reviewer** — the same briefing, but asked whether a
  pretrained model would do better, what its training-data blind spots
  are, and whether model integration is worth the effort versus a classical
  fix.

Both are run **in parallel, independently** (neither sees the other's
answer), specifically so their agreement or disagreement is informative
rather than one reviewer anchoring on the other. Concretely, this caught:

- **Rejecting single-image PRNU outright** — both reviewers independently
  identified that a no-reference, single-frame PRNU check isn't sound
  forensics (real PRNU needs a multi-image camera fingerprint to cancel
  scene content), before any code was written.
- **The bidirectional-detection blind spot** — the classical reviewer
  traced it to a specific inconsistency already in the codebase (the ELA
  channel already combined tophat+blackhat "regardless of polarity"; the
  newer sharpness/noise channels didn't), pinpointing the fix before
  implementation.
- **Deprioritizing a pretrained model (PSCC-Net) in favor of two classical
  fixes** — the DL reviewer argued against its own earlier recommendation
  once two concrete real-world failures came in, on the grounds that both
  were architecture bugs (wrong-polarity detectors, no cross-channel
  corroboration) rather than missing model capability, and that forgery
  localization training sets don't clearly cover either failure mode either.
- **The bokeh false-positive** — *not* caught by review (both reviewers
  signed off on the bidirectional-detection design); caught by testing the
  implementation against a real photo afterward, which is why every change
  in this project is verified against saved real test images before being
  called done, not just against the reviewers' sign-off.

A third role — a **research agent** — was used earlier and separately, to
survey current open-source forgery-localization models (TruFor, CAT-Net,
PSCC-Net, IML-ViT, MantraNet), classical diffusion-artifact techniques
(PRNU, FFT/radial-spectrum), and C2PA tooling maturity, feeding the options
the two reviewer roles above then argued over.

The pattern in short: **propose → two independent adversarial reviews →
implement → test against real saved images → report both what worked and
what didn't**, rather than treating a reviewed design as validated until a
real image proves it. Several sections above (bidirectional detection,
cross-channel corroboration, the resampling-artifact limitation) are
written the way they are because that last step caught something the
review step didn't.

### Known limitations (surfaced to the user as warnings)

- Very low ELA max-diff (heavily/repeatedly resaved images) can wash out
  tampering evidence.
- Dark/underexposed images reduce ELA and luminosity reliability.
- ELA cannot reliably catch single-pixel or very minor color edits.
- **A flattened single-generation image defeats ELA structurally**, not
  just weakly: if the original content and the edit were merged into one
  export with no prior differential compression history, there's no
  mismatch left for ELA to diff against. Confirmed on a real ID-card edit
  (a free-text field changed and re-exported as one PNG) where ELA, both
  sharpness directions, and both noise directions all measured within
  normal range at the true edit location — not borderline, genuinely
  invisible to every pixel channel.
- **MRZ validation is scoped to what the MRZ actually encodes.** A
  document's free-text fields outside the MRZ (e.g. a "Registration No."
  or "Remarks" box) are checksum-invisible by design — an edit confined to
  those fields will not be caught by MRZ validation even though the
  document has one. Confirmed on the same real ID-card case above.
- **The bidirectional excess (resampling-artifact) channels are a genuine,
  currently-unsolved risk area.** A generic "busier than its local
  surroundings" measure cannot reliably distinguish a resampling/upscale
  splice's block pattern from ordinary photographic texture (grass,
  foliage, gravel) — confirmed on a real copy-paste/resampling test image,
  where the true artifact fired correctly in the raw signal but got merged
  by contour dilation into one large, mostly-legitimate-texture blob and
  rejected by the area cap, while an unrelated seam artifact scored instead.
  A proper fix needs a periodicity-specific detector (e.g. an FFT or
  Popescu–Farid-style interpolation-artifact check), not further tuning of
  the tophat/blackhat approach — see Next steps.

## Running locally

### 1. Backend (FastAPI)

```bash
cd backend
python -m venv .venv          # or reuse an existing venv
.venv/Scripts/activate         # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API listens on `http://127.0.0.1:8000`. Generated result images are
served from `/results/<job_id>/...`.

**Optional — MRZ checksum validation** requires the Tesseract OCR binary
(not just the `pytesseract` Python wrapper, which `pip install` already
covers) on `PATH`:
- Windows: install from the [UB-Mannheim Tesseract build](https://github.com/UB-Mannheim/tesseract/wiki) and add its install directory to `PATH`.
- macOS: `brew install tesseract`
- Linux: `apt install tesseract-ocr` (or your distro's equivalent)

Without it, MRZ validation is skipped with a warning in the report — every
other channel still runs normally.

### 2. Frontend (React + Vite + Tailwind)

```bash
cd my-web-app
npm install
npm run dev
```

Open `http://localhost:5173`. The dev server proxies `/api` and `/results`
to `http://127.0.0.1:8000` (see `vite.config.js`), so no CORS configuration
is needed beyond what's already set in `backend/app/main.py`.

### 3. Use it

Drop a JPEG or PNG onto the dashboard. You'll get:

- **Tamper score** (0–100), a verdict badge, and a circular-progress score
  indicator.
- **Three-pane view**: original, ELA, and the Tophat/Bothat morphological
  reconstruction, with flagged regions boxed by channel (red = ELA, orange =
  sharpness anomaly, magenta = noise anomaly) and a shared legend.
- **AI localization report**: plain-English explanations per flagged region,
  including which direction (deficit/excess) each sharpness or noise anomaly
  ran, and a note when two channels corroborate each other's finding.
- **MRZ checksum panel**: per-field pass/fail table for ID-style documents,
  shown only when a TD1 MRZ was found and OCR'd.
- **EXIF & signal stats**: software traces, ELA max diff, luminosity std dev.

## Next steps (beyond this POC)

Per the most recent multi-agent review round, priority order is:

1. **A periodicity-specific resampling detector** (FFT/radial-spectrum or
   Popescu–Farid-style interpolation-artifact check) as a proper fourth
   channel — the bidirectional tophat/blackhat approach in #6/#7 above
   isn't the right tool for this and shouldn't be tuned further toward it;
   see Known limitations.
2. **Document-layout-aware field checks** for ID-style documents, to cover
   free-text fields outside the MRZ (e.g. cross-referencing a
   "Registration No." against another encoded field, where one exists) —
   necessarily specific per document layout, not a general pixel technique.
3. A pretrained forgery-localization model (PSCC-Net was the leading
   candidate) is **deliberately deprioritized** below both of the above —
   see Multi-agent development workflow for why.

Longer-term, this local pipeline is intentionally the foundation for a
future AWS serverless deployment (e.g. API Gateway → Lambda/Fargate for the
pipeline, S3 for image storage, and a real vector-store-backed RAG layer in
place of the current rule-based interpreter).
