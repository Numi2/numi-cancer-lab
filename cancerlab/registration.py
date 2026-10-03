"""Reviewed rigid landmark alignment in RAS+ millimetres; never a lesion identity claim."""
from __future__ import annotations

from typing import Annotated, Literal

import numpy as np
from pydantic import Field, model_validator

from .models import Day, Identifier, Organ, Patient, Record, Study, digest

Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1e6, le=1e6)]
Point = tuple[Coordinate, Coordinate, Coordinate]
Distance = Annotated[float, Field(gt=0, le=1000, allow_inf_nan=False)]
ALGORITHM = "landmark-rigid-kabsch.v1"


class LandmarkPair(Record):
    landmark_id: Identifier
    fixed_ras_mm: Point
    moving_ras_mm: Point


class RegistrationRequest(Record):
    patient_id: Identifier
    fixed_study_id: Identifier
    moving_study_id: Identifier
    organ: Organ
    reviewer_id: Identifier
    available_day: Day
    max_error_mm: Distance
    coordinate_system: Literal["RAS+ mm"] = "RAS+ mm"
    landmarks: tuple[LandmarkPair, ...] = Field(min_length=3, max_length=64)
    check_landmarks: tuple[LandmarkPair, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def unique(self):
        if self.fixed_study_id == self.moving_study_id:
            raise ValueError("Select two distinct examinations")
        points = self.landmarks + self.check_landmarks
        if len({p.landmark_id for p in points}) != len(points):
            raise ValueError("Landmark IDs must be unique across fit and check sets")
        for field in ("fixed_ras_mm", "moving_ras_mm"):
            if len({getattr(p, field) for p in points}) != len(points):
                raise ValueError("Landmark positions must be distinct; checks cannot reuse fit points")
        return self


def source_studies(patient: Patient, request: RegistrationRequest) -> tuple[Study, Study]:
    if patient.patient_id != request.patient_id:
        raise ValueError("Registration belongs to a different patient")
    by_id = {s.study_id: s for s in patient.studies}
    if not {request.fixed_study_id, request.moving_study_id} <= by_id.keys():
        raise ValueError("Registration examination not found")
    fixed, moving = by_id[request.fixed_study_id], by_id[request.moving_study_id]
    if fixed.acquired_day >= moving.acquired_day:
        raise ValueError("Fixed examination must precede moving examination")
    if request.organ not in fixed.coverage or request.organ not in moving.coverage:
        raise ValueError("Both examinations must explicitly cover the selected organ")
    if request.available_day < max(fixed.available_day, moving.available_day):
        raise ValueError("Registration cannot be available before its source evidence")
    if not patient.synthetic and (not fixed.scan_sha256 or not moving.scan_sha256):
        raise ValueError("Non-synthetic alignment requires both source CT hashes")
    return fixed, moving


def rigid_matrix(matrix) -> np.ndarray:
    value = np.asarray(matrix, dtype=np.float64)
    if value.shape != (4, 4) or not np.isfinite(value).all():
        raise ValueError("Expected a finite 4x4 rigid transform")
    if not np.allclose(value[3], [0, 0, 0, 1], atol=1e-10, rtol=0):
        raise ValueError("Invalid homogeneous transform")
    rotation = value[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8, rtol=0) or not np.isclose(
            np.linalg.det(rotation), 1, atol=1e-8, rtol=0):
        raise ValueError("Rigid transform must not scale, shear or reflect anatomy")
    return value


def transform_points(points, matrix) -> np.ndarray:
    matrix = rigid_matrix(matrix)
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError("Expected finite Nx3 RAS+ points")
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def _positions(pairs, field):
    return np.array([getattr(p, field) for p in pairs], dtype=np.float64)


def fit_rigid(fixed, moving) -> np.ndarray:
    fixed, moving = np.asarray(fixed, dtype=float), np.asarray(moving, dtype=float)
    if fixed.shape != moving.shape or fixed.ndim != 2 or fixed.shape[1] != 3 or not 3 <= len(fixed) <= 64:
        raise ValueError("Expected 3..64 paired Nx3 landmarks")
    if not np.isfinite(fixed).all() or not np.isfinite(moving).all():
        raise ValueError("Landmarks must be finite")
    f, m = fixed - fixed.mean(axis=0), moving - moving.mean(axis=0)
    for centered in (f, m):
        singular = np.linalg.svd(centered, compute_uv=False)
        if singular[1] <= max(singular[0] * 1e-6, 1e-3):
            raise ValueError("Coincident or nearly collinear landmarks do not constrain rotation")
    u, singular, vt = np.linalg.svd(m.T @ f)
    if singular[1] <= max(singular[0] * 1e-12, 1e-12):
        raise ValueError("Landmark correspondence is geometrically degenerate")
    correction = np.diag([1., 1., 1. if np.linalg.det(vt.T @ u.T) > 0 else -1.])
    result = np.eye(4)
    result[:3, :3] = vt.T @ correction @ u.T
    result[:3, 3] = fixed.mean(axis=0) - result[:3, :3] @ moving.mean(axis=0)
    return rigid_matrix(result)


def _errors(pairs, matrix) -> dict:
    if not pairs:
        return {"count": 0, "rmse_mm": None, "max_error_mm": None, "errors_mm": []}
    residual = transform_points(_positions(pairs, "moving_ras_mm"), matrix) - _positions(pairs, "fixed_ras_mm")
    errors = np.linalg.norm(residual, axis=1)
    return {"count": len(pairs), "rmse_mm": float(np.sqrt(np.mean(errors ** 2))),
            "max_error_mm": float(errors.max()), "errors_mm": errors.tolist()}


def register(patient: Patient, request: RegistrationRequest) -> dict:
    fixed, moving = source_studies(patient, request)
    matrix = fit_rigid(_positions(request.landmarks, "fixed_ras_mm"),
                       _positions(request.landmarks, "moving_ras_mm"))
    fit, check = _errors(request.landmarks, matrix), _errors(request.check_landmarks, matrix)
    if fit["max_error_mm"] > request.max_error_mm:
        raise ValueError("Fitted landmark error exceeds the declared tolerance")
    if check["max_error_mm"] is not None and check["max_error_mm"] > request.max_error_mm:
        raise ValueError("Independent check landmark error exceeds the declared tolerance")
    body = {"schema_version": "numi.cancer.registration.v1", "algorithm": ALGORITHM,
            "request": request.model_dump(mode="json"), "source_revision": patient.source_revision,
            "synthetic": patient.synthetic, "fixed_study_sha256": digest(fixed),
            "moving_study_sha256": digest(moving), "direction": "moving_to_fixed_ras_mm",
            "matrix": matrix.tolist(), "fit": fit, "check": check,
            "validation": "check landmarks within declared tolerance" if request.check_landmarks
                          else "fit only; no independent check landmarks",
            "limitations": ["Rigid alignment, not deformable organ registration",
                            "Landmark errors are not calibrated whole-organ uncertainty",
                            "Alignment does not establish lesion identity or treatment response"]}
    return {**body, "artifact_sha256": digest(body)}


def verify_registration(patient: Patient, artifact: dict) -> RegistrationRequest:
    if digest({k: v for k, v in artifact.items() if k != "artifact_sha256"}) != artifact.get("artifact_sha256"):
        raise ValueError("Registration integrity check failed")
    request = RegistrationRequest.model_validate(artifact.get("request"))
    expected = register(patient, request)
    for key in ("schema_version", "algorithm", "source_revision", "synthetic", "fixed_study_sha256",
                "moving_study_sha256", "direction"):
        if artifact.get(key) != expected[key]:
            raise ValueError("Registration source or algorithm changed; regenerate the alignment")
    # Numerical comparison permits normal floating-point differences across machines.
    if not np.allclose(rigid_matrix(artifact.get("matrix")), expected["matrix"], atol=1e-8, rtol=0):
        raise ValueError("Stored transform does not reproduce the reviewed landmarks")
    for kind in ("fit", "check"):
        actual, wanted = artifact.get(kind), expected[kind]
        if not isinstance(actual, dict) or actual.get("count") != wanted["count"]:
            raise ValueError("Stored landmark diagnostics do not reproduce")
        errors = np.asarray(actual.get("errors_mm"), dtype=float)
        if errors.shape != (wanted["count"],) or not np.allclose(errors, wanted["errors_mm"], atol=1e-8, rtol=0):
            raise ValueError("Stored landmark diagnostics do not reproduce")
        for metric in ("rmse_mm", "max_error_mm"):
            value = actual.get(metric)
            if wanted[metric] is None:
                valid = value is None
            else:
                valid = isinstance(value, (float, int)) and np.isclose(value, wanted[metric], atol=1e-8, rtol=0)
            if not valid:
                raise ValueError("Stored landmark diagnostics do not reproduce")
    if artifact.get("validation") != expected["validation"]:
        raise ValueError("Stored registration validation status does not reproduce")
    return request


def compare_registered_masks(fixed_mask, fixed_affine, moving_mask, moving_affine,
                             moving_to_fixed, *, max_voxels: int = 8_000_000) -> dict:
    """Nearest-neighbour overlap on shared support; original volumes stay authoritative.

    The sampling map is inv(moving_affine) @ inv(moving_to_fixed) @ fixed_affine.
    Pixels outside either observation are unobserved, never an absent lesion.
    This is a regional binary-mask comparison, not per-lesion correspondence.
    """
    from scipy.ndimage import affine_transform
    from .imaging import checked_affine

    if isinstance(max_voxels, bool) or not isinstance(max_voxels, int) or max_voxels < 1:
        raise ValueError("Voxel limit must be a positive integer")
    masks = []
    for value in (fixed_mask, moving_mask):
        value = np.asarray(value)
        if value.ndim != 3 or min(value.shape) < 1 or value.size > max_voxels:
            raise ValueError("Mask must be nonempty 3D and within the comparison voxel limit")
        if value.dtype.kind not in 'buif' or not np.isfinite(value).all() or not np.isin(value, [0, 1]).all():
            raise ValueError("Comparison requires finite binary masks")
        masks.append(value.astype(np.uint8))
    f, m = masks
    fa, ma, transform = checked_affine(fixed_affine), checked_affine(moving_affine), rigid_matrix(moving_to_fixed)
    pull = np.linalg.inv(ma) @ np.linalg.inv(transform) @ fa

    def resample(values, mapping, shape):
        # Tiny roundoff near a grid boundary should not discard exact matches.
        mapping = np.where(np.abs(mapping - np.rint(mapping)) < 1e-10, np.rint(mapping), mapping)
        return affine_transform(values, mapping[:3, :3], offset=mapping[:3, 3], output_shape=shape,
                                order=0, mode='constant', cval=0, prefilter=False)

    valid_f = resample(np.ones(m.shape, dtype=np.uint8), pull, f.shape).astype(bool)
    if not valid_f.any():
        raise ValueError("Registered fields of view have no shared sampled support")
    warped = resample(m, pull, f.shape).astype(bool)
    valid_m = resample(np.ones(f.shape, dtype=np.uint8), np.linalg.inv(pull), m.shape).astype(bool)
    fv, mv = f.astype(bool) & valid_f, warped & valid_f
    f_count, m_count = int(f.sum()), int(m.sum())
    denominator = int(fv.sum()) + int(mv.sum())
    return {"schema_version": "numi.cancer.registered-mask-comparison.v1",
            "direction": "moving_to_fixed_ras_mm", "interpolation": "nearest neighbour",
            "dice_on_shared_fixed_grid": 2 * int((fv & mv).sum()) / denominator if denominator else None,
            "shared_fixed_grid_fraction": float(valid_f.mean()),
            "fixed_tumor_observed_fraction": int((f.astype(bool) & valid_f).sum()) / f_count if f_count else None,
            "moving_tumor_observed_fraction": int((m.astype(bool) & valid_m).sum()) / m_count if m_count else None,
            "original_fixed_volume_ml": f_count * abs(float(np.linalg.det(fa[:3, :3]))) / 1000,
            "original_moving_volume_ml": m_count * abs(float(np.linalg.det(ma[:3, :3]))) / 1000,
            "notice": "Overlap depends on sampling, coverage, annotation, growth and alignment; not an identity or response score."}
