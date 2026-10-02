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

## Implemented

- Immutable, versioned patient records with separate acquisition and evidence-availability dates.
- Explicit organ coverage, annotation completeness, unknown observations, and reviewed versus unverified lesion correspondence.
- Interactive lesion-volume geometry, patient/date selection, trajectory plots, evidence inspection, and desktop/mobile layouts. Spheres represent volume, **not reconstructed tumor anatomy**. WebGL2 has a CPU-projection fallback.
- No-change, linear-growth, and exponential-growth baselines. These do not model treatment effects, new lesions, or calibrated uncertainty.
- Cutoff-only model input; later scans and reports are excluded before forecasting. This is application-level isolation, not a secure clinical trial data enclave.
- Append-only SQLite experiments with input, code, and artifact hashes; follow-up evaluation is recorded separately.
- Explicit missing-target errors, new-lesion-aware organ-total scoring, unscorable cases, and patient-level benchmark denominators.
- Loopback-only CLI server, host and cross-origin write checks, no external assets or telemetry, and no upload endpoints.
- CLI, JSON Schema, local experiment export, Python regression tests, and a browser smoke test.

## Research and data boundaries

Do not commit patient scans, clinical reports, identifiers, experiment outputs, or credentials. Keep local records under `data/`, and experiments under `var/`; both are ignored by Git. The service has no user authentication or tenant isolation: do not expose it publicly or use it as a patient portal.

CancerVerse is a separate dataset licensed under CC BY-NC-ND 4.0. No CancerVerse scans, reports, or annotations are redistributed here. Review the publisher's terms, including commercial-use restrictions, before using real records.

Measured observations, numerical forecasts, and future biological simulations are distinct. Software tests are not evidence of medical effectiveness. Patient-level registration, trained detection/forecast models, biological treatment models, and native Numi-suite consumers are not implemented in this milestone.

## Primary references

- Dataset, release layout, and annotation filenames: https://huggingface.co/datasets/BodyMaps/CancerVerse
- Release and licensing information: https://www.thebodymaps.com/releases/
- NIfTI coordinates and units: https://nipy.org/nibabel/nifti_images.html

No software redistribution license has been selected yet. The repository owner must choose one; this does not change any external dataset license.
