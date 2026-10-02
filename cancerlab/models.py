"""Versioned, immutable observations. Days are relative to a de-identified origin."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")]
Number = Annotated[float, Field(allow_inf_nan=False)]
Volume = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Day = Annotated[int, Field(strict=True, ge=-100000, le=100000)]
Organ = Literal["liver", "pancreas", "kidney", "stomach", "adrenal_gland", "colon",
                "bladder", "prostate", "esophagus", "spleen", "uterus", "duodenum", "gallbladder"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(Record):
    source: str = Field(min_length=1, max_length=300)
    method: Literal["synthetic", "manual", "mask-volume"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Lesion(Record):
    lesion_id: Identifier
    organ: Organ
    state: Literal["present", "absent", "not_assessed"] = "present"
    volume_ml: Volume | None
    centroid_ras_mm: tuple[Number, Number, Number] | None = None
    correspondence: Literal["confirmed", "unverified"] = "unverified"
    evidence: Evidence

    @model_validator(mode="after")
    def consistent(self):
        if self.state == "present" and (self.volume_ml is None or self.volume_ml <= 0):
            raise ValueError("A present lesion requires a positive measured volume")
        if self.state == "absent" and self.volume_ml != 0:
            raise ValueError("An explicitly absent lesion requires zero volume")
        if self.state == "not_assessed" and self.volume_ml is not None:
            raise ValueError("Not assessed is unknown, never zero")
        return self


class Study(Record):
    study_id: Identifier
    acquired_day: Day
    available_day: Day
    coverage: tuple[Organ, ...] = ()
    annotation_scope: Literal["complete", "partial", "unknown"] = "unknown"
    lesions: tuple[Lesion, ...] = ()
    scan_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def consistent(self):
        if self.available_day < self.acquired_day:
            raise ValueError("Study evidence cannot be available before acquisition")
        ids = [m.lesion_id for m in self.lesions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate lesion IDs in a study")
        if len(set(self.coverage)) != len(self.coverage):
            raise ValueError("Duplicate coverage entries")
        for m in self.lesions:
            if m.state != "not_assessed" and m.organ not in self.coverage:
                raise ValueError("Measured lesion must be within explicitly declared coverage")
        return self


class ClinicalEvent(Record):
    event_id: Identifier
    occurred_day: Day
    available_day: Day
    kind: Literal["report", "treatment", "pathology", "note"]
    text: str = Field(min_length=1, max_length=30000)
    evidence: Evidence

    @model_validator(mode="after")
    def consistent(self):
        if self.available_day < self.occurred_day:
            raise ValueError("Event cannot be available before it occurred")
        return self


class Patient(Record):
    schema_version: Literal["numi.cancer.patient.v1"] = "numi.cancer.patient.v1"
    patient_id: Identifier
    source: str
    source_revision: str = Field(min_length=1)
    synthetic: bool
    studies: tuple[Study, ...]
    events: tuple[ClinicalEvent, ...] = ()

    @model_validator(mode="after")
    def consistent(self):
        ids = [s.study_id for s in self.studies]
        days = [s.acquired_day for s in self.studies]
        if len(ids) != len(set(ids)):
            raise ValueError("Study IDs must be unique")
        if len(days) != len(set(days)):
            raise ValueError("Select one study/phase per examination day before import")
        if days != sorted(days):
            raise ValueError("Studies must be ordered by acquisition day")
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("Event IDs must be unique")
        organs: dict[str, str] = {}
        for study in self.studies:
            for m in study.lesions:
                if m.lesion_id in organs and organs[m.lesion_id] != m.organ:
                    raise ValueError("A lesion track cannot change organ")
                organs[m.lesion_id] = m.organ
        return self


class Snapshot(Record):
    """The entire forecaster input. No whole-patient object or future summary."""
    patient_id: Identifier
    source_revision: str
    synthetic: bool
    cutoff_day: Day
    studies: tuple[Study, ...]
    events: tuple[ClinicalEvent, ...]

    @model_validator(mode="after")
    def no_future(self):
        days = [s.acquired_day for s in self.studies]
        ids = [s.study_id for s in self.studies]
        if days != sorted(set(days)) or len(ids) != len(set(ids)):
            raise ValueError("Snapshot studies must have unique IDs and strictly ordered dates")
        if any(max(s.acquired_day, s.available_day) > self.cutoff_day for s in self.studies):
            raise ValueError("Future study in snapshot")
        if any(max(e.occurred_day, e.available_day) > self.cutoff_day for e in self.events):
            raise ValueError("Future clinical event in snapshot")
        return self


def canonical(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def snapshot(patient: Patient, cutoff_day: int) -> Snapshot:
    return Snapshot(patient_id=patient.patient_id, source_revision=patient.source_revision,
                    synthetic=patient.synthetic, cutoff_day=cutoff_day,
                    studies=tuple(s for s in patient.studies
                                  if max(s.acquired_day, s.available_day) <= cutoff_day),
                    events=tuple(e for e in patient.events
                                 if max(e.occurred_day, e.available_day) <= cutoff_day))
