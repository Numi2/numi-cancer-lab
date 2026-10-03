# Reviewed registration and lesion correspondence

This local workflow aligns two observations, proposes candidate correspondences,
and records an explicit review in the existing CancerVerse import manifest.
It does not change source patient records, forecast inputs, scan pixels or lesion
identities automatically. There is no additional database or hosted service.

## Try the synthetic workflow

```bash
python scripts/tracking_demo.py --out var/tracking-demo
```

This generates an explicitly synthetic patient with known 100 mm scanner-frame
translation. The real registration, matching and review commands run in sequence.
It produces one candidate and one unmatched observation, then a simulated review
of the known correspondence. No NIfTI files, real patient data or network access
are used. Output paths must be new; reruns never overwrite evidence.

## Align observations

Obtain paired anatomical landmarks from reviewed images of the same patient and
organ. Fixed is the earlier examination; moving is the later examination.
Supply at least three non-collinear landmark pairs. Independent check landmarks
are optional and are not used to fit the transform. Without them, the artifact
explicitly says that only the fitting error was measured.

```bash
python -m cancerlab registration-schema
python -m cancerlab register --patient data/patients/P001.json \
  --request var/landmarks.json --out var/registration.json
```

The request has `patient_id`, `fixed_study_id`, `moving_study_id`, `organ`,
`reviewer_id`, `available_day`, a required `max_error_mm`, `landmarks`, and
optional `check_landmarks`. Each point has `landmark_id`, `fixed_ras_mm` and
`moving_ras_mm`. Coordinates are RAS+ millimetres, not voxel indices or DICOM LPS.
The generated synthetic `request.json` is an executable format example.

The Kabsch least-squares fit estimates rotation and translation, without scaling,
shear or reflection. Its direction is explicitly **moving RAS+ to fixed RAS+**.
Near-collinear landmarks, failed fit/check tolerances, missing study coverage,
wrong patient references and backdated evidence are refused. Source study hashes,
landmarks and errors travel with the artifact. Reloading verifies the digest,
source records, transform and diagnostics. Hashes detect changes, not reviewer
identity or authenticity; this remains a trusted local research tool.

A low fitting error is not a calibrated estimate of registration accuracy across
an organ. The declared tolerance is a research setting, not a clinical threshold.
Rigid alignment cannot correct breathing-related or treatment-related deformation.

## Propose and review correspondences

```bash
python -m cancerlab match --patient data/patients/P001.json \
  --registration var/registration.json --max-distance-mm 20 \
  --ambiguity-margin-mm 3 --out var/proposal.json
python -m cancerlab track-review-schema
```

Candidates use measured, present lesions with physical centroids in the selected
organ. Positions are compared after alignment. All within-radius candidates are
retained, subject to explicit resource limits. Mutual nearest candidates with a
sufficient gap are labelled `separated_candidate`; competing candidates are
`ambiguous_candidate`. Neither status confirms identity or represents a probability.
Even a competing point just outside the search radius participates in ambiguity
checking. Original measured volumes are reported without using growth to exclude
a candidate. Missing centroids and unassessed observations have explicit reasons.
Unmatched observations are not labelled new disease, disappearance or cure.

A reviewer supplies `proposal_sha256`, `reviewer_id`, `available_day`, and `links`.
Each link has `fixed_lesion_id`, `moving_lesion_id`, and a written `reason`.
The earlier identity must already have been reviewed in the original import
manifest. Ambiguous pairs can be explicitly accepted after review, but no pair
is accepted merely because it was geometrically closest.

```bash
python -m cancerlab review-tracks --patient data/patients/P001.json \
  --manifest var/import-manifest.json --proposal var/proposal.json \
  --review var/review.json --out var/reviewed
python -m cancerlab cancerverse-import --root /path/to/local/CancerVerse \
  --manifest var/reviewed/manifest.json --out data/patients-reviewed \
  --receipt var/reimport-receipt.json --acknowledge-license
```

The result is a **new** manifest and review receipt, not a modified patient file.
Only selected later components acquire the earlier track ID. Duplicate links,
split/merge assignments, conflicting existing identities and backdated reviews
are refused. Unselected components remain unverified. Reviewed CT and mask hashes
are bound into the manifest; changed bytes cause re-import to fail. The review
receipt connects the decisions to the proposal, registration and both manifests.

Retain the original patient directory for existing sealed experiments. Import
reviews into a fresh directory and create new experiments for the revised inputs.
The current importer conservatively delays the entire affected examination to
its latest review availability date. It does not retain multiple as-of identity
versions inside one examination, and does not claim that a later review was known
earlier. Research `available_day` values are curator assertions, not authenticated
wall-clock timestamps.

## Regional mask comparison

The library function `registration.compare_registered_masks` compares binary masks
under a reviewed rigid transform. It uses nearest-neighbour resampling and reports
Dice only on shared sampled support, each original mask's visible fraction, and
physical volumes computed on the original grids. No shared support is an error;
two empty shared masks produce an undefined Dice value, not perfect agreement.

The pull sampling matrix is
`inv(moving_affine) @ inv(moving_to_fixed) @ fixed_affine`.
Keep correct voxel-to-RAS affines when preparing cropped regions. The default
limit is eight million voxels per mask. Comparison is a library API in this
increment; it is not a new button in the CT viewer and does not automatically
select or load patient mask files.

## Verification and limits

`python scripts/check_local.py` runs local tests, synthetic baseline benchmarks,
and the synthetic registration/review workflow. `--browser` additionally runs the
existing offline UI/API check. No hosted jobs are installed or dispatched.

Tests cover known transforms, independent checks, geometry degeneracy, ambiguity,
review provenance, unchanged source records, availability cutoffs, changed file
bindings, and mask overlap with translated, rotated and cropped grids. Synthetic
and mocked-file tests are software checks, not real-patient registration evidence.
NIfTI integration tests require the optional NiBabel installation.

References: [NiBabel coordinate conventions](https://nipy.org/nibabel/coordinate_systems.html),
[SciPy's documented Kabsch alignment](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.transform.Rotation.align_vectors.html).
