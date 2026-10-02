import copy
import sqlite3

import pytest
from pydantic import ValidationError

from cancerlab.demo import demo_patients
from cancerlab.engine import ExperimentSpec, evaluate, forecast, verify_run
from cancerlab.models import Patient, Snapshot, digest, snapshot
from cancerlab.store import ExperimentStore


@pytest.fixture
def patient():
    return demo_patients()["SYN-001"]


def mutate(patient, operation):
    data = patient.model_dump(mode="json")
    operation(data)
    return Patient.model_validate(data)


def run_for(patient, **kwargs):
    spec = ExperimentSpec(cutoff_day=90, **kwargs)
    return forecast(snapshot(patient, 90), spec)


def test_demo_valid_and_synthetic():
    assert len(demo_patients()) == 3
    assert all(p.synthetic for p in demo_patients().values())


def test_cutoff_filters_late_reports_and_scans(patient):
    history = snapshot(patient, 90)
    assert len(history.studies) == 2
    assert [e.event_id for e in history.events] == ["E1"]
    assert "HELD-OUT" not in history.model_dump_json()
    assert len(snapshot(patient, 1).events) == 0


def test_delayed_annotation_is_not_available_at_acquisition(patient):
    changed = mutate(patient, lambda d: d["studies"][1].update(available_day=100))
    assert len(snapshot(changed, 90).studies) == 1


def test_future_perturbation_cannot_change_prediction(patient):
    original = run_for(patient)
    data = patient.model_dump(mode="json")
    data["studies"][2]["lesions"][0]["volume_ml"] = 9000
    data["events"][1]["text"] = "A future diagnosis changed completely"
    changed = run_for(Patient.model_validate(data))
    assert original == changed


def test_linear_and_exponential_are_actual_baselines(patient):
    run = run_for(patient)
    assert run["models"]["no_change"]["lesions_ml"]["L1"] == 6
    assert run["models"]["linear"]["lesions_ml"]["L1"] == 8
    assert run["models"]["exponential"]["lesions_ml"]["L1"] == 9
    assert run["models"]["linear"]["uncertainty"] is None
    assert run["models"]["linear"]["total_ml"] == 10.1


def test_horizon_is_relative_to_cutoff_not_last_scan(patient):
    spec = ExperimentSpec(cutoff_day=100, horizon_days=90)
    run = forecast(snapshot(patient, 100), spec)
    assert run["target_day"] == 190
    assert run["models"]["linear"]["lesions_ml"]["L1"] == pytest.approx(8.22222222)


def test_missing_observation_not_zero(patient):
    data = patient.model_dump(mode="json")
    data["studies"][1]["lesions"] = data["studies"][1]["lesions"][:1]
    run = run_for(Patient.model_validate(data))
    assert "L2" in run["models"]["linear"]["abstentions"]
    assert run["models"]["linear"]["total_ml"] is None


def test_unverified_correspondence_abstains(patient):
    changed = mutate(patient, lambda d: d["studies"][1]["lesions"][0].update(correspondence="unverified"))
    run = run_for(changed)
    assert "L1" not in run["models"]["no_change"]["lesions_ml"]
    assert "identity" in run["models"]["linear"]["abstentions"]["L1"]


def test_single_study_only_allows_no_change(patient):
    spec = ExperimentSpec(cutoff_day=0)
    run = forecast(snapshot(patient, 0), spec)
    assert run["models"]["no_change"]["lesions_ml"]
    assert not run["models"]["linear"]["lesions_ml"]


def test_partial_annotations_do_not_produce_complete_burden(patient):
    changed = mutate(patient, lambda d: d["studies"][1].update(annotation_scope="partial"))
    assert run_for(changed)["models"]["linear"]["total_ml"] is None


def test_evaluation_reports_errors_without_mutating_run(patient):
    run = run_for(patient)
    original = copy.deepcopy(run)
    result = evaluate(run, patient)
    assert result["scores"]["linear"]["lesions"]["L1"]["absolute_error_ml"] == 1
    assert result["scores"]["linear"]["total_absolute_error_ml"] == pytest.approx(1.7)
    assert run == original


