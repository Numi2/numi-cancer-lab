"""Append-only sealed experiments in local SQLite; evaluations are separate records."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .engine import verify_run
from .models import canonical, digest


class ExperimentStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, artifact TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS evaluations (
                    id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
                    created_at TEXT NOT NULL, artifact TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS no_experiment_update BEFORE UPDATE ON experiments
                    BEGIN SELECT RAISE(ABORT, 'Sealed experiments are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS no_experiment_delete BEFORE DELETE ON experiments
                    BEGIN SELECT RAISE(ABORT, 'Sealed experiments are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS no_evaluation_update BEFORE UPDATE ON evaluations
                    BEGIN SELECT RAISE(ABORT, 'Evaluations are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS no_evaluation_delete BEFORE DELETE ON evaluations
                    BEGIN SELECT RAISE(ABORT, 'Evaluations are immutable'); END;
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def seal(self, artifact: dict) -> str:
        verify_run(artifact)
        run_id = uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO experiments VALUES (?, ?, ?)",
                       (run_id, datetime.now(timezone.utc).isoformat(), canonical(artifact)))
        return run_id

    def get(self, run_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT artifact FROM experiments WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown experiment")
        artifact = json.loads(row[0])
        verify_run(artifact)
        return artifact

    def record_evaluation(self, run_id: str, evaluation: dict) -> str:
        run = self.get(run_id)
        if evaluation["artifact_sha256"] != run["artifact_sha256"]:
            raise ValueError("Evaluation belongs to another experiment")
        key = digest([run_id, evaluation])
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO evaluations VALUES (?, ?, ?, ?)",
                       (key, run_id, datetime.now(timezone.utc).isoformat(), canonical(evaluation)))
        return key
