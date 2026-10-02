import pytest
from fastapi.testclient import TestClient

from cancerlab.api import create_app

HEADERS = {"X-Cancerlab-Request": "local-research"}
BODY = {"patient_id": "SYN-001", "spec": {"cutoff_day": 90, "horizon_days": 90, "organ": "liver"}}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "experiments.sqlite3")) as client:
        yield client


def test_health_and_home(client):
    assert client.get("/api/health").json()["synthetic_only"]
    response = client.get("/")
    assert response.status_code == 200
    assert "Observe. Predict. Verify." in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_patient_selector_does_not_expose_future_summary(client):
    assert client.get("/api/patients").json()[0] == {"patient_id": "SYN-001", "synthetic": True}


def test_snapshot_requires_explicit_cutoff(client):
    assert client.get("/api/patients/SYN-001/snapshot").status_code == 422


def test_snapshot_does_not_ship_hidden_outcomes(client):
    response = client.get("/api/patients/SYN-001/snapshot?cutoff_day=90")
    assert response.status_code == 200
    assert [s["acquired_day"] for s in response.json()["studies"]] == [0, 90]
    assert "HELD-OUT" not in response.text
    assert "SYN-001-180" not in response.text


def test_end_to_end_seal_reveal_export(client):
    response = client.post("/api/experiments", json=BODY, headers=HEADERS)
    assert response.status_code == 201
    run = response.json()
    assert "HELD-OUT" not in response.text
    assert "truth_study" not in response.text
    assert client.get(f"/api/experiments/{run['id']}").json() == run
    export = client.get(f"/api/experiments/{run['id']}/export")
    assert export.json() == run["artifact"]
    assert "attachment" in export.headers["Content-Disposition"]
    result = client.post(f"/api/experiments/{run['id']}/reveal", json={}, headers=HEADERS)
    assert result.status_code == 200
    assert result.json()["evaluation"]["actual_day"] == 180
    again = client.post(f"/api/experiments/{run['id']}/reveal", json={}, headers=HEADERS)
    assert result.json()["evaluation_id"] == again.json()["evaluation_id"]


def test_reveal_before_seal_refused(client):
    assert client.post("/api/experiments/missing/reveal", json={}, headers=HEADERS).status_code == 404


def test_cross_origin_and_simple_form_writes_refused(client):
    assert client.post("/api/experiments", json=BODY).status_code == 403
    assert client.post("/api/experiments", json=BODY,
                       headers={**HEADERS, "Origin": "https://untrusted.example"}).status_code == 403


def test_unknown_patient_and_wrong_organ(client):
    assert client.get("/api/patients/unknown/snapshot?cutoff_day=90").status_code == 404
    response = client.post("/api/experiments", json={**BODY, "spec": {**BODY["spec"], "organ": "spleen"}}, headers=HEADERS)
    assert response.status_code == 422


@pytest.mark.parametrize("horizon", [0, -1, 731, 90.5])
def test_bad_horizon(client, horizon):
    response = client.post("/api/experiments", json={**BODY, "spec": {**BODY["spec"], "horizon_days": horizon}}, headers=HEADERS)
    assert response.status_code == 422


def test_no_matching_followup_is_reported(client):
    response = client.post("/api/experiments", json={**BODY, "spec": {**BODY["spec"], "horizon_days": 80}}, headers=HEADERS)
    run_id = response.json()["id"]
    assert client.post(f"/api/experiments/{run_id}/reveal", json={}, headers=HEADERS).status_code == 409


def test_host_boundary_and_no_cors(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert "access-control-allow-origin" not in client.get("/api/health").headers


def test_schema_and_static_files(client):
    assert client.get("/api/schemas/patient").json()["additionalProperties"] is False
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/scene.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/../../pyproject.toml").status_code == 404
