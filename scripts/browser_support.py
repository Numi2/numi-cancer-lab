"""Offline browser/API integration, not live-network, module-loader or CSP verification.

The test renders application files in memory and binds fetch to TestClient.
It never changes browser policies or launches a network service.
"""
from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient


def attach_local_api(page, db_path: Path, scan_fixture: bool = False):
    from cancerlab.api import create_app
    from cancerlab import api as api_module
    previous = api_module.LocalScans
    if scan_fixture:
        import numpy as np
        from types import SimpleNamespace
        from cancerlab.scanview import geometry, render_slice
        from cancerlab.models import digest
        xyz = np.indices((48, 56, 40))
        radius = ((xyz[0]-24)/20)**2 + ((xyz[1]-28)/24)**2 + ((xyz[2]-20)/17)**2
        values = np.where(radius < 1, 40 + xyz[0], -900).astype(np.int16)
        mask = (((xyz[0]-28)**2 + (xyz[1]-25)**2 + (xyz[2]-20)**2) < 36).astype(np.uint8)
        affine = np.diag([1., 1., 2., 1.])
        ct = SimpleNamespace(shape=values.shape, dataobj=values, affine=affine)
        annotation = SimpleNamespace(shape=mask.shape, dataobj=mask, affine=affine)
        class SyntheticScans:
            def __init__(self, root):
                pass
            def metadata(self, patient, study, organ):
                return {**geometry(ct), 'scan_sha256': digest('synthetic voxel fixture'),
                        'overlay_available': True, 'synthetic': True}
            def slice(self, patient, study, organ, plane, index, center, width, opacity):
                return render_slice(ct, plane, index, mask=annotation, center=center, width=width, opacity=opacity)
        api_module.LocalScans = SyntheticScans
    app = create_app(db_path=db_path, scan_root=db_path.parent if scan_fixture else None)
    api_module.LocalScans = previous
    client = TestClient(app)
    client.__enter__()
    calls = []
    def local_request(data):
        calls.append((data['method'], data['path']))
        response = client.request(data['method'], data['path'],
                                  headers=data['headers'], content=data['body'])
        return {'status': response.status_code, 'text': response.text}
    page.expose_function('localResearchAPI', local_request)
    mount_offline(page)
    return client, calls


def mount_offline(page):
    import re
    web = Path(__file__).resolve().parents[1] / 'cancerlab/web'
    html = (web / 'index.html').read_text()
    for name in ['styles.css', 'scanview.css']:
        html = html.replace(f'<link rel="stylesheet" href="/static/{name}">',
                            '<style>' + (web / name).read_text() + '</style>')
    html = html.replace('<script type="module" src="/static/app.js"></script>', '')
    page.set_content(html)
    page.add_script_tag(content="""window.fetch=async(path,options={})=>{
        const signal=options.signal;
        if(signal?.aborted)throw new DOMException('Cancelled','AbortError');
        if(window.__testDelay && path.includes(window.__testDelay.path))
            await new Promise(resolve=>setTimeout(resolve,window.__testDelay.ms));
        if(signal?.aborted)throw new DOMException('Cancelled','AbortError');
        const r=await window.localResearchAPI({path,method:options.method||'GET',headers:options.headers||{},body:options.body||null});
        if(signal?.aborted)throw new DOMException('Cancelled','AbortError');
        return new Response(r.text,{status:r.status,headers:{'Content-Type':'application/json'}});
    };""")
    sources = []
    for name in ['ui.js', 'scene.js', 'scanview.js', 'chart.js', 'review.js', 'app.js']:
        source = (web / name).read_text()
        source = re.sub(r'^import .*?;\n', '', source, flags=re.MULTILINE)
        source = re.sub(r'^export ', '', source, flags=re.MULTILINE)
        sources.append(source)
    page.add_script_tag(content='(() => {\n' + '\n'.join(sources) + '\n})();')
