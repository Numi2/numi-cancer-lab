"""Verify the real UI, either against a live server or an in-process offline API.

Run: python scripts/browser_smoke.py --offline --screenshots /tmp/cancerlab-ui
Live: start `python -m cancerlab serve`, then omit --offline.
Offline mode is component integration testing, not network/CSP verification.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        executable = shutil.which('chromium')
        launch = {'headless': True, 'args': ['--no-sandbox']}
        if executable:
            launch['executable_path'] = executable
        browser = pw.chromium.launch(**launch)
        page = browser.new_page(viewport={'width': 1440, 'height': 1150})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        if args.offline:
            from fastapi.testclient import TestClient
            from cancerlab.api import create_app
            client = TestClient(create_app(db_path=Path(tmp) / 'browser.sqlite3'))
            def request(data):
                response = client.request(data['method'], data['path'], headers=data['headers'], content=data['body'])
                return {'status': response.status_code, 'text': response.text}
            page.expose_function('localResearchAPI', request)
            web = ROOT / 'cancerlab/web'
            html = (web / 'index.html').read_text()
            html = html.replace('<link rel="stylesheet" href="/static/styles.css">', '<style>' + (web / 'styles.css').read_text() + '</style>')
            html = html.replace('<script type="module" src="/static/app.js"></script>', '')
            page.set_content(html)
            page.add_script_tag(content="""window.fetch=async(path,options={})=>{
              const r=await window.localResearchAPI({path,method:options.method||'GET',headers:options.headers||{},body:options.body||null});
              return new Response(r.text,{status:r.status,headers:{'Content-Type':'application/json'}});
            };""")
            source = (web / 'scene.js').read_text().replace('export class LesionScene', 'class LesionScene')
            source += '\n' + (web / 'app.js').read_text().replace("import {LesionScene} from './scene.js';", '')
            page.add_script_tag(content=source)
        else:
            page.goto(args.url, wait_until='networkidle')
        page.wait_for_function("document.getElementById('metric-studies').textContent==='2'")
        assert page.locator('#seal').is_enabled()
        assert not page.locator('#reveal').is_enabled()
        assert 'HELD-OUT' not in page.locator('#input-evidence').text_content()
        assert not page.locator('#scene-fallback').is_visible()
        renderer = page.locator('#scene').get_attribute('data-renderer')
        assert renderer in {'webgl2', 'canvas-projection'}
        page.click('#seal')
        page.wait_for_function("document.getElementById('metric-state').textContent==='Sealed'")
        page.click('#reveal')
        page.wait_for_function("document.getElementById('metric-state').textContent==='Evaluated'")
        assert page.locator('#scores .score').count() == 3
        assert page.locator('#truth-view').is_enabled()
        page.click('#truth-view')
        assert 'day 180' in page.locator('#scene-day').inner_text()
        if args.screenshots:
            args.screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.screenshots / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.locator('#patient').is_visible()
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        if args.screenshots:
            page.screenshot(path=str(args.screenshots / 'mobile.png'), full_page=True)
        page.select_option('#patient', 'SYN-002')
        page.wait_for_function("document.getElementById('organ').value==='kidney'")
        assert not page.locator('#reveal').is_enabled()
        page.click('#seal')
        page.wait_for_function("document.getElementById('metric-state').textContent==='Sealed'")
        page.click('#reveal')
        page.wait_for_function("document.getElementById('metric-state').textContent==='Evaluated'")
        assert '1 newly observed' in page.locator('#comparison-note').text_content()
        page.fill('#horizon', '80')
        assert not page.locator('#seal').is_enabled()
        page.click('#apply')
        page.wait_for_function("!document.getElementById('seal').disabled")
        page.click('#seal')
        page.wait_for_function("document.getElementById('metric-state').textContent==='Sealed'")
        page.click('#reveal')
        page.wait_for_selector('#error', state='visible')
        assert 'predeclared' in page.locator('#error').text_content()
        assert errors == [], errors
        print(f'PASS: observe/seal/reveal, new lesion, target rejection, desktop/mobile; renderer={renderer}; mode={"offline" if args.offline else "live"}')
        browser.close()


if __name__ == '__main__':
    main()
