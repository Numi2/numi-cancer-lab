"""Geometry-based suggestions and explicit one-to-one review, reusing the importer."""
from __future__ import annotations

import re
from typing import Annotated

import numpy as np
from pydantic import Field, model_validator
from scipy.spatial import cKDTree

from .cancerverse import ImportManifest, MASK_NAMES, TrackReview
from .models import Day, Identifier, Patient, Record, digest
from .registration import Distance, source_studies, transform_points, verify_registration

MAX_POINTS = 4096
MAX_EDGES = 20000


class MatchOptions(Record):
    max_distance_mm: Distance = 20
    ambiguity_margin_mm: Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)] = 3


class MatchDecision(Record):
    fixed_lesion_id: Identifier
    moving_lesion_id: Identifier
    reason: str = Field(min_length=1, max_length=2000)


class CorrespondenceReview(Record):
    proposal_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer_id: Identifier
    available_day: Day
    links: tuple[MatchDecision, ...] = Field(min_length=1, max_length=MAX_POINTS)

    @model_validator(mode="after")
    def one_to_one(self):
        for field in ("fixed_lesion_id", "moving_lesion_id"):
            if len({getattr(link, field) for link in self.links}) != len(self.links):
                raise ValueError("Review must be one-to-one; split/merge cases need separate annotation review")
        return self


def _eligible(study, organ):
    valid, excluded = [], []
    for lesion in sorted(study.lesions, key=lambda m: m.lesion_id):
        if lesion.organ != organ:
            continue
        if lesion.state != "present":
            excluded.append({"lesion_id": lesion.lesion_id, "reason": "Not a measured present lesion"})
        elif lesion.centroid_ras_mm is None:
            excluded.append({"lesion_id": lesion.lesion_id, "reason": "No measured centroid"})
        else:
            valid.append(lesion)
    if len(valid) > MAX_POINTS:
        raise ValueError("Too many components for a bounded matching review")
    return valid, excluded


def propose_matches(patient: Patient, registration: dict, options: MatchOptions | None = None) -> dict:
    options = options or MatchOptions()
    request = verify_registration(patient, registration)
    fixed, moving = source_studies(patient, request)
    f, excluded_f = _eligible(fixed, request.organ)
    m, excluded_m = _eligible(moving, request.organ)
    edges = []
    if f and m:
        fixed_points = np.array([lesion.centroid_ras_mm for lesion in f])
        moved_points = transform_points([lesion.centroid_ras_mm for lesion in m], registration["matrix"])
        ftree, mtree = cKDTree(fixed_points), cKDTree(moved_points)
        # Second neighbours include points outside the search radius. A boundary
        # must not make an otherwise ambiguous nearest neighbour appear unique.
        fd, fi = mtree.query(fixed_points, k=2)
        md, mi = ftree.query(moved_points, k=2)
        for i, point in enumerate(fixed_points):
            nearby = sorted(mtree.query_ball_point(point, options.max_distance_mm))
            if len(edges) + len(nearby) > MAX_EDGES:
                raise ValueError("Too many candidate edges; reduce the review region or search radius")
            for j in nearby:
                separated = (fi[i, 0] == j and mi[j, 0] == i
                             and fd[i, 1] - fd[i, 0] > max(options.ambiguity_margin_mm, 1e-8)
                             and md[j, 1] - md[j, 0] > max(options.ambiguity_margin_mm, 1e-8))
                edges.append({"fixed_lesion_id": f[i].lesion_id, "moving_lesion_id": m[j].lesion_id,
                              "distance_mm": float(np.linalg.norm(point - moved_points[j])),
                              "fixed_volume_ml": f[i].volume_ml, "moving_volume_ml": m[j].volume_ml,
                              "moving_in_fixed_ras_mm": moved_points[j].tolist(),
                              "status": "separated_candidate" if separated else "ambiguous_candidate"})
    matched_f = {edge["fixed_lesion_id"] for edge in edges}
    matched_m = {edge["moving_lesion_id"] for edge in edges}
    body = {"schema_version": "numi.cancer.correspondence-proposal.v1", "patient_id": patient.patient_id,
            "available_day": request.available_day, "registration": registration,
            "options": options.model_dump(mode="json"), "candidates": edges,
            "unmatched_fixed": [p.lesion_id for p in f if p.lesion_id not in matched_f],
            "unmatched_moving": [p.lesion_id for p in m if p.lesion_id not in matched_m],
            "excluded_fixed": excluded_f, "excluded_moving": excluded_m,
            "limitations": ["All matches are suggestions, including separated candidates",
                            "Distances and margins are not probabilities or clinical thresholds",
                            "No match does not establish disappearance or a new cancer lesion",
                            "No automatic split, merge or persistent-identity assignment",
                            "Volumes remain measured on each original scan, not the registered grid"]}
    return {**body, "artifact_sha256": digest(body)}


def _component(lesion, study_id, organ):
    prefix = f"CancerVerse/{study_id}/segmentations/{MASK_NAMES[organ]}.nii.gz#component="
    match = re.fullmatch(re.escape(prefix) + r"([1-9][0-9]*)", lesion.evidence.source)
    if lesion.evidence.method != "mask-volume" or match is None:
        raise ValueError("Review requires the original scan-local mask component evidence")
    return int(match.group(1))


