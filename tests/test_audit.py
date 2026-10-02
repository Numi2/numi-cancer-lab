import pytest
from pydantic import ValidationError

from cancerlab.audit import audit_cohort
from cancerlab.cli import benchmark, main
from cancerlab.demo import demo_patients
from cancerlab.models import Patient, Snapshot, snapshot
from cancerlab.store import ExperimentStore


def test_demo_audit_passes_without_claiming_alias_resolution():
    report = audit_cohort(demo_patients())
    assert report['status'] == 'exact-hash-check-passed'
    assert not report['duplicate_scans']
    assert 'Different hashes' in report['limitations'][1]


def test_cross_patient_duplicate_blocks_benchmark():
    patients = demo_patients()
    p = patients['SYN-002'].model_dump(mode='json')
    p['studies'][0]['scan_sha256'] = patients['SYN-001'].studies[0].scan_sha256
    patients['SYN-002'] = Patient.model_validate(p)
    report = audit_cohort(patients)
    assert report['duplicate_scans'][0]['cross_patient']
    with pytest.raises(ValueError, match='Duplicate'):
        benchmark(patients, 90, 90, 'liver')


def test_missing_hashes_are_incomplete_not_passed():
    patients = demo_patients()
    p = patients['SYN-001'].model_dump(mode='json')
    p['studies'][0]['scan_sha256'] = None
    patients['SYN-001'] = Patient.model_validate(p)
    assert audit_cohort(patients)['status'] == 'incomplete'


def test_snapshot_direct_constructor_refuses_reordered_studies():
    history = snapshot(demo_patients()['SYN-001'], 90).model_dump(mode='json')
    history['studies'].reverse()
    with pytest.raises(ValidationError, match='ordered'):
        Snapshot.model_validate(history)


def test_database_connections_close(tmp_path):
    import sqlite3
    store = ExperimentStore(tmp_path / 'test.sqlite3')
    with store.connect() as db:
        assert db.execute('SELECT 1').fetchone() == (1,)
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        db.execute('SELECT 1')


def test_import_schema_command(capsys):
    import json
    main(['import-schema'])
    assert json.loads(capsys.readouterr().out)['title'] == 'ImportManifest'


def test_published_duplicate_helper_uses_real_schema():
    from cancerlab.audit import audit_duplicate_scans
    patients = demo_patients()
    assert audit_duplicate_scans(patients.values()) == []
    p = patients['SYN-002'].model_dump(mode='json')
    p['studies'][0]['scan_sha256'] = patients['SYN-001'].studies[0].scan_sha256
    patients['SYN-002'] = Patient.model_validate(p)
    assert len(audit_duplicate_scans(iter(patients.values()))) == 1


def test_hash_helper_and_chunk_validation(tmp_path):
    from cancerlab.audit import sha256_file
    p = tmp_path / 'scan'; p.write_bytes(b'abc')
    assert sha256_file(p, 1) == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    with pytest.raises(ValueError):
        sha256_file(p, 0)
