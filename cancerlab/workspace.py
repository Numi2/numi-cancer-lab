"""Read saved work and validate review drafts without changing observations."""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, Query
from pydantic import Field

from .models import Day, Identifier, Patient, Record, digest
from .registration import source_studies, verify_registration
from .store import ExperimentStore
from .tracking import CorrespondenceReview, MatchOptions, propose_matches


class ProposalPreview(Record):
    patient_id: Identifier
    cutoff_day: Day
    proposal_json: str = Field(min_length=1, max_length=2_000_000)


class ReviewDraft(ProposalPreview):
    review: CorrespondenceReview


def checked_proposal(patient: Patient, request: ProposalPreview) -> dict:
    if len(request.proposal_json.encode()) > 2_000_000:
        raise ValueError("Proposal exceeds the 2 MB review limit")
    # Preserve Python artifact number types (e.g. 0.0 versus 0). JavaScript
    # JSON.stringify normalizes them and would invalidate a sealed digest.
    proposal = json.loads(request.proposal_json)
    if not isinstance(proposal, dict):
        raise ValueError("Expected a proposal JSON object")
    if proposal.get("patient_id") != patient.patient_id:
        raise ValueError("Select the patient belonging to this proposal")
    if digest({k: v for k, v in proposal.items() if k != "artifact_sha256"}) != proposal.get("artifact_sha256"):
        raise ValueError("Proposal integrity check failed")
    registration = proposal.get("registration", {})
    alignment = verify_registration(patient, registration)
    if alignment.available_day > request.cutoff_day:
        raise ValueError("This proposal is later than the selected evidence cutoff; change the cutoff explicitly")
    fresh = propose_matches(patient, registration, MatchOptions.model_validate(proposal.get("options")))
    if fresh["artifact_sha256"] != proposal["artifact_sha256"]:
        raise ValueError("Proposal no longer matches current observations; regenerate it")
    return fresh


def install_workspace(app: FastAPI, cohort: dict[str, Patient], store: ExperimentStore) -> None:
    def patient(patient_id):
        if patient_id not in cohort:
            raise HTTPException(404, "Unknown patient")
        return cohort[patient_id]

    @app.get("/api/patients/{patient_id}/experiments")
    def history(patient_id: str, cutoff_day: int = Query(..., ge=-100000, le=100000),
                limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=10000)):
        patient(patient_id)
        # Only saved protocol metadata is listed, never outcomes or future counts.
        with store.connect() as db:
            rows = db.execute("""
                SELECT e.id, e.created_at,
                       EXISTS(SELECT 1 FROM evaluations v WHERE v.experiment_id=e.id)
                FROM experiments e
                WHERE json_extract(e.artifact, '$.patient_id')=?
                  AND json_extract(e.artifact, '$.spec.cutoff_day')<=?
                ORDER BY e.created_at DESC, e.id DESC LIMIT ? OFFSET ?
                """, (patient_id, cutoff_day, limit + 1, offset)).fetchall()
        items = []
        for run_id, created_at, evaluated in rows[:limit]:
            try:
                artifact = store.get(run_id)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise HTTPException(409, "A saved experiment failed its integrity check") from exc
            items.append({"id": run_id, "created_at": created_at, "spec": artifact["spec"],
                          "state": "evaluated" if evaluated else "sealed"})
        return {"items": items, "next_offset": offset + limit if len(rows) > limit else None}

    @app.get("/api/experiments/{run_id}/evaluation")
    def saved_evaluation(run_id: Identifier):
        try:
            return {"evaluation": store.get_evaluation(run_id)}
        except KeyError as exc:
            raise HTTPException(404, "Unknown sealed experiment") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/workspace/proposal")
    def preview(request: ProposalPreview):
        try:
            return checked_proposal(patient(request.patient_id), request)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise HTTPException(422, str(exc) or "Malformed proposal") from exc

    @app.post("/api/workspace/review")
    def review(request: ReviewDraft):
        try:
            owner = patient(request.patient_id)
            proposal = checked_proposal(owner, request)
            decision = request.review
            if decision.proposal_sha256 != proposal["artifact_sha256"]:
                raise ValueError("Review belongs to another proposal")
            if not proposal["available_day"] <= decision.available_day <= request.cutoff_day:
                raise ValueError("Review day must follow alignment availability and not exceed the selected cutoff")
            candidates = {(c["fixed_lesion_id"], c["moving_lesion_id"]) for c in proposal["candidates"]}
            alignment = verify_registration(owner, proposal["registration"])
            fixed, _ = source_studies(owner, alignment)
            anchors = {m.lesion_id for m in fixed.lesions if m.correspondence == "confirmed"}
            for link in decision.links:
                if not link.reason.strip():
                    raise ValueError("Write a reason for every selected correspondence")
                if (link.fixed_lesion_id, link.moving_lesion_id) not in candidates:
                    raise ValueError("Selected pair is not a verified proposal candidate")
                if link.fixed_lesion_id not in anchors:
                    raise ValueError("Establish the earlier track identity before linking observations")
            # Exportable decision only. The existing review-tracks command still
            # checks the original import manifest before producing a NEW manifest.
            return decision
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise HTTPException(422, str(exc) or "Malformed review") from exc
