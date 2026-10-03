# Numi Cancer Lab

Local, patient-specific longitudinal cancer research for the Numi suite.

**Working milestone:** inspect dated observations, seal a cutoff-safe forecast, reveal a later examination, and compare the result against three explicit numerical baselines. The included cases are entirely synthetic; this is not a validated cancer AI or clinical decision-support system.

## Run

Python 3.11 or later, including Apple Silicon. No CUDA, Node, API key, or cloud account is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,imaging]'
python -m cancerlab serve
```

Open `http://127.0.0.1:8765`. Select a synthetic patient, inspect the two visible observations, seal a forecast, then reveal the day-180 follow-up. The kidney example includes a newly observed lesion: its volume counts toward total-burden error instead of being silently excluded.

```bash
python -m pytest -q
python -m cancerlab demo --out data/demo
python -m cancerlab serve --patients data/demo
python -m cancerlab benchmark --organ liver --out var/benchmark.json
python -m cancerlab schema
python -m playwright install chromium
python scripts/browser_smoke.py --offline
```

## Local-only verification: no hosted CI

GitHub Actions workflows have been removed. Do not restore them or substitute another paid CI service. The owner has prohibited hosted runner spending. Tests remain in the repository and run on the developer's machine:

```bash
python scripts/check_local.py --browser
python scripts/browser_smoke.py --offline --scan-fixture
```

The check command runs Python tests, synthetic liver/kidney baseline evaluations, and the synthetic registration/review workflow, optionally adding browser checks. It neither installs dependencies nor starts remote jobs. Missing imaging dependencies are reported as skipped tests, not passes.

## Local CT and measured-mask viewing

After the reviewed import described in [DATA_IMPORT](docs/DATA_IMPORT.md), run:

```bash
python -m cancerlab serve --patients data/cancerverse-patients --scan-root /path/to/dataset
```

The source-image panel provides axial, coronal and sagittal slices, intensity-window controls, measured mask overlays, orientation markers and physical pixel aspect ratios. It verifies source hashes, reads planes through NIfTI proxies rather than loading complete CT arrays, and keeps only eight image proxies cached. Compressed files may still require decompression work; no latency benchmark is claimed.

Source grids must be cardinal-axis aligned. Oblique/sheared images require explicit resampling and are refused rather than shown with misleading labels. The viewer still displays each examination in its source frame; CLI alignment is described below. Forecast spheres are not drawn as tumor boundaries on CT. Follow-up image access through an experiment requires its recorded reveal; only that target examination is exposed.

The synthetic demo does not include real CT. `--scan-fixture` exercises browser rendering with synthetic voxel arrays, not patient scans or NIfTI disk reads. Real CancerVerse imaging still requires locally authorized data and the optional imaging dependencies.

## Implemented

- Immutable, versioned patient records with separate acquisition and evidence-availability dates.
- Explicit organ coverage, annotation completeness, unknown observations, and reviewed versus unverified lesion correspondence.
- Interactive lesion-volume geometry, patient/date selection, trajectory plots, evidence inspection, and desktop/mobile layouts. Spheres represent volume, **not reconstructed tumor anatomy**. WebGL2 has a CPU-projection fallback.
- No-change, linear-growth, and exponential-growth baselines. These do not model treatment effects, new lesions, or calibrated uncertainty.
- Cutoff-only model input; later scans and reports are excluded before forecasting. This is application-level isolation, not a secure clinical trial data enclave.
- Append-only SQLite experiments with input, code, and artifact hashes; follow-up evaluation is recorded separately.
- Explicit missing-target errors, new-lesion-aware organ-total scoring, unscorable cases, and patient-level benchmark denominators.
- Loopback-only CLI server, host and cross-origin write checks, no external assets or telemetry, and no upload endpoints.
- Local CancerVerse NIfTI import with a reviewed manifest, physical volume/centroid measurement, source hashes, and explicit correspondence review dates. No CSV column guessing or automatic patient grouping.
- Local CT/mask viewer with hash checks, cutoff-aware access, plane-bounded rendering and stale-response protection.
- Exact duplicate scan audit with incomplete-audit reporting; duplicate scans block benchmark execution.
- CLI, JSON Schema, local experiment export, Python regression tests, and a browser smoke test.

See [local data import](docs/DATA_IMPORT.md) for the dataset layout, manifest format, and import commands. Canonical JSON records and experiment exports are the current Numi integration boundary; native consumers are not yet connected.

## Research and data boundaries

Do not commit patient scans, clinical reports, identifiers, experiment outputs, or credentials. Keep local records under `data/`, and experiments under `var/`; both are ignored by Git. The service has no user authentication or tenant isolation: do not expose it publicly or use it as a patient portal.

CancerVerse is a separate dataset licensed under CC BY-NC-ND 4.0. No CancerVerse scans, reports, or annotations are redistributed here. Review the publisher's terms, including commercial-use restrictions, before using real records.

Measured observations, numerical forecasts, and future biological simulations are distinct. Software tests are not evidence of medical effectiveness. Deformable registration, interactive landmark review, trained detection/forecast models, biological treatment models, and native Numi-suite consumers are not implemented in this milestone.

## Primary references

- Dataset, release layout, and annotation filenames: https://huggingface.co/datasets/BodyMaps/CancerVerse
- Release and licensing information: https://www.thebodymaps.com/releases/
- NIfTI coordinates and units: https://nipy.org/nibabel/nifti_images.html

No software redistribution license has been selected yet. The repository owner must choose one; this does not change any external dataset license.


## Real-cohort evaluation

CancerVerse data stays local. After a reviewed import, run a fixed protocol:

```bash
python -m cancerlab audit --patients data/cancerverse
python -m cancerlab benchmark --patients data/cancerverse --cutoff 90 --horizon 90 --organ liver --out var/liver-90d.json
```

The benchmark reports the input/eligible/skipped patient counts, total-burden coverage, pooled lesion MAE, and per-patient sealed artifacts. A lesion is scored only when its longitudinal correspondence is confirmed. Total burden is scored only when the held-out study is declared completely annotated for that organ. These are retrospective research measurements, not clinical performance claims.

Hosted CI is intentionally absent to avoid runner spend. Verification is local with `python scripts/check_local.py --browser`.

## Reviewed scan alignment and matching

Run `python scripts/tracking_demo.py --out var/tracking-demo` for a local,
explicitly synthetic registration -> candidate matching -> reviewed-manifest
workflow. New CLI commands are `register`, `match`, and `review-tracks`.
Suggestions never become persistent identities without an explicit review.
Reviewed manifests bind exact CT/mask hashes and preserve review availability.

See [registration and correspondence](docs/REGISTRATION.md) for formats,
limitations, and regional registered-mask comparison. This increment adds library
and command-line workflows, not an interactive landmark-review screen.


## Workspace experience

The browser workspace now separates Overview, CT viewer, Evidence, Match review,
and Saved experiments. Resume saved work, explicitly confirm a follow-up reveal,
inspect source evidence, and export reviewed correspondence drafts without
changing patient records. On mobile, compact settings and a persistent primary
action keep the workflow accessible. See [the workspace guide](docs/UX.md) for
controls, review semantics, and verification limits.
