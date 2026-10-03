import copy

import numpy as np
import pytest

from cancerlab.demo import demo_patients
from cancerlab.models import digest
from cancerlab.registration import RegistrationRequest, fit_rigid, register, rigid_matrix, transform_points, verify_registration


def request(**changes):
    moving = np.array([[0, 0, 0], [20, 0, 0], [0, 30, 0], [0, 0, 40]], dtype=float)
    transform = np.array([[0, -1, 0, 11], [1, 0, 0, -7], [0, 0, 1, 3], [0, 0, 0, 1.]])
    fixed = transform_points(moving, transform)
    patient = demo_patients()['SYN-001']
    raw = dict(patient_id=patient.patient_id, fixed_study_id=patient.studies[0].study_id,
               moving_study_id=patient.studies[1].study_id, organ='liver', reviewer_id='test-reviewer',
               available_day=90, max_error_mm=1,
               landmarks=[dict(landmark_id=f'p{i}', fixed_ras_mm=f.tolist(), moving_ras_mm=m.tolist())
                          for i, (f, m) in enumerate(zip(fixed, moving))])
    raw.update(changes)
    return patient, RegistrationRequest.model_validate(raw), transform


def test_recovers_known_transform_and_preserves_distances():
    patient, spec, truth = request()
    result = register(patient, spec)
    assert np.allclose(result['matrix'], truth)
    assert result['fit']['max_error_mm'] < 1e-10
    assert result['check']['rmse_mm'] is None
    assert verify_registration(patient, result) == spec
    assert patient == demo_patients()['SYN-001']


def test_independent_check_not_used_for_fit():
    patient, spec, truth = request(check_landmarks=[dict(landmark_id='check', fixed_ras_mm=[1, 3, 13], moving_ras_mm=[10, 10, 10])])
    result = register(patient, spec)
    assert result['check']['count'] == 1
    assert result['check']['rmse_mm'] < 1e-10
    assert np.allclose(result['matrix'], truth)


def test_bad_independent_check_refused():
    patient, spec, _ = request(check_landmarks=[dict(landmark_id='check', fixed_ras_mm=[100, 100, 100], moving_ras_mm=[10, 10, 10])])
    with pytest.raises(ValueError, match='Independent check'):
        register(patient, spec)


@pytest.mark.parametrize('changes,match', [
    ({'available_day': 89}, 'before'), ({'patient_id': 'other'}, 'different patient'),
    ({'fixed_study_id': 'missing'}, 'not found'), ({'organ': 'bladder'}, 'cover')])
def test_sources_and_availability(changes, match):
    patient, spec, _ = request(**changes)
    with pytest.raises(ValueError, match=match):
        register(patient, spec)


def test_changed_evidence_and_tampering_refused():
    patient, spec, _ = request()
    result = register(patient, spec)
    changed = patient.model_copy(update={'source_revision': 'different'})
    with pytest.raises(ValueError, match='source'):
        verify_registration(changed, result)
    result['matrix'][0][3] += 1
    with pytest.raises(ValueError, match='integrity'):
        verify_registration(patient, result)
    result['artifact_sha256'] = digest({k: v for k, v in result.items() if k != 'artifact_sha256'})
    with pytest.raises(ValueError, match='reproduce'):
        verify_registration(patient, result)


@pytest.mark.parametrize('matrix', [np.diag([2, 1, 1, 1]), np.diag([-1, 1, 1, 1]), np.zeros((4, 4)), np.eye(3)])
def test_not_rigid_refused(matrix):
    with pytest.raises(ValueError):
        rigid_matrix(matrix)


@pytest.mark.parametrize('points', [[[0, 0, 0]] * 3, [[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 0, 0], [1, 0, 0], [2, 1e-10, 0]]])
def test_degenerate_landmarks_refused(points):
    with pytest.raises(ValueError, match='collinear'):
        fit_rigid(points, points)


def test_non_collinear_planar_points_allowed():
    points = [[0, 0, 0], [10, 0, 0], [0, 10, 0]]
    assert np.allclose(fit_rigid(points, points), np.eye(4))


def test_noisy_landmark_tolerance_and_duplicate_checks():
    patient, spec, _ = request()
    raw = spec.model_dump(mode='json')
    raw['landmarks'][0]['fixed_ras_mm'][0] += 10
    with pytest.raises(ValueError, match='Fitted landmark'):
        register(patient, RegistrationRequest.model_validate(raw))
    raw = spec.model_dump(mode='json')
    raw['check_landmarks'] = [copy.deepcopy(raw['landmarks'][0])]
    with pytest.raises(ValueError, match='unique'):
        RegistrationRequest.model_validate(raw)
    raw['check_landmarks'][0]['landmark_id'] = 'new-name-same-position'
    with pytest.raises(ValueError, match='distinct'):
        RegistrationRequest.model_validate(raw)


def test_empty_point_transform_and_nonfinite_rejection():
    assert transform_points(np.empty((0, 3)), np.eye(4)).shape == (0, 3)
    with pytest.raises(ValueError):
        transform_points([[np.nan, 0, 0]], np.eye(4))


def test_requires_ct_hashes_for_real_records():
    patient, spec, _ = request()
    with pytest.raises(ValueError, match='CT hashes'):
        register(patient.model_copy(update={'synthetic': False, 'studies': tuple(
            s.model_copy(update={'scan_sha256': None}) for s in patient.studies)}), spec)
