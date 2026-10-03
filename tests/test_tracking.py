import copy
import hashlib

import pytest

from cancerlab import cancerverse as cv
from cancerlab.models import Evidence, Lesion, Patient, Study, digest, snapshot
from cancerlab.registration import RegistrationRequest, register
from cancerlab.tracking import CorrespondenceReview, MatchOptions, propose_matches, review_manifest


def fixture(offsets=(0, 40), shifted=(0.2, 40.1), fixed_confirmed=True):
    """Entirely fabricated mask observations; no patient data or imaging I/O."""
    studies, manifest_studies = [], []
    for index, positions in enumerate((offsets, shifted), 1):
        case = f'CV_{index:08}'
        lesions, reviews = [], []
        for component, x in enumerate(positions, 1):
            confirmed = index == 1 and fixed_confirmed
            track = f'L{component}' if confirmed else f'{case}.liver.c{component}'
            lesions.append(Lesion(lesion_id=track, organ='liver', volume_ml=component,
                centroid_ras_mm=(x + (100 if index == 2 else 0), 0, 0),
                correspondence='confirmed' if confirmed else 'unverified',
                evidence=Evidence(source=f'CancerVerse/{case}/segmentations/liver_lesion.nii.gz#component={component}',
                                  method='mask-volume', sha256=hashlib.sha256(f'SYNTHETIC MASK:{case}'.encode()).hexdigest())))
            if confirmed:
                reviews.append(dict(component=component, lesion_id=track, reviewer_id='fixture', available_day=0))
        studies.append(Study(study_id=case, acquired_day=(index - 1) * 90, available_day=(index - 1) * 90,
                             coverage=('liver',), annotation_scope='complete', lesions=tuple(lesions), scan_sha256=hashlib.sha256(f'SYNTHETIC:{case}'.encode()).hexdigest()))
        manifest_studies.append(dict(case_id=case, acquired_day=(index-1)*90, available_day=(index-1)*90,
            coverage=['liver'], annotation_scope='complete', masks=[dict(organ='liver', reviews=reviews)]))
    patient = Patient(patient_id='SYN-TRACK', synthetic=True, source='synthetic tracking fixture',
                      source_revision='synthetic-v1', studies=tuple(studies))
    manifest = cv.ImportManifest(source_revision=patient.source_revision,
                                patients=[dict(patient_id=patient.patient_id, studies=manifest_studies)])
    spec = RegistrationRequest(patient_id=patient.patient_id, fixed_study_id=studies[0].study_id,
        moving_study_id=studies[1].study_id, reviewer_id='fixture', available_day=90, organ='liver', max_error_mm=1,
        landmarks=[dict(landmark_id=str(i), fixed_ras_mm=p, moving_ras_mm=[p[0]+100, p[1], p[2]])
                   for i, p in enumerate([[0,0,0], [0,20,0], [0,0,20], [20,0,0]])])
    return patient, manifest, register(patient, spec)


def decision(proposal, **changes):
    raw = dict(proposal_sha256=proposal['artifact_sha256'], reviewer_id='reviewer-test', available_day=100,
               links=[dict(fixed_lesion_id='L1', moving_lesion_id='CV_00000002.liver.c1', reason='Synthetic test review')])
    raw.update(changes)
    return CorrespondenceReview.model_validate(raw)


def test_alignment_recovers_candidates_without_assigning_identity():
    patient, _, registration = fixture()
    before = digest(patient)
    proposal = propose_matches(patient, registration)
    assert len(proposal['candidates']) == 2
    assert all(e['status'] == 'separated_candidate' for e in proposal['candidates'])
    assert proposal['candidates'][0]['distance_mm'] == pytest.approx(.2)
    assert digest(patient) == before
    assert all(m.correspondence == 'unverified' for m in patient.studies[1].lesions)


def test_close_candidates_remain_ambiguous():
    patient, _, registration = fixture(offsets=(0, 2), shifted=(.5, 1.5))
    result = propose_matches(patient, registration)
    assert len(result['candidates']) == 4
    assert all(e['status'] == 'ambiguous_candidate' for e in result['candidates'])


def test_ambiguity_considers_neighbour_outside_search_radius():
    patient, _, registration = fixture(offsets=(0,), shifted=(19,21))
    result = propose_matches(patient, registration)
    assert len(result['candidates']) == 1
    assert result['candidates'][0]['status'] == 'ambiguous_candidate'
    assert result['unmatched_moving'] == ['CV_00000002.liver.c2']


def test_unmatched_is_not_absence_or_new_disease():
    patient, _, registration = fixture(offsets=(0,), shifted=(100,))
    result = propose_matches(patient, registration)
    assert not result['candidates']
    assert result['unmatched_fixed'] == ['L1']
    assert result['unmatched_moving'] == ['CV_00000002.liver.c1']


def test_missing_centroid_and_empty_sets():
    patient, _, registration = fixture(offsets=(), shifted=())
    assert propose_matches(patient, registration)['candidates'] == []
    patient, _, registration = fixture()
    moving = patient.studies[1]
    changed = moving.model_copy(update={'lesions': tuple(m.model_copy(update={'centroid_ras_mm': None}) for m in moving.lesions)})
    patient = patient.model_copy(update={'studies': (patient.studies[0], changed)})
    registration = register(patient, RegistrationRequest.model_validate(registration['request']))
    result = propose_matches(patient, registration)
    assert not result['candidates'] and len(result['excluded_moving']) == 2


