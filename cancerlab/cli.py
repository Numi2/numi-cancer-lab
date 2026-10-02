"""Local entry points. Use `python -m cancerlab --help`."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .demo import demo_patients
from .engine import ExperimentSpec, evaluate, forecast
from .models import Patient, canonical, snapshot


def load_patients(directory: Path | None) -> dict[str, Patient]:
    if directory is None:
        return demo_patients()
    if not directory.is_dir():
        raise ValueError("Patient directory does not exist")
    patients = {}
    for path in sorted(directory.glob("*.json")):
        patient = Patient.model_validate_json(path.read_text())
        if patient.patient_id in patients:
            raise ValueError("Duplicate patient ID; refusing to overwrite a record")
        patients[patient.patient_id] = patient
    if not patients:
        raise ValueError("No canonical patient JSON records found")
    return patients


def benchmark(patients: dict[str, Patient], cutoff: int, horizon: int, organ: str) -> dict:
    rows, skipped = [], []
    for patient in patients.values():
        try:
            spec = ExperimentSpec(cutoff_day=cutoff, horizon_days=horizon, organ=organ)
            run = forecast(snapshot(patient, cutoff), spec)
            result = evaluate(run, patient)
            rows.append({"patient_id": patient.patient_id, "run": run, "evaluation": result})
        except ValueError as exc:
            skipped.append({"patient_id": patient.patient_id, "reason": str(exc)})
    summary = {}
    for method in ("no_change", "linear", "exponential"):
        errors = [r["evaluation"]["scores"][method]["total_absolute_error_ml"] for r in rows]
        errors = [e for e in errors if e is not None]
        summary[method] = {"scored_patients": len(errors), "patient_mean_absolute_error_ml":
                           sum(errors) / len(errors) if errors else None}
    return {"schema_version": "numi.cancer.benchmark.v1", "synthetic_only": all(p.synthetic for p in patients.values()),
            "protocol": {"cutoff_day": cutoff, "horizon_days": horizon, "organ": organ},
            "summary": summary, "patients": rows, "skipped": skipped,
            "interpretation": "Retrospective baseline evaluation, not a trained-model or clinical benchmark"}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Numi Cancer Lab — local research, not clinical guidance")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Launch the local research workspace")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--patients", type=Path)
    serve.add_argument("--db", type=Path, default=Path("var/experiments.sqlite3"))
    demo = commands.add_parser("demo", help="Write the entirely synthetic demonstration records")
    demo.add_argument("--out", type=Path, default=Path("data/demo"))
    bench = commands.add_parser("benchmark", help="Evaluate fixed-cutoff baselines, one result per patient")
    bench.add_argument("--patients", type=Path)
    bench.add_argument("--cutoff", type=int, default=90)
    bench.add_argument("--horizon", type=int, default=90)
    bench.add_argument("--organ", default="liver")
    bench.add_argument("--out", type=Path, default=Path("var/benchmark.json"))
    commands.add_parser("schema", help="Print the patient JSON Schema")
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            import uvicorn
            from .api import create_app
            if not 1024 <= args.port <= 65535:
                raise ValueError("Port must be in 1024..65535")
            uvicorn.run(create_app(load_patients(args.patients), args.db), host="127.0.0.1", port=args.port)
        elif args.command == "demo":
            patients = demo_patients()
            args.out.mkdir(parents=True, exist_ok=True)
            if any((args.out / f"{p}.json").exists() for p in patients):
                raise ValueError("Destination already contains demo records; no files overwritten")
            for patient in patients.values():
                (args.out / f"{patient.patient_id}.json").write_text(patient.model_dump_json(indent=2))
            print(f"Wrote {len(patients)} synthetic records to {args.out}")
        elif args.command == "benchmark":
            result = benchmark(load_patients(args.patients), args.cutoff, args.horizon, args.organ)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=2, allow_nan=False))
            print(json.dumps(result["summary"], indent=2))
        elif args.command == "schema":
            print(json.dumps(Patient.model_json_schema(), indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
