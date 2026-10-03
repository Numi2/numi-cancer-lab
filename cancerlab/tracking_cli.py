"""Local alignment/review commands. No new database, downloads or hosted execution."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Patient
from .registration import RegistrationRequest, register
from .tracking import CorrespondenceReview, MatchOptions, propose_matches, review_manifest

COMMANDS = {'register', 'match', 'review-tracks', 'registration-schema', 'track-review-schema'}


def configure(commands):
    for name in ('register', 'match', 'review-tracks'):
        cmd = commands.add_parser(name, help={'register': 'Fit a reviewed moving-to-fixed rigid alignment',
            'match': 'Propose, but never assign, lesion correspondences',
            'review-tracks': 'Write a newly reviewed import manifest and receipt'}[name])
        cmd.add_argument('--patient', type=Path, required=True, help='One existing canonical patient JSON file')
        cmd.add_argument('--out', type=Path, required=True, help='New JSON file; new directory for review-tracks')
        if name == 'register':
            cmd.add_argument('--request', type=Path, required=True)
        elif name == 'match':
            cmd.add_argument('--registration', type=Path, required=True)
            cmd.add_argument('--max-distance-mm', type=float, default=20)
            cmd.add_argument('--ambiguity-margin-mm', type=float, default=3)
        else:
            cmd.add_argument('--manifest', type=Path, required=True)
            cmd.add_argument('--proposal', type=Path, required=True)
            cmd.add_argument('--review', type=Path, required=True)
    commands.add_parser('registration-schema', help='Print reviewed alignment request JSON Schema')
    commands.add_parser('track-review-schema', help='Print explicit correspondence review JSON Schema')


def _read(path: Path) -> dict:
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Input exceeds the local review JSON size limit')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def _write_new(path: Path, value: dict):
    content = json.dumps(value, indent=2, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(content + '\n')


def run(args):
    if args.command in {'registration-schema', 'track-review-schema'}:
        model = RegistrationRequest if args.command == 'registration-schema' else CorrespondenceReview
        print(json.dumps(model.model_json_schema(), indent=2))
        return
    if args.out.exists():
        raise ValueError('Output already exists; no review artifacts overwritten')
    patient = Patient.model_validate(_read(args.patient))
    if args.command == 'register':
        result = register(patient, RegistrationRequest.model_validate(_read(args.request)))
        _write_new(args.out, result)
        print(json.dumps({'artifact_sha256': result['artifact_sha256'], 'fit': result['fit'], 'check': result['check']}))
    elif args.command == 'match':
        result = propose_matches(patient, _read(args.registration), MatchOptions(
            max_distance_mm=args.max_distance_mm, ambiguity_margin_mm=args.ambiguity_margin_mm))
        _write_new(args.out, result)
        print(json.dumps({'artifact_sha256': result['artifact_sha256'], 'candidates': len(result['candidates']),
                          'ambiguous': sum(e['status'] == 'ambiguous_candidate' for e in result['candidates'])}))
    elif args.command == 'review-tracks':
        from .cancerverse import ImportManifest
        manifest, receipt = review_manifest(patient, ImportManifest.model_validate(_read(args.manifest)),
            _read(args.proposal), CorrespondenceReview.model_validate(_read(args.review)))
        args.out.mkdir(parents=True, mode=0o700)
        _write_new(args.out/'manifest.json', manifest.model_dump(mode='json'))
        _write_new(args.out/'receipt.json', receipt)
        print('Wrote reviewed manifest and receipt. Re-import into a new local patient directory.')