def review_manifest(patient: Patient, manifest: ImportManifest, proposal: dict,
                    review: CorrespondenceReview) -> tuple[ImportManifest, dict]:
    """Return a NEW import manifest. Never relabel in-memory observations or files.

    Review affects only selected moving components. The importer delays their
    examination availability to the review date; no earlier label is backdated.
    """
    if digest({k: v for k, v in proposal.items() if k != "artifact_sha256"}) != proposal.get("artifact_sha256"):
        raise ValueError("Proposal integrity check failed")
    if review.proposal_sha256 != proposal.get("artifact_sha256"):
        raise ValueError("Review belongs to a different proposal")
    registration = proposal.get("registration", {})
    request = verify_registration(patient, registration)
    fixed, moving = source_studies(patient, request)
    fresh = propose_matches(patient, registration, MatchOptions.model_validate(proposal.get("options")))
    if fresh["artifact_sha256"] != proposal["artifact_sha256"]:
        raise ValueError("Proposal no longer reproduces; regenerate against current evidence")
    if review.available_day < request.available_day:
        raise ValueError("Review cannot be available before its alignment evidence")
    if manifest.source_revision != patient.source_revision:
        raise ValueError("Manifest source revision differs from the reviewed patient")
    raw = manifest.model_dump(mode="json")
    owner = next((p for p in raw["patients"] if p["patient_id"] == patient.patient_id), None)
    if owner is None:
        raise ValueError("Patient not found in import manifest")
    selections = {}
    for study in (fixed, moving):
        source = next((s for s in owner["studies"] if s["case_id"] == study.study_id), None)
        if source is None or source["acquired_day"] != study.acquired_day or set(source["coverage"]) != set(study.coverage):
            raise ValueError("Manifest examination differs from the reviewed evidence")
        availability = max([source["available_day"]] + [r["available_day"] for mask in source["masks"] for r in mask["reviews"]])
        if availability != study.available_day or source["annotation_scope"] != study.annotation_scope:
            raise ValueError("Manifest availability or annotation scope changed")
        selection = next((m for m in source["masks"] if m["organ"] == request.organ), None)
        if selection is None:
            raise ValueError("Selected mask not found in manifest")
        hashes = {m.evidence.sha256 for m in study.lesions if m.organ == request.organ}
        if len(hashes) != 1 or not study.scan_sha256:
            raise ValueError("A reviewed import requires consistent CT and mask hashes")
        mask_hash = hashes.pop()
        if source["expected_scan_sha256"] not in (None, study.scan_sha256) or selection["expected_mask_sha256"] not in (None, mask_hash):
            raise ValueError("Manifest file binding differs from the reviewed evidence")
        source["expected_scan_sha256"] = study.scan_sha256
        selection["expected_mask_sha256"] = mask_hash
        selections[study.study_id] = selection
    fixed_by_id = {p.lesion_id: p for p in fixed.lesions}
    moving_by_id = {p.lesion_id: p for p in moving.lesions}
    candidates = {(e["fixed_lesion_id"], e["moving_lesion_id"]) for e in fresh["candidates"]}
    target_reviews = selections[moving.study_id]["reviews"]
    for link in review.links:
        if (link.fixed_lesion_id, link.moving_lesion_id) not in candidates:
            raise ValueError("Selected pair is not a candidate in the reviewed proposal")
        first, later = fixed_by_id[link.fixed_lesion_id], moving_by_id[link.moving_lesion_id]
        if first.correspondence != "confirmed":
            raise ValueError("Establish the earlier track identity before linking a later observation")
        fixed_component = _component(first, fixed.study_id, request.organ)
        anchor = next((r for r in selections[fixed.study_id]["reviews"] if r["component"] == fixed_component), None)
        if anchor is None or anchor["lesion_id"] != first.lesion_id:
            raise ValueError("Earlier identity does not agree with the import manifest")
        component = _component(later, moving.study_id, request.organ)
        if later.correspondence == "confirmed" or any(r["component"] == component for r in target_reviews):
            raise ValueError("Moving component already reviewed; existing decisions are not overwritten")
        if any(r["lesion_id"] == first.lesion_id for mask in next(
                s for s in owner["studies"] if s["case_id"] == moving.study_id)["masks"] for r in mask["reviews"]):
            raise ValueError("Identity already assigned to another moving component")
        target_reviews.append(TrackReview(component=component, lesion_id=first.lesion_id,
                                          reviewer_id=review.reviewer_id, available_day=review.available_day).model_dump(mode="json"))
    updated = ImportManifest.model_validate(raw)
    body = {"schema_version": "numi.cancer.correspondence-review.v1", "patient_id": patient.patient_id,
            "registration_sha256": registration["artifact_sha256"], "review": review.model_dump(mode="json"),
            "input_manifest_sha256": digest(manifest), "output_manifest_sha256": digest(updated),
            "notice": "Human identity assertions, not automatic validation. Re-import into a new local directory."}
    return updated, {**body, "artifact_sha256": digest(body)}
