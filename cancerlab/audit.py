"""Data-quality audit primitives."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from .models import Patient


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_duplicate_scans(patients: Iterable[Patient]) -> list[dict]:
    """Find exact scan reuse across records. Metadata IDs alone are not trusted."""
    by_hash: dict[str, list[dict]] = {}
    for patient in patients:
        for study in patient.studies:
            for evidence in study.evidence:
                if evidence.kind != "ct" or not evidence.content_sha256:
                    continue
                by_hash.setdefault(evidence.content_sha256, []).append({
                    "patient_id": patient.patient_id,
                    "study_id": study.study_id,
                    "source_ref": evidence.source_ref,
                })
    return [{"sha256": digest, "occurrences": occurrences}
            for digest, occurrences in sorted(by_hash.items()) if len(occurrences) > 1]
