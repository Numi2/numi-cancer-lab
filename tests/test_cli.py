import json

import pytest

from cancerlab.cli import benchmark, load_patients, main
from cancerlab.demo import demo_patients


def test_demo_roundtrip_and_no_overwrite(tmp_path):
    out = tmp_path / 'demo'
    main(['demo', '--out', str(out)])
    assert load_patients(out) == demo_patients()
    with pytest.raises(SystemExit):
        main(['demo', '--out', str(out)])


def test_benchmark_reports_skipped_and_denominators():
    result = benchmark(demo_patients(), 90, 90, 'liver')
    assert result['synthetic_only']
    assert len(result['skipped']) == 2
    assert result['summary']['linear']['scored_patients'] == 1
    assert result['summary']['linear']['patient_mean_absolute_error_ml'] == pytest.approx(1.7)


def test_empty_directory_refused(tmp_path):
    with pytest.raises(ValueError, match='No canonical'):
        load_patients(tmp_path)


def test_duplicate_patient_files_refused(tmp_path):
    patient = demo_patients()['SYN-001']
    for name in ['a.json', 'b.json']:
        (tmp_path / name).write_text(patient.model_dump_json())
    with pytest.raises(ValueError, match='Duplicate'):
        load_patients(tmp_path)


def test_cli_schema(capsys):
    main(['schema'])
    assert json.loads(capsys.readouterr().out)['title'] == 'Patient'