def test_review_updates_only_selected_moving_manifest_component():
    patient, manifest, registration = fixture()
    proposal = propose_matches(patient, registration)
    original = digest(manifest), digest(patient)
    updated, receipt = review_manifest(patient, manifest, proposal, decision(proposal))
    assert updated.patients[0].studies[0].masks[0].reviews == manifest.patients[0].studies[0].masks[0].reviews
    assert updated.patients[0].studies[0].expected_scan_sha256 == patient.studies[0].scan_sha256
    reviews = updated.patients[0].studies[1].masks[0].reviews
    assert len(reviews) == 1 and reviews[0].lesion_id == 'L1' and reviews[0].available_day == 100
    assert original == (digest(manifest), digest(patient))
    assert receipt['output_manifest_sha256'] == digest(updated)


def test_split_or_merge_review_refused():
    patient, _, registration = fixture()
    proposal = propose_matches(patient, registration)
    link = decision(proposal).links[0].model_dump()
    with pytest.raises(ValueError, match='one-to-one'):
        decision(proposal, links=[link, link])


@pytest.mark.parametrize('changes,match', [({'available_day':89}, 'before'), ({'proposal_sha256':'0'*64}, 'different proposal')])
def test_review_backdating_and_wrong_proposal_refused(changes, match):
    patient, manifest, registration = fixture()
    proposal = propose_matches(patient, registration)
    with pytest.raises(ValueError, match=match):
        review_manifest(patient, manifest, proposal, decision(proposal, **changes))


def test_fixed_identity_must_preexist():
    patient, manifest, registration = fixture(fixed_confirmed=False)
    proposal = propose_matches(patient, registration)
    links=[dict(fixed_lesion_id='CV_00000001.liver.c1', moving_lesion_id='CV_00000002.liver.c1', reason='test')]
    with pytest.raises(ValueError, match='earlier track'):
        review_manifest(patient, manifest, proposal, decision(proposal, links=links))


def test_fabricated_candidate_and_changed_manifest_refused():
    patient, manifest, registration = fixture()
    proposal = propose_matches(patient, registration)
    with pytest.raises(ValueError, match='not a candidate'):
        review_manifest(patient, manifest, proposal, decision(proposal, links=[dict(
            fixed_lesion_id='L1', moving_lesion_id='CV_00000002.liver.c2', reason='wrong pair')]))
    bad = copy.deepcopy(proposal); bad['candidates'][0]['distance_mm'] = 500
    bad['artifact_sha256'] = digest({k:v for k,v in bad.items() if k != 'artifact_sha256'})
    with pytest.raises(ValueError, match='reproduces'):
        review_manifest(patient, manifest, bad, decision(bad))
    with pytest.raises(ValueError, match='revision'):
        review_manifest(patient, manifest.model_copy(update={'source_revision':'changed'}), proposal, decision(proposal))


def test_review_reimport_respects_delayed_availability(tmp_path, monkeypatch):
    patient, manifest, registration = fixture()
    proposal = propose_matches(patient, registration)
    updated, _ = review_manifest(patient, manifest, proposal, decision(proposal))
    for study in patient.studies:
        folder = tmp_path/'CancerVerse'/study.study_id
        (folder/'segmentations').mkdir(parents=True)
        (folder/'ct.nii.gz').write_bytes(f'SYNTHETIC:{study.study_id}'.encode())
        (folder/'segmentations/liver_lesion.nii.gz').write_bytes(f'SYNTHETIC MASK:{study.study_id}'.encode())
    monkeypatch.setattr(cv, 'load_nifti', lambda path: object())
    monkeypatch.setattr(cv, 'measure_nifti', lambda path, ct: [dict(component=i, volume_ml=i, centroid_ras_mm=(i,0,0)) for i in (1,2)])
    cohort, _ = cv.import_records(tmp_path, updated, acknowledge_license=True)
    revised = cohort[patient.patient_id]
    assert len(snapshot(revised,99).studies) == 1
    assert len(snapshot(revised,100).studies) == 2
    assert revised.studies[1].lesions[0].lesion_id == 'L1'
    assert revised.studies[1].lesions[1].correspondence == 'unverified'


def test_candidate_resource_limits_fail_instead_of_truncating(monkeypatch):
    import cancerlab.tracking as tracking
    patient, _, registration = fixture(offsets=(0,2), shifted=(1,3))
    monkeypatch.setattr(tracking, 'MAX_EDGES', 1)
    with pytest.raises(ValueError, match='Too many candidate edges'):
        propose_matches(patient, registration)


def test_review_cannot_replace_existing_decision():
    patient, manifest, registration = fixture()
    moving = patient.studies[1]
    later = moving.lesions[0].model_copy(update={'correspondence':'confirmed'})
    patient = patient.model_copy(update={'studies': (patient.studies[0], moving.model_copy(update={
        'lesions': (later, moving.lesions[1])}))})
    registration = register(patient, RegistrationRequest.model_validate(registration['request']))
    proposal = propose_matches(patient, registration)
    with pytest.raises(ValueError, match='already reviewed'):
        review_manifest(patient, manifest, proposal, decision(proposal))


def test_manifest_binding_cannot_be_silently_replaced():
    patient, manifest, registration = fixture()
    raw = manifest.model_dump(mode='json')
    raw['patients'][0]['studies'][1]['expected_scan_sha256'] = '0'*64
    proposal = propose_matches(patient, registration)
    with pytest.raises(ValueError, match='binding differs'):
        review_manifest(patient, cv.ImportManifest.model_validate(raw), proposal, decision(proposal))
