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

This project is developed with a fixed roster of six specialized agents
(`.claude/agents/*.md`), each scoped to one concern, with explicit
boundaries about what it hands off to another agent rather than doing
itself. All six share the same project-context brief (pipeline stages,
file layout, run commands) plus their own domain-specific "hard-won
lessons" section, so a fresh invocation doesn't re-litigate settled
calibration decisions from first principles.

### The six agents

| Agent | Model | Tools | Role |
|---|---|---|---|
| `planner` | opus | read-only + web | Turns a feature/refactor/migration request into an ordered, file-specific implementation plan. Never edits code. |
| `feature-builder` | sonnet | read/write/edit | Implements a given plan or direct request — endpoints, pipeline stages, UI components. Writes code; doesn't do open-ended design. |
| `bug-fixer` | sonnet | read/edit + bash | Takes a reported symptom (wrong score, API error, UI glitch), root-causes it, and applies the minimal fix. Not for new features. |
| `tester` | sonnet | read + bash + write (scripts only) | Writes and runs verification scripts, reports pass/fail with actual numbers. Never fixes what it finds — hands findings to `bug-fixer`. |
| `cv-expert` | opus | read-only + web | Deep classical image-processing/OpenCV authority — ELA, morphology, frequency-domain methods, denoising, algorithm selection for a given tampering signature. Defers model/training questions to `ml-expert`. |
| `ml-expert` | opus | read-only + web | Deep neural-network/pretrained-model authority — which architecture fits which forensic task (ManTraNet, PSCC-Net, CAT-Net, Noiseprint, diffusion-detector CNNs), integration strategy, dataset/training reality-checks. Defers classical pixel/frequency methods to `cv-expert`. |

`planner`, `bug-fixer`, `tester`, and `feature-builder` all read/write only
(no `WebFetch`/`WebSearch`) — their job is reasoning about *this* codebase.
`cv-expert` and `ml-expert` are read-only over the codebase but have
`WebFetch`/`WebSearch`, because their job is bringing outside domain
knowledge (published techniques, model landscape) to bear on it — neither
can edit `app/` directly; a decision they reach still goes through
`feature-builder` to land in code.

### What each one actually knows (baked into its own file, not re-derived per run)

- **`planner`** carries the project's calibration history as constraints on
  any new plan: ELA must run at native resolution (never downscale pixels —
  only thresholds scale, via `scale_factor = max(image_dims) / REFERENCE_DIMENSION`);
  local-ring comparison, not global-mean; a floored ratio denominator; the
  `--reload` requirement on uvicorn. A plan that would reintroduce any of
  these is something `planner` is briefed to catch before `feature-builder`
  ever sees it.
- **`feature-builder`** carries the same constraints as house rules for
  writing code — no comments beyond non-obvious WHY, no scope creep, verify
  with a synthetic-image sanity check before reporting done, and flag (not
  silently revert) if a request conflicts with existing false-positive
  tuning.
- **`bug-fixer`** carries a numbered history of every tamper-score bug this
  project has already hit and fixed once (global-mean comparison, ratio
  explosion near zero, resolution-dependent thresholds, pixel downscaling,
  bounding-box mean dilution) — so a new bug report gets matched against
  that list before any constant gets changed blindly.
- **`tester`** carries the specific test-methodology mistakes already made
  in this project — hand-drawn hard-edged rectangles fake a false-positive
  signal that isn't the pipeline's fault; numpy smooth-gradient + Gaussian
  blur synthetic images are the real regression fixture, run at both ~500px
  and ~3000px, both untampered and spliced.
- **`cv-expert`** carries the classical-forensics technique catalog this
  project draws on when evaluating a new channel: noise-level analysis,
  CFA/demosaicing artifacts, JPEG double-compression analysis, PRNU,
  copy-move via SIFT/ORB+RANSAC, illumination/shadow-inconsistency
  detection — plus the explicit acknowledgment that ELA + Tophat/Bothat is
  structurally edge-sensitive, not tamper-specific, and that's a known
  limitation, not a bug to keep chasing.
- **`ml-expert`** carries the actual published model landscape by name —
  ManTraNet, PSCC-Net, CAT-Net/RGB-N, MVSS-Net, Noiseprint/Noiseprint++,
  diffusion/GAN-fingerprint CNN detectors — and the practical constraints
  that matter for this project specifically: no labeled dataset exists
  in-repo, no GPU infrastructure, so pretrained/zero-shot is the only
  realistic near-term option.

### How this played out on real changes

Before implementing a nontrivial pipeline change, the proposed approach is
routed through `cv-expert` and `ml-expert` **in parallel, independently**
(neither sees the other's answer), specifically so agreement or
disagreement between them is informative rather than one anchoring on the
other. Concretely, this caught:

- **Rejecting single-image PRNU outright** — both agents independently
  identified that a no-reference, single-frame PRNU check isn't sound
  forensics (real PRNU needs a multi-image camera fingerprint to cancel
  scene content), before any code was written.
- **The bidirectional-detection blind spot** — `cv-expert` traced it to a
  specific inconsistency already in the codebase (the ELA channel already
  combined tophat+blackhat "regardless of polarity"; the newer
  sharpness/noise channels didn't), pinpointing the fix before
  implementation.
- **Deprioritizing a pretrained model (PSCC-Net) in favor of two classical
  fixes** — `ml-expert` argued against its own earlier recommendation once
  two concrete real-world failures came in, on the grounds that both were
  architecture bugs (wrong-polarity detectors, no cross-channel
  corroboration) rather than missing model capability, and that forgery
  localization training sets don't clearly cover either failure mode either.
- **The bokeh false-positive** — *not* caught by review (both agents signed
  off on the bidirectional-detection design); caught by testing the
  implementation against a real photo afterward. This is exactly the gap
  `tester`'s role exists to close, and why no change in this project is
  called done on review sign-off alone.

The pattern in short: **`planner`/direct request → `cv-expert` + `ml-expert`
independent review → `feature-builder` implements → `tester`-style
verification against real saved images → `bug-fixer` if something's still
wrong**. Several sections above (bidirectional detection, cross-channel
corroboration, the resampling-artifact limitation) are written the way they
are because the verification step caught something the review step didn't.

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
