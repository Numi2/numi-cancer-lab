import copy
import json

import pytest
from fastapi.testclient import TestClient

from cancerlab.api import create_app
from cancerlab.demo import demo_patients
from cancerlab.models import digest
from cancerlab.registration import RegistrationRequest, register
from cancerlab.tracking import propose_matches

HEADERS = {"X-Cancerlab-Request": "local-research"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=tmp_path / 'workspace.sqlite3')) as c:
        yield c


def seal(c, patient='SYN-001', cutoff=90):
    return c.post('/api/experiments', headers=HEADERS, json={
        'patient_id': patient, 'spec': {'cutoff_day': cutoff, 'horizon_days': 90, 'organ': 'liver'}
    }).json()['id']


def proposal():
    patient = demo_patients()['SYN-001']
    request = RegistrationRequest(patient_id=patient.patient_id, fixed_study_id='SYN-001-0',
        moving_study_id='SYN-001-90', organ='liver', reviewer_id='synthetic-review',
        available_day=90, max_error_mm=1, landmarks=[{'landmark_id': f'p{i}',
            'fixed_ras_mm': p, 'moving_ras_mm': p} for i, p in enumerate([(0,0,0),(30,0,0),(0,30,0)])])
    return propose_matches(patient, register(patient, request))


def payload():
    return {'patient_id': 'SYN-001', 'cutoff_day': 90, 'proposal_json': json.dumps(proposal())}


def test_history_is_patient_and_cutoff_scoped_and_paged(client):
    first = seal(client)
    second = seal(client)
    seal(client, cutoff=180)
    assert client.get('/api/patients/SYN-001/experiments').status_code == 422
    result = client.get('/api/patients/SYN-001/experiments?cutoff_day=90&limit=1').json()
    assert result['items'][0]['id'] == second
    assert result['next_offset'] == 1
    assert 'snapshot' not in result['items'][0]
    assert 'evaluation' not in result['items'][0]
    rest = client.get('/api/patients/SYN-001/experiments?cutoff_day=90&limit=1&offset=1').json()
    assert rest['items'][0]['id'] == first
    assert rest['next_offset'] is None
    assert client.get('/api/patients/SYN-002/experiments?cutoff_day=90').json()['items'] == []
    assert client.get('/api/patients/missing/experiments?cutoff_day=90').status_code == 404
    assert client.get('/api/patients/SYN-001/experiments?cutoff_day=90&limit=10000').status_code == 422


def test_resume_never_implicitly_reveals(client):
    run_id = seal(client)
    url = f'/api/experiments/{run_id}/evaluation'
    assert client.get(url).json() == {'evaluation': None}
    client.post(f'/api/experiments/{run_id}/reveal', json={}, headers=HEADERS)
    assert client.get(url).json()['evaluation']['actual_day'] == 180
    assert client.get('/api/patients/SYN-001/experiments?cutoff_day=90').json()['items'][0]['state'] == 'evaluated'
    assert client.get('/api/experiments/missing/evaluation').status_code == 404


def test_proposal_requires_local_boundary_and_explicit_cutoff(client):
    body = payload()
    assert client.post('/api/workspace/proposal', json=body).status_code == 403
    response = client.post('/api/workspace/proposal', json=body, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == json.loads(body['proposal_json'])
    assert client.post('/api/workspace/proposal', json={**body, 'cutoff_day':89}, headers=HEADERS).status_code == 422
    assert client.post('/api/workspace/proposal', json={**body, 'patient_id':'SYN-002'}, headers=HEADERS).status_code == 422
    changed = json.loads(body['proposal_json']); changed['candidates'][0]['distance_mm'] = 200
    body['proposal_json'] = json.dumps(changed)
    assert client.post('/api/workspace/proposal', json=body, headers=HEADERS).status_code == 422


def test_review_draft_is_explicit_and_never_mutates_patient(client):
    body = payload()
    edge = json.loads(body['proposal_json'])['candidates'][0]
    review = {'proposal_sha256':json.loads(body['proposal_json'])['artifact_sha256'], 'reviewer_id':'reviewer', 'available_day':90,
              'links':[{'fixed_lesion_id':edge['fixed_lesion_id'], 'moving_lesion_id':edge['moving_lesion_id'],
                        'reason':'Reviewed the synthetic correspondence.'}]}
    before = client.get('/api/patients/SYN-001/snapshot?cutoff_day=90').json()
    response = client.post('/api/workspace/review', json={**body,'review':review}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == review
    assert before == client.get('/api/patients/SYN-001/snapshot?cutoff_day=90').json()
    for day in (89,91):
        assert client.post('/api/workspace/review', json={**body,'review':{**review,'available_day':day}}, headers=HEADERS).status_code == 422
    for reason in ('', '  '):
        bad = copy.deepcopy(review); bad['links'][0]['reason'] = reason
        assert client.post('/api/workspace/review', json={**body,'review':bad}, headers=HEADERS).status_code == 422
    duplicate = {**review, 'links':review['links'] * 2}
    assert client.post('/api/workspace/review', json={**body,'review':duplicate}, headers=HEADERS).status_code == 422


@pytest.mark.parametrize('value', [None, [], {}, 'bad'])
def test_malformed_proposal_does_not_return_500(client, value):
    body = payload(); changed = json.loads(body['proposal_json']); changed['registration'] = value
    changed['artifact_sha256'] = digest({k:v for k,v in changed.items() if k!='artifact_sha256'})
    body['proposal_json'] = json.dumps(changed)
    assert client.post('/api/workspace/proposal', json=body, headers=HEADERS).status_code == 422


def test_review_api_keeps_original_number_serialization(client):
    body=payload()
    # The original raw JSON retains the float/int distinction used by the
    # existing artifact digest. Browser parsing must not rewrite the artifact.
    assert '0.0' in body['proposal_json']
    assert client.post('/api/workspace/proposal',json=body,headers=HEADERS).status_code==200
    body['proposal_json']=body['proposal_json'].replace('0.0','0')
    assert client.post('/api/workspace/proposal',json=body,headers=HEADERS).status_code==422


def test_review_size_and_json_type_validation(client):
    for raw in ('[]','null','{bad','x'*2_000_001):
        response=client.post('/api/workspace/proposal',json={
            'patient_id':'SYN-001','cutoff_day':90,'proposal_json':raw},headers=HEADERS)
        assert response.status_code==422
