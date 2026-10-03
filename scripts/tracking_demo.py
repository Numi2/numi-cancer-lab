"""Run registration -> suggestions -> simulated review on explicitly synthetic records."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cancerlab.cli import main as cancerlab
from cancerlab.models import Evidence, Lesion, Patient, Study, digest
from cancerlab.tracking_cli import _write_new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    out = parser.parse_args().out
    out.mkdir(parents=True, mode=0o700)  # intentionally refuses an existing directory
    studies, manifest_studies = [], []
    for index, coordinates in enumerate(((0.,), (100.2, 150.)), 1):
        case = f'CV_{index:08}'
        lesions = [Lesion(lesion_id='L1' if index == 1 else f'{case}.liver.c{j}', organ='liver',
            volume_ml=1 if index == 1 else 1.2, centroid_ras_mm=(x, 0, 0),
            correspondence='confirmed' if index == 1 else 'unverified',
            evidence=Evidence(source=f'CancerVerse/{case}/segmentations/liver_lesion.nii.gz#component={j}',
                method='mask-volume', sha256=digest(f'SYNTHETIC MASK PLACEHOLDER:{case}')))
            for j, x in enumerate(coordinates, 1)]
        day = (index-1)*90
        studies.append(Study(study_id=case, acquired_day=day, available_day=day, coverage=('liver',),
            annotation_scope='complete', lesions=tuple(lesions), scan_sha256=digest(f'SYNTHETIC CT PLACEHOLDER:{case}')))
        manifest_studies.append(dict(case_id=case, acquired_day=day, available_day=day, coverage=['liver'],
            annotation_scope='complete', masks=[dict(organ='liver', reviews=[dict(component=1, lesion_id='L1',
                reviewer_id='synthetic-fixture', available_day=0)] if index == 1 else [])]))
    patient = Patient(patient_id='SYN-REG', source='synthetic registration fixture',
        source_revision='synthetic-v1', synthetic=True, studies=tuple(studies))
    request = dict(patient_id=patient.patient_id, fixed_study_id=studies[0].study_id,
        moving_study_id=studies[1].study_id, organ='liver', reviewer_id='synthetic-fixture', available_day=90,
        max_error_mm=1, landmarks=[dict(landmark_id=f'fit-{i}', fixed_ras_mm=p, moving_ras_mm=[p[0]+100,p[1],p[2]])
        for i,p in enumerate([[0,0,0],[20,0,0],[0,20,0],[0,0,20]])],
        check_landmarks=[dict(landmark_id='independent-check', fixed_ras_mm=[10,10,10], moving_ras_mm=[110,10,10])])
    _write_new(out/'patient.json', patient.model_dump(mode='json'))
    _write_new(out/'request.json', request)
    _write_new(out/'manifest.json', dict(source_revision='synthetic-v1', patients=[dict(patient_id='SYN-REG', studies=manifest_studies)]))
    cancerlab(['register', '--patient', str(out/'patient.json'), '--request', str(out/'request.json'), '--out', str(out/'registration.json')])
    cancerlab(['match', '--patient', str(out/'patient.json'), '--registration', str(out/'registration.json'), '--out', str(out/'proposal.json')])
    proposal = json.loads((out/'proposal.json').read_text())
    assert len(proposal['candidates']) == 1 and len(proposal['unmatched_moving']) == 1
    _write_new(out/'review.json', dict(proposal_sha256=proposal['artifact_sha256'], reviewer_id='synthetic-fixture',
        available_day=100, links=[dict(fixed_lesion_id='L1', moving_lesion_id='CV_00000002.liver.c1',
                                     reason='Known synthetic correspondence; not a real anatomical review')]))
    cancerlab(['review-tracks', '--patient', str(out/'patient.json'), '--manifest', str(out/'manifest.json'),
        '--proposal', str(out/'proposal.json'), '--review', str(out/'review.json'), '--out', str(out/'reviewed')])
    print('SYNTHETIC ONLY: known 100 mm motion, one candidate, one unmatched observation; no images or patient data loaded.')


if __name__ == '__main__':
    main()
