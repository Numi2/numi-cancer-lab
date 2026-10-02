"""Deterministic baselines and prospective-style evaluation, not trained cancer AI."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from .models import Day, Organ, Patient, Record, Snapshot, canonical, digest, snapshot

METHODS = ("no_change", "linear", "exponential")


class ExperimentSpec(Record):
    cutoff_day: Day
    horizon_days: Annotated[int, Field(strict=True, ge=1, le=730)] = 90
    tolerance_days: Annotated[int, Field(strict=True, ge=0, le=30)] = 0
    organ: Organ = "liver"
    assumptions: Literal["observed-history extrapolation; no treatment-effect model"] = (
        "observed-history extrapolation; no treatment-effect model")


def engine_fingerprint() -> str:
    h = hashlib.sha256()
    for name in ("models.py", "engine.py"):
        h.update(name.encode())
        h.update(Path(__file__).with_name(name).read_bytes())
    return h.hexdigest()


def forecast(history: Snapshot, spec: ExperimentSpec) -> dict:
    """Read only a cutoff-filtered Snapshot; never consult held-out observations."""
    if history.cutoff_day != spec.cutoff_day:
        raise ValueError("Snapshot/spec cutoff mismatch")
    studies = [s for s in history.studies if spec.organ in s.coverage]
    if not studies:
        raise ValueError("No visible study covers the selected organ")
    latest = studies[-1]
    target = spec.cutoff_day + spec.horizon_days
    if target > 100000:
        raise ValueError("Target day outside supported range")
    tracks = {m.lesion_id for s in studies for m in s.lesions if m.organ == spec.organ}
    results = {}
    for method in METHODS:
        values, abstentions = {}, {}
        for track in sorted(tracks):
            observations = [(s.acquired_day, m) for s in studies for m in s.lesions
                            if m.organ == spec.organ and m.lesion_id == track]
            last = next((m for m in latest.lesions if m.lesion_id == track), None)
            if last is None or last.state == "not_assessed":
                abstentions[track] = "Not explicitly assessed in latest covered study"
                continue
            if last.correspondence != "confirmed":
                abstentions[track] = "Longitudinal identity has not been confirmed"
                continue
            usable = [(d, m.volume_ml) for d, m in observations
                      if m.state != "not_assessed" and m.correspondence == "confirmed"]
            day, volume = usable[-1]
            if method == "no_change":
                value = volume
            elif len(usable) < 2:
                abstentions[track] = "Needs two distinct, verified observation dates"
                continue
            else:
                previous_day, previous_volume = usable[-2]
                dt = day - previous_day
                if dt <= 0:
                    raise ValueError("Non-increasing observation dates")
                if method == "linear":
                    value = max(0.0, volume + (volume - previous_volume) / dt * (target - day))
                else:
                    if min(volume, previous_volume) <= 0:
                        abstentions[track] = "Exponential model requires positive volumes"
                        continue
                    exponent = math.log(volume / previous_volume) / dt * (target - day)
                    if not math.isfinite(exponent) or abs(exponent) > 50:
                        abstentions[track] = "Extrapolation exceeds numerical validity range"
                        continue
                    value = volume * math.exp(exponent)
            if not math.isfinite(value) or value > 1e6:
                abstentions[track] = "Extrapolation exceeds numerical validity range"
                continue
            values[track] = round(value, 8)
        complete = (latest.annotation_scope == "complete" and not abstentions)
        results[method] = {"lesions_ml": values, "abstentions": abstentions,
                           "total_ml": round(sum(values.values()), 8) if complete else None,
                           "uncertainty": None, "uncertainty_status": "not calibrated"}
    body = {"schema_version": "numi.cancer.experiment.v1", "patient_id": history.patient_id,
            "synthetic": history.synthetic, "spec": spec.model_dump(mode="json"),
            "target_day": target, "snapshot": history.model_dump(mode="json"),
            "snapshot_sha256": digest(history), "engine_sha256": engine_fingerprint(),
            "models": results,
            "limitations": ["Baseline extrapolations, not a validated biological model",
                            "No calibrated prediction intervals or treatment-effect estimates",
                            "No forecast of new lesions; organ-total scoring includes them"]}
    return {**body, "artifact_sha256": digest(body)}


def verify_run(run: dict) -> None:
    body = {k: v for k, v in run.items() if k != "artifact_sha256"}
    if digest(body) != run.get("artifact_sha256"):
        raise ValueError("Experiment artifact integrity check failed")
    if digest(run["snapshot"]) != run["snapshot_sha256"]:
        raise ValueError("Snapshot integrity check failed")


def evaluate(run: dict, patient: Patient) -> dict:
    verify_run(run)
    if patient.patient_id != run["patient_id"]:
        raise ValueError("Wrong patient for this experiment")
    spec = ExperimentSpec.model_validate(run["spec"])
    if digest(snapshot(patient, spec.cutoff_day)) != run["snapshot_sha256"]:
        raise ValueError("Observed input changed after sealing; create a new experiment")
    target = run["target_day"]
    candidates = [s for s in patient.studies
                  if s.acquired_day > spec.cutoff_day
                  and abs(s.acquired_day - target) <= spec.tolerance_days
                  and spec.organ in s.coverage]
    if not candidates:
        raise ValueError("No held-out study within the predeclared target tolerance")
    truth = min(candidates, key=lambda s: (abs(s.acquired_day - target), s.acquired_day))
    assessed = {m.lesion_id: m for m in truth.lesions
                if m.organ == spec.organ and m.state != "not_assessed"}
    incomplete = any(m.organ == spec.organ and m.state == "not_assessed" for m in truth.lesions)
    actual_total = (sum(m.volume_ml for m in assessed.values())
                    if truth.annotation_scope == "complete" and not incomplete else None)
    known_tracks = {m["lesion_id"] for s in run["snapshot"]["studies"] for m in s["lesions"]
                    if m["organ"] == spec.organ}
    scores = {}
    for method, prediction in run["models"].items():
        per_lesion = {}
        for track, estimate in prediction["lesions_ml"].items():
            measured = assessed.get(track)
            per_lesion[track] = ({"predicted_ml": estimate, "actual_ml": measured.volume_ml,
                                 "absolute_error_ml": abs(estimate - measured.volume_ml)}
                                if measured and measured.correspondence == "confirmed" else
                                {"predicted_ml": estimate, "actual_ml": None,
                                 "absolute_error_ml": None, "reason": "Missing or unverified correspondence"})
        errors = [m["absolute_error_ml"] for m in per_lesion.values() if m["absolute_error_ml"] is not None]
        predicted_total = prediction["total_ml"]
        scores[method] = {"lesions": per_lesion, "scored_lesions": len(errors),
                          "lesion_mae_ml": sum(errors) / len(errors) if errors else None,
                          "predicted_total_ml": predicted_total, "actual_total_ml": actual_total,
                          "total_absolute_error_ml": abs(predicted_total - actual_total)
                          if predicted_total is not None and actual_total is not None else None}
    return {"schema_version": "numi.cancer.evaluation.v1", "artifact_sha256": run["artifact_sha256"],
            "truth_sha256": digest(truth), "truth_study": truth.model_dump(mode="json"),
            "target_day": target, "actual_day": truth.acquired_day,
            "horizon_offset_days": truth.acquired_day - target,
            "new_observed_tracks": sorted(set(assessed) - known_tracks), "scores": scores,
            "interpretation": "Synthetic software demonstration" if patient.synthetic else
                              "Retrospective baseline evaluation; not clinical validation"}
