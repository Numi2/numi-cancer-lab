"""Conservative exact-duplicate audit; not a claim of resolved patient identity."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from .models import Patient


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("Hash chunk size must be a positive integer")
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def audit_cohort(patients: dict[str, Patient]) -> dict:
    scans, missing = {}, []
    for patient in patients.values():
        for study in patient.studies:
            reference = {'patient_id': patient.patient_id, 'study_id': study.study_id}
            if study.scan_sha256 is None:
                missing.append(reference)
            else:
                scans.setdefault(study.scan_sha256, []).append(reference)
    duplicates = [{'scan_sha256': key, 'records': refs,
                   'cross_patient': len({r['patient_id'] for r in refs}) > 1}
                  for key, refs in sorted(scans.items()) if len(refs) > 1]
    return {'schema_version': 'numi.cancer.audit.v1', 'patients': len(patients),
            'duplicate_scans': duplicates, 'unhashed_studies': missing,
            'status': 'blocked' if duplicates else 'incomplete' if missing else 'exact-hash-check-passed',
            'limitations': ['Exact hash comparison only; no report-based alias resolution',
                            'Different hashes do not establish different patients or scan content']}


def audit_duplicate_scans(patients: Iterable[Patient]) -> list[dict]:
    """Retain the published helper, using the actual Study.scan_sha256 schema."""
    rows = list(patients)
    if len({p.patient_id for p in rows}) != len(rows):
        raise ValueError("Duplicate patient IDs; refusing to discard records")
    report = audit_cohort({p.patient_id: p for p in rows})
    return [{'sha256': d['scan_sha256'], 'occurrences': d['records']}
            for d in report['duplicate_scans']]
