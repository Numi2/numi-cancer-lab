"""Loopback-only research API. No uploads, telemetry, remote models, or external assets."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .demo import demo_patients
from .engine import ExperimentSpec, evaluate, forecast
from .models import Identifier, Organ, Patient, Record, Study, canonical, snapshot
from .store import ExperimentStore
from .scanview import LocalScans
from .workspace import install_workspace


class CreateExperiment(Record):
    patient_id: Identifier
    spec: ExperimentSpec


def create_app(patients: dict[str, Patient] | None = None, db_path: Path | None = None,
               scan_root: Path | None = None) -> FastAPI:
    cohort = demo_patients() if patients is None else patients
    scans = LocalScans(scan_root) if scan_root is not None else None
    store = ExperimentStore(db_path or Path("var/experiments.sqlite3"))
    app = FastAPI(title="Numi Cancer Lab", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("x-cancerlab-request") != "local-research":
                return JSONResponse({"detail": "Missing local research request header"}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"detail": "Cross-origin writes are disabled"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        return response

    def patient_or_404(patient_id: str) -> Patient:
        if patient_id not in cohort:
            raise HTTPException(404, "Unknown patient")
        return cohort[patient_id]

    def run_or_404(run_id: str) -> dict:
        try:
            return store.get(run_id)
        except KeyError as exc:
            raise HTTPException(404, "Unknown sealed experiment") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "mode": "local research",
                "synthetic_only": all(p.synthetic for p in cohort.values()), "patients": len(cohort),
                "local_imaging_configured": scans is not None}

    @app.get("/api/patients")
    def list_patients():
        # No future diagnosis, scan count, or outcome-derived labels in the selector.
        return [{"patient_id": p.patient_id, "synthetic": p.synthetic} for p in cohort.values()]

    @app.get("/api/patients/{patient_id}/snapshot")
    def read_snapshot(patient_id: str, cutoff_day: int = Query(..., ge=-100000, le=100000)):
        return snapshot(patient_or_404(patient_id), cutoff_day)

    def visible_study(patient_id: str, study_id: str, cutoff_day: int, run_id: str | None):
        patient = patient_or_404(patient_id)
        if run_id is None:
            studies = snapshot(patient, cutoff_day).studies
        else:
            run = run_or_404(run_id)
            if run["patient_id"] != patient_id:
                raise HTTPException(404, "Study not available in this view")
            try:
                result = store.get_evaluation(run_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            studies = () if result is None else (Study.model_validate(result["truth_study"]),)
        for study in studies:
            if study.study_id == study_id:
                return patient, study
        raise HTTPException(404, "Study not available in this view")

    @app.get("/api/patients/{patient_id}/studies/{study_id}/image")
    def image_metadata(patient_id: str, study_id: str, organ: Organ,
                       cutoff_day: int = Query(..., ge=-100000, le=100000), run_id: Identifier | None = None):
        patient, study = visible_study(patient_id, study_id, cutoff_day, run_id)
        if scans is None:
            return {"configured": False, "notice": "Start the local server with --scan-root to inspect imported CT images"}
        try:
            return {"configured": True, **scans.metadata(patient, study, organ)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(422, "Local image unavailable; check the configured dataset root") from exc

    @app.get("/api/patients/{patient_id}/studies/{study_id}/slice")
    def image_slice(patient_id: str, study_id: str, organ: Organ,
                    cutoff_day: int = Query(..., ge=-100000, le=100000),
                    plane: Literal["axial", "coronal", "sagittal"] = "axial",
                    index: int = Query(..., ge=0), center: float = Query(40, ge=-5000, le=5000, allow_inf_nan=False),
                    width: float = Query(400, ge=1, le=10000, allow_inf_nan=False),
                    opacity: float = Query(.4, ge=0, le=1, allow_inf_nan=False), run_id: Identifier | None = None):
        patient, study = visible_study(patient_id, study_id, cutoff_day, run_id)
        if scans is None:
            raise HTTPException(409, "Local imaging is not configured")
        try:
            return scans.slice(patient, study, organ, plane, index, center, width, opacity)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(422, "Local image unavailable; check the configured dataset root") from exc

    @app.post("/api/experiments", status_code=201)
    def create_experiment(request: CreateExperiment):
        patient = patient_or_404(request.patient_id)
        try:
            artifact = forecast(snapshot(patient, request.spec.cutoff_day), request.spec)
            run_id = store.seal(artifact)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": run_id, "artifact": artifact, "state": "sealed"}

    @app.get("/api/experiments/{run_id}")
    def read_experiment(run_id: str):
        return {"id": run_id, "artifact": run_or_404(run_id), "state": "sealed"}

    @app.post("/api/experiments/{run_id}/reveal")
    def reveal(run_id: str):
        run = run_or_404(run_id)
        try:
            result = evaluate(run, patient_or_404(run["patient_id"]))
            evaluation_id = store.record_evaluation(run_id, result)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"evaluation_id": evaluation_id, "evaluation": result}

    @app.get("/api/experiments/{run_id}/export")
    def export(run_id: str):
        run = run_or_404(run_id)
        return Response(canonical(run), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="numi-experiment.json"'})

    @app.get("/api/schemas/patient")
    def patient_schema():
        return Patient.model_json_schema()

    @app.get("/")
    def index():
        return FileResponse(Path(__file__).with_name("web") / "index.html")

    install_workspace(app, cohort, store)
    app.mount("/static", StaticFiles(directory=Path(__file__).with_name("web")), name="static")
    return app
