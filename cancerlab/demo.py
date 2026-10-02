"""Deterministic fictional cases. No CancerVerse records or patient data."""
from .models import ClinicalEvent, Evidence, Lesion, Patient, Study, digest


def demo_patients() -> dict[str, Patient]:
    patients = {}
    for n, organ in enumerate(("liver", "kidney", "pancreas"), start=1):
        studies = []
        for i, day in enumerate((0, 90, 180, 270)):
            # Distinct trajectories deliberately make simple forecasts fail differently.
            volumes = ((4, 6, 7, 5), (2, 2.2, 3.8, 5.2), (3, 4.5, 6.8, 9))[n - 1]
            lesions = [Lesion(lesion_id="L1", organ=organ, volume_ml=volumes[i],
                              centroid_ras_mm=(-40 + n * 25, 20, 15), correspondence="confirmed",
                              evidence=Evidence(source=f"synthetic:{n}:{day}:L1", method="synthetic",
                                                sha256=digest([n, day, "L1", volumes[i]])))]
            if n == 1:
                v = (1.5, 1.8, 1.4, 1.1)[i]
                lesions.append(Lesion(lesion_id="L2", organ=organ, volume_ml=v,
                                      centroid_ras_mm=(30, -15, -15), correspondence="confirmed",
                                      evidence=Evidence(source=f"synthetic:{n}:{day}:L2", method="synthetic",
                                                        sha256=digest([n, day, "L2", v]))))
            if n == 2 and i >= 2:
                lesions.append(Lesion(lesion_id="L2", organ=organ, volume_ml=0.8 + 0.3 * (i - 2),
                                      centroid_ras_mm=(-25, -10, -10), correspondence="confirmed",
                                      evidence=Evidence(source=f"synthetic:{n}:{day}:L2", method="synthetic",
                                                        sha256=digest([n, day, "new"]))))
            studies.append(Study(study_id=f"SYN-{n:03}-{day}", acquired_day=day, available_day=day,
                                 coverage=(organ,), annotation_scope="complete", lesions=tuple(lesions),
                                 scan_sha256=digest(["synthetic-scan", n, day])))
        events = (ClinicalEvent(event_id="E1", occurred_day=0, available_day=3, kind="report",
                               text="Fictional research case. Lesion measurements are generated, not patient observations.",
                               evidence=Evidence(source="synthetic:report", method="synthetic", sha256=digest([n, "report"]))),
                  ClinicalEvent(event_id="E2", occurred_day=170, available_day=185, kind="note",
                                text="HELD-OUT NOTE: this text must not appear in the day-90 model input.",
                                evidence=Evidence(source="synthetic:future-note", method="synthetic", sha256=digest([n, "future"]))))
        patient = Patient(patient_id=f"SYN-{n:03}", source="Numi synthetic demonstration",
                          source_revision="synthetic-v1", synthetic=True, studies=tuple(studies), events=events)
        patients[patient.patient_id] = patient
    return patients
