"""Local CancerVerse adapter. No downloads, CSV column guessing, or automatic tracking.

Source layout: https://huggingface.co/datasets/BodyMaps/CancerVerse
A reviewed manifest supplies patient grouping, dates, coverage and correspondence.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .imaging import file_sha256, load_nifti, measure_nifti
from .models import Day, Evidence, Identifier, Lesion, Organ, Patient, Record, Study, digest

MASK_NAMES = {"liver": "liver_lesion", "pancreas": "pancreatic_lesion", "kidney": "kidney_lesion",
              "stomach": "stomach_lesion", "adrenal_gland": "adrenal_gland_lesion",
              "colon": "colon_lesion", "bladder": "bladder_lesion", "prostate": "prostate_lesion",
              "esophagus": "esophagus_lesion", "spleen": "spleen_lesion", "uterus": "uterus_lesion",
              "duodenum": "duodenum_lesion", "gallbladder": "gallbladder_lesion"}


class TrackReview(Record):
    component: Annotated[int, Field(strict=True, ge=1)]
    lesion_id: Identifier
    reviewer_id: Identifier
    available_day: Day


class MaskSelection(Record):
    organ: Organ
    reviews: tuple[TrackReview, ...] = ()

    @model_validator(mode="after")
    def unique_components(self):
        if len({r.component for r in self.reviews}) != len(self.reviews):
            raise ValueError("A component cannot have multiple track assignments")
        return self


class ImportStudy(Record):
    case_id: Annotated[str, Field(pattern=r"^CV_[0-9]{8}$")]
    acquired_day: Day
    available_day: Day
    coverage: tuple[Organ, ...]
    annotation_scope: Literal["complete", "partial", "unknown"] = "unknown"
    masks: tuple[MaskSelection, ...]

    @model_validator(mode="after")
    def consistent(self):
        if self.available_day < self.acquired_day:
            raise ValueError("Annotation availability cannot precede acquisition")
        if len({m.organ for m in self.masks}) != len(self.masks):
            raise ValueError("Duplicate organ masks")
        if not set(m.organ for m in self.masks).issubset(self.coverage):
            raise ValueError("Selected annotation must lie within declared coverage")
        if self.annotation_scope == "complete" and set(self.coverage) != {m.organ for m in self.masks}:
            raise ValueError("Complete annotation requires an explicit mask for every covered organ")
        for mask in self.masks:
            if any(r.available_day < self.acquired_day for r in mask.reviews):
                raise ValueError("Track review cannot precede scan acquisition")
        return self


class ImportPatient(Record):
    patient_id: Identifier
    studies: tuple[ImportStudy, ...] = Field(min_length=1)


class ImportManifest(Record):
    schema_version: Literal["numi.cancer.cancerverse-import.v1"] = "numi.cancer.cancerverse-import.v1"
    source_revision: str = Field(min_length=1, max_length=200)
    patients: tuple[ImportPatient, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self):
        if len({p.patient_id for p in self.patients}) != len(self.patients):
            raise ValueError("Duplicate patient identifiers in manifest")
        cases = [s.case_id for p in self.patients for s in p.studies]
        if len(cases) != len(set(cases)):
            raise ValueError("A CancerVerse case cannot appear twice in an import")
        return self


def inside(root: Path, *parts: str) -> Path:
    root = root.resolve(strict=True)
    result = root.joinpath(*parts).resolve(strict=True)
    if not result.is_relative_to(root) or not result.is_file():
        raise ValueError("Source must be a regular file inside the selected dataset root")
    return result


def inspect(root: Path) -> dict:
    """Inspect actual metadata headers, not patient values. Never infer a patient key."""
    path = inside(root, "CancerVerse_dataset_metadata.csv")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        columns = next(reader, [])
        rows = sum(1 for _ in reader)
    return {"metadata_columns": columns, "row_count": rows, "metadata_sha256": file_sha256(path),
            "case_root_present": (root / "CancerVerse").is_dir(),
            "requires_reviewed_manifest": True,
            "notice": "Group by verified patient identity, not CV case number; audit aliases and duplicate scans"}


def import_records(root: Path, manifest: ImportManifest, *, acknowledge_license: bool = False) -> tuple[dict[str, Patient], dict]:
    if not acknowledge_license:
        raise ValueError("Review CancerVerse CC BY-NC-ND 4.0 terms and acknowledge the separate dataset license")
    patients, receipt = {}, {"manifest_sha256": digest(manifest), "source_revision": manifest.source_revision,
                              "license": "CC-BY-NC-ND-4.0", "studies": [], "warnings": []}
    seen_scans = {}
    for p in manifest.patients:
        studies = []
        for s in sorted(p.studies, key=lambda s: s.acquired_day):
            ct_path = inside(root, "CancerVerse", s.case_id, "ct.nii.gz")
            ct = load_nifti(ct_path)
            scan_hash = file_sha256(ct_path)
            if scan_hash in seen_scans:
                raise ValueError("Exact duplicate CT bytes found; review duplicate/alias records before import")
            seen_scans[scan_hash] = p.patient_id
            lesions, records, available_day = [], [], s.available_day
            for selected in s.masks:
                relative = f"CancerVerse/{s.case_id}/segmentations/{MASK_NAMES[selected.organ]}.nii.gz"
                mask_path = inside(root, relative)
                mask_hash = file_sha256(mask_path)
                measured = measure_nifti(mask_path, ct)
                reviews = {r.component: r for r in selected.reviews}
                if set(reviews) - {m["component"] for m in measured}:
                    raise ValueError("Reviewed component number does not exist in the selected mask")
                for measurement in measured:
                    number = measurement["component"]
                    review = reviews.get(number)
                    # Scan-local IDs intentionally cannot masquerade as longitudinal tracks.
                    track = review.lesion_id if review else f"{s.case_id}.{selected.organ}.c{number}"
                    available_day = max(available_day, review.available_day if review else available_day)
                    lesions.append(Lesion(lesion_id=track, organ=selected.organ,
                                          volume_ml=measurement["volume_ml"],
                                          centroid_ras_mm=measurement["centroid_ras_mm"],
                                          correspondence="confirmed" if review else "unverified",
                                          evidence=Evidence(source=f"{relative}#component={number}",
                                                            method="mask-volume", sha256=mask_hash)))
                records.append({"organ": selected.organ, "mask_sha256": mask_hash, "components": measured,
                                "reviews": [r.model_dump(mode="json") for r in selected.reviews]})
            studies.append(Study(study_id=s.case_id, acquired_day=s.acquired_day, available_day=available_day,
                                 coverage=s.coverage, annotation_scope=s.annotation_scope,
                                 lesions=tuple(lesions), scan_sha256=scan_hash))
            receipt["studies"].append({"patient_id": p.patient_id, "case_id": s.case_id,
                                       "scan_sha256": scan_hash, "masks": records})
        patients[p.patient_id] = Patient(patient_id=p.patient_id, source="CancerVerse",
                                         source_revision=manifest.source_revision, synthetic=False,
                                         studies=tuple(studies))
    receipt["warnings"] = ["No automatic lesion correspondence or clinical-event extraction",
                            "No registration across examinations; each centroid is in its own scan RAS frame",
                            "Exact-file duplicate checking does not resolve patient aliases or re-encoded scans",
                            "Complete coverage/annotation flags are curator assertions, not inferred guarantees"]
    receipt["receipt_sha256"] = digest(receipt)
    return patients, receipt


def write_import(patients: dict[str, Patient], receipt: dict, out: Path, receipt_path: Path) -> None:
    """Write only to new local destinations; never overwrite existing records."""
    if out.exists() or receipt_path.exists():
        raise ValueError("Import destination or receipt already exists; no records overwritten")
    if receipt_path.resolve().is_relative_to(out.resolve()):
        raise ValueError("Keep the import receipt outside the canonical patient directory")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True)
    for p in patients.values():
        (out / f"{p.patient_id}.json").write_text(p.model_dump_json(indent=2))
    receipt_path.write_text(json.dumps(receipt, indent=2, allow_nan=False))
