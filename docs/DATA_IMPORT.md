# Local CancerVerse import

No dataset is downloaded by this package. Download only an authorized, manageable subset using the publisher's instructions. Keep it outside this public repository or under ignored `data/`.

The adapter uses the published directory layout and 13 annotation stems. It does **not** assume unverified CSV column names or equate a `CV_########` case with a patient. Patient grouping and relative dates are supplied through a reviewed manifest. The CSV inspector prints column names and row count, not report text or patient values.

```bash
python -m cancerlab cancerverse-inspect --root /path/to/CancerVerse
python -m cancerlab import-schema > /tmp/cancerverse-import.schema.json
```

Create a private manifest. This example is a format illustration, not a claim about any real case or patient:

```json
{
  "schema_version": "numi.cancer.cancerverse-import.v1",
  "source_revision": "REPLACE_WITH_PINNED_DATASET_REVISION",
  "patients": [{
    "patient_id": "LOCAL-P001",
    "studies": [{
      "case_id": "CV_00000001",
      "acquired_day": 0,
      "available_day": 5,
      "coverage": ["liver"],
      "annotation_scope": "partial",
      "masks": [{
        "organ": "liver",
        "reviews": [{
          "component": 1,
          "lesion_id": "L1",
          "reviewer_id": "curator-1",
          "available_day": 7
        }]
      }]
    }]
  }]
}
```

Use the same reviewed lesion ID at subsequent examination dates only when correspondence is actually established. Omit `reviews` to inspect scan-local components; they will remain unverified and the forecast engine will abstain. Component numbering uses deterministic 26-connected labeling, not biological lesion identity. Adjacent tumors can merge into one component, and one tumor can fragment; review the original mask before assigning a track.

`available_day` must reflect when the annotation/report/review was available, not automatically the scan date. A late correspondence review delays the whole imported study's availability conservatively. Retrospective expert masks and later-informed correspondence do not establish prospective early-detection performance. No absence of a prior lesion is inferred from an empty or missing file.

Coverage and completeness are explicit curator assertions. Use `unknown` or `partial` unless completeness is independently established. A complete multi-organ examination requires an explicit mask for every covered organ. Non-binary labels, undeclared units, undefined orientation, and mismatched CT/mask grids are refused rather than silently repaired.

```bash
python -m cancerlab cancerverse-import \
  --root /path/to/CancerVerse \
  --manifest private/reviewed-manifest.json \
  --out data/cancerverse-patients \
  --receipt var/cancerverse-import-receipt.json \
  --acknowledge-license
python -m cancerlab audit --patients data/cancerverse-patients
python -m cancerlab serve --patients data/cancerverse-patients --scan-root /path/to/CancerVerse
```

Output and receipt destinations must be new. The receipt preserves source hashes, connected-component measurements, and reviewer assignments. Each scan's RAS coordinates are retained, but scans are not registered to each other. The UI can inspect local source CT slices and measured masks when --scan-root is configured. It does not reconstruct registered anatomy or predict tumor boundaries.

Exact duplicate CT file bytes block import; cohort audit also checks repeated recorded scan hashes. Different file hashes do not establish different patients, and re-encoded copies are not detected. Alias resolution and patient-disjoint train/validation/test assignment remain necessary before trained-model studies.

The `--acknowledge-license` flag records deliberate use, not legal permission. CancerVerse is separately licensed CC BY-NC-ND 4.0, with commercial terms handled by BodyMaps. Neither the flag nor this repository grants additional rights.

References: https://huggingface.co/datasets/BodyMaps/CancerVerse and https://www.thebodymaps.com/releases/
