"""Local verification only. Never installs dependencies or invokes hosted jobs."""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', action='store_true', help='Also run the local offline browser/API smoke test')
    args = parser.parse_args()
    subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix='cancerlab-check-') as tmp:
        for organ in ['liver', 'kidney']:
            subprocess.run([sys.executable, '-m', 'cancerlab', 'benchmark', '--organ', organ,
                            '--out', str(Path(tmp) / f'{organ}.json')], cwd=ROOT, check=True)
    if args.browser:
        subprocess.run([sys.executable, 'scripts/browser_smoke.py', '--offline'], cwd=ROOT, check=True)
    print('Local checks completed. No hosted CI jobs were requested.')


if __name__ == '__main__':
    main()
