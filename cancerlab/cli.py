"""Local entry points. Use `python -m cancerlab --help`."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audit import audit_cohort
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
    audit = audit_cohort(patients)
    if audit["duplicate_scans"]:
        raise ValueError("Duplicate scans detected; audit the cohort before benchmarking")
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
        total_errors = []
        lesion_errors = []
        scored_lesions = 0
        for row in rows:
            score = row["evaluation"]["scores"][method]
            if score["total_absolute_error_ml"] is not None:
                total_errors.append(score["total_absolute_error_ml"])
            for lesion in score["lesions"].values():
                error = lesion.get("absolute_error_ml")
                if error is not None:
                    lesion_errors.append(error)
                    scored_lesions += 1
        summary[method] = {
            # Preserve the published v1 fields for existing consumers.
            "scored_patients": len(total_errors),
            "patient_mean_absolute_error_ml":
                sum(total_errors) / len(total_errors) if total_errors else None,
            "eligible_patients": len(rows),
            "scored_patients_total_burden": len(total_errors),
            "scored_lesions": scored_lesions,
            "patient_mean_total_absolute_error_ml":
                sum(total_errors) / len(total_errors) if total_errors else None,
            "pooled_lesion_mae_ml":
                sum(lesion_errors) / len(lesion_errors) if lesion_errors else None,
        }
    return {"schema_version": "numi.cancer.benchmark.v1",
            "synthetic_only": all(p.synthetic for p in patients.values()),
            "protocol": {"cutoff_day": cutoff, "horizon_days": horizon, "organ": organ},
            "cohort": {"input_patients": len(patients), "eligible_patients": len(rows),
                       "skipped_patients": len(skipped)},
            "summary": summary, "patients": rows, "skipped": skipped, "audit": audit,
            "interpretation": "Retrospective baseline evaluation, not a trained-model or clinical benchmark"}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Numi Cancer Lab — local research, not clinical guidance")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Launch the local research workspace")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--patients", type=Path)
    serve.add_argument("--scan-root", type=Path, help="Local CancerVerse root for source CT/mask inspection")
    serve.add_argument("--db", type=Path, default=Path("var/experiments.sqlite3"))
    demo = commands.add_parser("demo", help="Write the entirely synthetic demonstration records")
    demo.add_argument("--out", type=Path, default=Path("data/demo"))
    bench = commands.add_parser("benchmark", help="Evaluate fixed-cutoff baselines, one result per patient")
    bench.add_argument("--patients", type=Path)
    bench.add_argument("--cutoff", type=int, default=90)
    bench.add_argument("--horizon", type=int, default=90)
    bench.add_argument("--organ", default="liver")
    bench.add_argument("--out", type=Path, default=Path("var/benchmark.json"))
    audit = commands.add_parser("audit", help="Check exact duplicate scans without inferring patient identity")
    audit.add_argument("--patients", type=Path)
    inspect = commands.add_parser("cancerverse-inspect", help="Inspect local metadata columns, without publishing rows")
    inspect.add_argument("--root", type=Path, required=True)
    ingest = commands.add_parser("cancerverse-import", help="Import local NIfTI measurements with a reviewed manifest")
    ingest.add_argument("--root", type=Path, required=True)
    ingest.add_argument("--manifest", type=Path, required=True)
    ingest.add_argument("--out", type=Path, required=True)
    ingest.add_argument("--receipt", type=Path, required=True)
    ingest.add_argument("--acknowledge-license", action="store_true")
    commands.add_parser("import-schema", help="Print the reviewed CancerVerse import manifest JSON Schema")
    commands.add_parser("schema", help="Print the patient JSON Schema")
    from .tracking_cli import COMMANDS, configure, run as run_tracking
    configure(commands)
    args = parser.parse_args(argv)
    try:
        if args.command in COMMANDS:
            run_tracking(args)
        elif args.command == "serve":
            import uvicorn
            from .api import create_app
            if not 1024 <= args.port <= 65535:
                raise ValueError("Port must be in 1024..65535")
            uvicorn.run(create_app(load_patients(args.patients), args.db, args.scan_root), host="127.0.0.1", port=args.port)
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
        elif args.command == "audit":
            result = audit_cohort(load_patients(args.patients))
            print(json.dumps(result, indent=2))
            if result["duplicate_scans"]:
                raise ValueError("Duplicate scans require review")
        elif args.command == "cancerverse-inspect":
            from .cancerverse import inspect
            print(json.dumps(inspect(args.root), indent=2))
        elif args.command == "cancerverse-import":
            from .cancerverse import ImportManifest, import_records, write_import
            if args.out.exists() or args.receipt.exists():
                raise ValueError("Import destination or receipt already exists")
            manifest = ImportManifest.model_validate_json(args.manifest.read_text())
            patients, receipt = import_records(args.root, manifest, acknowledge_license=args.acknowledge_license)
            write_import(patients, receipt, args.out, args.receipt)
            print(f"Imported {len(patients)} local patient records; receipt: {args.receipt}")
        elif args.command == "import-schema":
            from .cancerverse import ImportManifest
            print(json.dumps(ImportManifest.model_json_schema(), indent=2))
        elif args.command == "schema":
            print(json.dumps(Patient.model_json_schema(), indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
