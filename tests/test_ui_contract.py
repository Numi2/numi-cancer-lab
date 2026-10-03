"""Cheap structural checks complement, not replace, the local browser suite."""
from html.parser import HTMLParser
from pathlib import Path
import re

from fastapi.testclient import TestClient
from cancerlab.api import create_app

WEB=Path(__file__).resolve().parents[1]/'cancerlab/web'


class Markup(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.tags=[]; self.feed(text)
    def handle_starttag(self,tag,attrs):
        self.tags.append((tag,dict(attrs)))


def test_tab_and_dialog_references_resolve():
    markup=Markup((WEB/'index.html').read_text())
    ids=[a['id'] for _,a in markup.tags if 'id' in a]
    assert len(ids)==len(set(ids))
    tabs=[a for _,a in markup.tags if a.get('role')=='tab']
    assert len(tabs)==5
    assert sum(t.get('aria-selected')=='true' for t in tabs)==1
    for t in tabs:assert t['aria-controls'] in ids
    for tag,a in markup.tags:
        if tag=='label' and 'for' in a:assert a['for'] in ids
        if tag=='dialog':assert a['aria-labelledby'] in ids


def test_module_dependencies_are_local_and_exist():
    for file in WEB.glob('*.js'):
        for target in re.findall(r"^import .*? from ['\"](.+?)['\"];",file.read_text(),re.MULTILINE):
            assert target.startswith('./')
            assert (file.parent/target).resolve().is_relative_to(WEB.resolve())
            assert (file.parent/target).is_file()
    source='\n'.join(p.read_text() for p in WEB.glob('*.js'))
    assert 'localStorage' not in source and 'sessionStorage' not in source


def test_new_modules_keep_static_security_headers(tmp_path):
    with TestClient(create_app(db_path=tmp_path/'ui.sqlite3')) as c:
        for name in ['ui.js','review.js','chart.js','scanview.js']:
            response=c.get('/static/'+name)
            assert response.status_code==200
            assert "script-src 'self'" in response.headers['Content-Security-Policy']
            assert "unsafe-eval" not in response.headers['Content-Security-Policy']
            assert response.headers['Cache-Control']=='no-store'
