"""Local UX regression suite. Offline mode does not claim network/CSP verification."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from browser_support import attach_local_api


def wait_state(page, value):
    page.wait_for_function('(value) => document.getElementById("metric-state").textContent===value', arg=value)


def capture(page, path, *, full_page=True):
    # Full-page screenshots must start at the origin so sticky/fixed controls
    # are not captured at an old scrolled viewport position.
    page.evaluate("() => {document.activeElement?.blur();window.scrollTo({top:0,left:0,behavior:'instant'});}")
    page.wait_for_timeout(120)
    page.screenshot(path=str(path), full_page=full_page)


def reveal(page):
    page.click('#reveal')
    page.wait_for_selector('#confirm-dialog[open]')
    page.click('#confirm-primary')
    wait_state(page, 'Evaluated')


def synthetic_proposal():
    from cancerlab.demo import demo_patients
    from cancerlab.registration import RegistrationRequest, register
    from cancerlab.tracking import propose_matches
    patient=demo_patients()['SYN-001']
    req=RegistrationRequest(patient_id='SYN-001',fixed_study_id='SYN-001-0',moving_study_id='SYN-001-90',
        organ='liver',reviewer_id='synthetic-review',available_day=90,max_error_mm=1,
        landmarks=[{'landmark_id':f'p{i}','fixed_ras_mm':p,'moving_ras_mm':p}
                   for i,p in enumerate([(0,0,0),(30,0,0),(0,30,0)])])
    return propose_matches(patient,register(patient,req))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--scan-fixture',action='store_true')
    parser.add_argument('--url',default='http://127.0.0.1:8765')
    parser.add_argument('--screenshots',type=Path)
    args=parser.parse_args()
    if args.scan_fixture and not args.offline:parser.error('Synthetic scan fixture requires --offline')
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        launch={'headless':True,'args':['--no-sandbox']}
        if shutil.which('chromium'):launch['executable_path']=shutil.which('chromium')
        browser=pw.chromium.launch(**launch)
        page=browser.new_page(viewport={'width':1440,'height':1100},reduced_motion='reduce')
        page.set_default_timeout(8000)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        calls=[];client=None
        if args.offline:client,calls=attach_local_api(page,Path(tmp)/'browser.sqlite3',args.scan_fixture)
        else:page.goto(args.url,wait_until='networkidle')
        page.wait_for_function('() => document.getElementById("metric-studies").textContent==="2"')
        assert page.locator('#seal').is_enabled()
        assert page.locator('#reveal').is_disabled()
        assert 'HELD-OUT' not in page.locator('#input-evidence').text_content()
        assert not any('/image?' in path or '/slice?' in path for _,path in calls), 'Images must be lazy-loaded'
        renderer=page.locator('#scene').get_attribute('data-renderer')
        assert renderer in {'webgl2','canvas-projection'}
        # Read-only dirty settings never destroy a saved artifact.
        page.click('#seal');wait_state(page,'Sealed')
        saved_href=page.locator('#export').get_attribute('href')
        assert page.locator('#seal').is_disabled()
        page.fill('#horizon','80')
        assert page.locator('#dirty-note').is_visible()
        assert page.locator('#reveal').is_disabled()
        assert page.locator('#export').get_attribute('href')==saved_href
        page.click('#restore-settings');assert page.locator('#horizon').input_value()=='90'
        page.click('#reveal');page.click('#confirm-cancel')
        assert not any(path.endswith('/reveal') for _,path in calls)
        reveal(page)
        assert page.locator('#scores .score').count()==3
        page.click('#truth-view')
        assert 'day 180' in page.locator('#scene-day').text_content()
        assert not page.locator('#forecast-legend').is_visible(), 'Never overlay unregistered future anatomy'
        page.click('#toggle-chart-data');assert page.locator('#chart-data tr').count()==4
        # Saved experiments are recoverable, without another seal/reveal.
        page.click('#new-draft');wait_state(page,'Draft')
        page.click('#tab-history');page.wait_for_selector('[data-resume]')
        before=len([1 for m,p in calls if m=='POST' and (p=='/api/experiments' or p.endswith('/reveal'))])
        page.locator('[data-resume]').first.click();wait_state(page,'Evaluated')
        after=len([1 for m,p in calls if m=='POST' and (p=='/api/experiments' or p.endswith('/reveal'))])
        assert before==after
        # Evidence search, detail dialog, and focus restoration.
        page.click('#tab-evidence');page.fill('#lesion-search','no-such-lesion')
        assert 'No matching identifiers' in page.locator('#lesions').text_content()
        page.fill('#lesion-search','');page.locator('[data-lesion="L1"]').first.click()
        assert page.locator('#lesion-dialog').is_visible()
        assert 'SHA-256' in page.locator('#lesion-detail').text_content()
        page.keyboard.press('Escape');assert not page.locator('#lesion-dialog').is_visible()
        assert page.locator('[data-lesion="L1"]').first.evaluate('(el) => el===document.activeElement')
        # Real UI file selection; explicit, validated draft, never relabelling.
        if args.offline:
            page.click('#tab-review')
            p=synthetic_proposal();source=Path(tmp)/'synthetic-proposal.json';source.write_text(json.dumps(p))
            page.set_input_files('#proposal-file',str(source))
            page.wait_for_selector('#review-content',state='visible')
            assert page.locator('[data-candidate]:checked').count()==0
            if args.screenshots:
                args.screenshots.mkdir(parents=True,exist_ok=True)
                capture(page,args.screenshots/'match-review.png')
            page.locator('[data-candidate]').first.check()
            page.locator('[data-reason]').first.fill('Reviewed synthetic source observations.')
            page.fill('#reviewer-id','reviewer-1')
            with page.expect_download() as pending:page.click('#review-export')
            output=Path(tmp)/'review.json';pending.value.save_as(output)
            review=json.loads(output.read_text())
            assert len(review['links'])==1 and review['proposal_sha256']==p['artifact_sha256']
            assert 'records are unchanged' in page.locator('#review-selection-note').text_content()
            # A deliberately malformed file must not keep old actionable data.
            bad=Path(tmp)/'bad.json';bad.write_text('{bad')
            page.set_input_files('#proposal-file',str(bad))
            page.wait_for_function('() => document.getElementById("review-status").textContent.includes("not valid JSON")')
            assert not page.locator('#review-content').is_visible()
        # Source CT interactions, keyboard range, overlay, presets and expanded view.
        page.click('#tab-images')
        if args.scan_fixture:
            page.wait_for_function('() => [...document.querySelectorAll(".scan-card img")].filter(i=>!i.hidden&&i.complete&&i.naturalWidth>0).length===3')
            assert 'SYNTHETIC VOXEL FIXTURE' in page.locator('#scan-status').text_content()
            page.select_option('#scan-preset','-600,1500')
            assert page.locator('input[name=center]').input_value()=='-600'
            page.locator('[data-plane=axial] .expand-scan').click()
            assert page.locator('#scan-dialog').is_visible()
            page.locator('#scan-dialog input[type=range]').fill('1')
            page.wait_for_function('() => document.querySelector("#scan-dialog .scan-card p").textContent.startsWith("Slice 2/")')
            page.keyboard.press('Escape')
            assert not page.locator('#scan-dialog').is_visible()
            page.wait_for_function('() => document.querySelector("[data-plane=axial] .expand-scan")===document.activeElement')
            page.locator('#mask-visible').uncheck()
            page.wait_for_timeout(200)
            assert any('opacity=0' in path for _,path in calls if '/slice?' in path)
            if args.screenshots:
                args.screenshots.mkdir(parents=True,exist_ok=True)
                page.select_option('#scan-preset','40,400')
                page.locator('#mask-visible').check()
                page.locator('[data-plane=axial] input[type=range]').fill('20')
                page.wait_for_function('() => [...document.querySelectorAll(".scan-card")].every(c=>c.getAttribute("aria-busy")=="false")')
                page.wait_for_function('() => document.querySelector("[data-plane=axial] p").textContent.startsWith("Slice 21/")')
                capture(page,args.screenshots/'ct-viewer.png')
        else:
            page.wait_for_function('() => document.getElementById("scan-status").textContent.includes("scan-root")')
            assert page.locator('#scan-setup').is_visible()
        # Help dialog and APG tab keyboard navigation.
        page.click('#help');assert page.locator('#help-dialog').is_visible();page.keyboard.press('Escape')
        page.locator('#tab-overview').focus();page.keyboard.press('ArrowRight')
        assert page.locator('#tab-images').get_attribute('aria-selected')=='true'
        page.keyboard.press('Home');assert page.locator('#tab-overview').get_attribute('aria-selected')=='true'
        if args.screenshots:
            args.screenshots.mkdir(parents=True,exist_ok=True)
            capture(page,args.screenshots/'desktop.png')
        # Responsive layouts and named controls, across all five views.
        for width in [320,390,768,1440]:
            page.set_viewport_size({'width':width,'height':844})
            for name in ['overview','images','evidence','review','history']:
                page.click(f'#tab-{name}')
                assert not page.evaluate('() => document.documentElement.scrollWidth>innerWidth'),f'overflow: {name} {width}'
        page.set_viewport_size({'width':390,'height':844});page.click('#tab-overview')
        if args.screenshots:capture(page,args.screenshots/'mobile.png')
        assert page.locator('#quick-action').is_visible()
        # New patient, missing follow-up, and future-data isolation after resets.
        page.select_option('#patient','SYN-002')
        page.wait_for_function('() => document.getElementById("organ").value==="kidney" && !document.getElementById("seal").disabled')
        assert page.locator('#reveal').is_disabled()
        page.click('#quick-action');wait_state(page,'Sealed')
        page.click('#quick-action');page.click('#confirm-primary');wait_state(page,'Evaluated')
        assert '1 newly observed' in page.locator('#comparison-note').text_content()
        if not page.locator('#settings').is_visible():page.click('#toggle-settings')
        page.fill('#horizon','80');page.click('#apply')
        page.wait_for_function('() => !document.getElementById("seal").disabled')
        page.click('#quick-action');wait_state(page,'Sealed')
        page.click('#quick-action');page.click('#confirm-primary');page.wait_for_selector('#error',state='visible')
        assert 'predeclared' in page.locator('#error-message').text_content()
        assert page.locator('#export').get_attribute('href')
        if args.offline:
            page.evaluate('() => {window.__testDelay={path:"SYN-001/snapshot",ms:400}}')
            page.select_option('#patient','SYN-001');page.select_option('#patient','SYN-003')
            page.wait_for_function('() => document.getElementById("organ").value==="pancreas" && document.getElementById("patient-title").textContent==="SYN-003"')
            page.wait_for_timeout(450)
            assert page.locator('#patient-title').text_content()=='SYN-003'
            assert 'SYN-001' not in page.locator('#input-evidence').text_content()
        assert errors==[],errors
        print(f'PASS: saved/resumed forecasts, explicit reveal, dirty settings, review draft, search/detail, tabs/focus, 320/390/768/1440px, lazy scans={args.scan_fixture}, latest-patient wins; renderer={renderer}; mode={"offline in-process API" if args.offline else "live"}')
        if args.offline and args.screenshots:
            mobile=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
            mobile_client,_=attach_local_api(mobile,Path(tmp)/'mobile.sqlite3',args.scan_fixture)
            mobile.wait_for_function('() => document.getElementById("metric-studies").textContent==="2"')
            assert not mobile.locator('#settings').is_visible()
            assert mobile.locator('#quick-action').is_visible()
            capture(mobile,args.screenshots/'mobile.png',full_page=False)
            mobile_client.__exit__(None,None,None)
        browser.close()
        if client:client.__exit__(None,None,None)


if __name__=='__main__':main()
