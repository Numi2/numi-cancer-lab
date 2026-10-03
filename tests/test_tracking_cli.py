import json

import pytest

from cancerlab.cli import main
from cancerlab.tracking import propose_matches
from test_tracking import fixture, decision


def write(path, value):
    path.write_text(json.dumps(value)); return str(path)


def test_local_command_workflow_and_no_overwrite(tmp_path, capsys):
    patient, manifest, registration = fixture()
    p = write(tmp_path/'patient.json', patient.model_dump(mode='json'))
    req = write(tmp_path/'request.json', registration['request'])
    reg, prop, out = tmp_path/'registration.json', tmp_path/'proposal.json', tmp_path/'reviewed'
    main(['register', '--patient', p, '--request', req, '--out', str(reg)])
    main(['match', '--patient', p, '--registration', str(reg), '--out', str(prop)])
    proposal = json.loads(prop.read_text())
    assert len(proposal['candidates']) == 2
    original = reg.read_bytes()
    with pytest.raises(SystemExit):
        main(['register', '--patient', p, '--request', req, '--out', str(reg)])
    assert reg.read_bytes() == original
    args = ['review-tracks', '--patient', p, '--manifest', write(tmp_path/'manifest.json', manifest.model_dump(mode='json')),
            '--proposal', str(prop), '--review', write(tmp_path/'review.json', decision(proposal).model_dump(mode='json')),
            '--out', str(out)]
    main(args)
    assert (out/'manifest.json').is_file() and (out/'receipt.json').is_file()
    assert (out/'receipt.json').stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemExit):
        main(args)


def test_schemas_and_invalid_inputs(tmp_path, capsys):
    for command, title in [('registration-schema','RegistrationRequest'), ('track-review-schema','CorrespondenceReview')]:
        main([command]); assert json.loads(capsys.readouterr().out)['title'] == title
    with pytest.raises(SystemExit):
        main(['register', '--patient', write(tmp_path/'bad.json', []), '--request', 'missing', '--out', str(tmp_path/'out')])
    assert not (tmp_path/'out').exists()