def test_new_lesions_are_in_total_error():
    p = demo_patients()["SYN-002"]
    result = evaluate(run_for(p, organ="kidney"), p)
    assert result["new_observed_tracks"] == ["L2"]
    assert result["scores"]["no_change"]["actual_total_ml"] == pytest.approx(4.6)
    assert result["scores"]["no_change"]["total_absolute_error_ml"] == pytest.approx(2.4)


def test_missing_truth_is_not_implicit_disappearance(patient):
    data = patient.model_dump(mode="json")
    data["studies"][2]["lesions"] = data["studies"][2]["lesions"][:1]
    data["studies"][2]["annotation_scope"] = "partial"
    p = Patient.model_validate(data)
    result = evaluate(run_for(p), p)
    assert result["scores"]["linear"]["lesions"]["L2"]["actual_ml"] is None
    assert result["scores"]["linear"]["actual_total_ml"] is None


def test_wrong_patient_refused(patient):
    with pytest.raises(ValueError, match="Wrong patient"):
        evaluate(run_for(patient), demo_patients()["SYN-002"])


def test_changed_inputs_refused(patient):
    run = run_for(patient)
    changed = mutate(patient, lambda d: d["studies"][0]["lesions"][0].update(volume_ml=9))
    with pytest.raises(ValueError, match="changed after sealing"):
        evaluate(run, changed)


def test_no_target_refused(patient):
    with pytest.raises(ValueError, match="predeclared"):
        evaluate(run_for(patient, horizon_days=80), patient)


def test_declared_tolerance_and_offset_reported(patient):
    result = evaluate(run_for(patient, horizon_days=80, tolerance_days=10), patient)
    assert result["horizon_offset_days"] == 10


def test_artifact_tamper_detected(patient):
    run = run_for(patient)
    run["models"]["linear"]["lesions_ml"]["L1"] = 2
    with pytest.raises(ValueError, match="integrity"):
        verify_run(run)


def test_store_seals_before_reveal_and_survives_restart(patient, tmp_path):
    path = tmp_path / "runs.sqlite3"
    store = ExperimentStore(path)
    with pytest.raises(KeyError):
        store.get("not-sealed")
    run = run_for(patient)
    run_id = store.seal(run)
    assert ExperimentStore(path).get(run_id) == run
    result = evaluate(run, patient)
    assert store.record_evaluation(run_id, result) == store.record_evaluation(run_id, result)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM evaluations").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM experiments")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE experiments SET artifact='{}'")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 0])
def test_bad_present_volume_refused(patient, bad):
    with pytest.raises(ValidationError):
        mutate(patient, lambda d: d["studies"][0]["lesions"][0].update(volume_ml=bad))


def test_duplicate_scan_dates_refused(patient):
    with pytest.raises(ValidationError, match="one study"):
        mutate(patient, lambda d: d["studies"][1].update(acquired_day=0))


def test_future_snapshot_rejected(patient):
    with pytest.raises(ValidationError, match="Future study"):
        Snapshot(patient_id=patient.patient_id, source_revision="test", synthetic=True,
                 cutoff_day=0, studies=patient.studies, events=())


def test_invalid_clock_order_refused(patient):
    with pytest.raises(ValidationError):
        mutate(patient, lambda d: d["studies"][1].update(available_day=89))


def test_uncovered_organ_refused(patient):
    with pytest.raises(ValidationError):
        mutate(patient, lambda d: d["studies"][0].update(coverage=[]))


def test_identity_cannot_change_organ(patient):
    data = patient.model_dump(mode="json")
    data["studies"][1]["coverage"].append("kidney")
    data["studies"][1]["lesions"][0]["organ"] = "kidney"
    with pytest.raises(ValidationError, match="change organ"):
        Patient.model_validate(data)


def test_unknown_is_not_zero(patient):
    with pytest.raises(ValidationError, match="unknown"):
        mutate(patient, lambda d: d["studies"][0]["lesions"][0].update(state="not_assessed", volume_ml=0))


def test_deterministic_digest(patient):
    assert digest(snapshot(patient, 90)) == digest(snapshot(patient, 90))
