from pathlib import Path


def test_no_hosted_ci_configuration():
    root = Path(__file__).resolve().parents[1]
    workflows = root / '.github/workflows'
    assert not list(workflows.glob('*.yml')) + list(workflows.glob('*.yaml')), 'Hosted CI is prohibited by the owner'
    for path in ['.gitlab-ci.yml', '.circleci/config.yml', 'azure-pipelines.yml', '.travis.yml']:
        assert not (root / path).exists(), 'Do not replace GitHub CI with another hosted CI service'
