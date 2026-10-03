from cancerlab.cli import benchmark
from cancerlab.demo import demo_patients

def test_benchmark_reports_denominators_and_lesion_metrics():
    patients=demo_patients()
    result=benchmark(patients,90,90,"liver")
    assert result["cohort"]["input_patients"]==len(patients)
    assert result["cohort"]["eligible_patients"]+result["cohort"]["skipped_patients"]==len(patients)
    for method in ("no_change","linear","exponential"):
        row=result["summary"][method]
        assert row["eligible_patients"]==result["cohort"]["eligible_patients"]
        assert row["scored_patients_total_burden"]<=row["eligible_patients"]
        assert row["scored_lesions"]>=0
        if row["scored_lesions"]:
            assert row["pooled_lesion_mae_ml"] is not None

def test_benchmark_is_deterministic():
    patients=demo_patients()
    assert benchmark(patients,90,90,"liver")==benchmark(patients,90,90,"liver")
