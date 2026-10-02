"""Synthetic array/adapter tests; not a substitute for NIfTI integration tests."""
import base64
import io
import itertools
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cancerlab import scanview as sv
from cancerlab.api import create_app
from cancerlab.demo import demo_patients
from cancerlab.models import Evidence, Lesion, Patient, Study


class PlaneOnly:
    def __init__(self, values):
        self.values = values
        self.reads = []

    def __getitem__(self, selection):
        assert sum(isinstance(x, int) for x in selection) == 1
        self.reads.append(selection)
        return self.values[selection]

    def __array__(self, *args, **kwargs):
        raise AssertionError('Whole-volume materialization is prohibited in the viewer')


def image(values=None, affine=None):
    values = np.arange(60).reshape(3, 4, 5) if values is None else values
    return SimpleNamespace(shape=values.shape, affine=np.eye(4) if affine is None else affine,
                           dataobj=PlaneOnly(values))


@pytest.mark.parametrize('permutation', list(itertools.permutations(range(3))))
@pytest.mark.parametrize('signs', list(itertools.product([-1, 1], repeat=3)))
def test_all_axis_permutations_and_flips_preserve_ras_planes(permutation, signs):
    canonical = np.arange(60).reshape(3, 4, 5)
    spacing = [2, 3, 4]; origin = [10, -20, 30]
    values = canonical.transpose(permutation)
    affine = np.zeros((4, 4)); affine[3, 3] = 1; affine[:3, 3] = origin
    for source, world in enumerate(permutation):
        affine[world, source] = signs[source] * spacing[world]
        if signs[source] < 0:
            values = np.flip(values, axis=source)
            affine[world, 3] += (canonical.shape[world] - 1) * spacing[world]
    img = image(values, affine)
    for plane, fixed in [('axial', 2), ('coronal', 1), ('sagittal', 0)]:
        actual, meta = sv.plane_pixels(img, plane, 1)
        expected = np.take(canonical, 1, axis=fixed).T[::-1, ::-1]
        np.testing.assert_array_equal(actual, expected)
        assert meta['position_ras_mm'] == pytest.approx(origin[fixed] + spacing[fixed])
    assert len(img.dataobj.reads) == 3


def test_plane_spacing_orientation_and_png_window():
    img = image(np.array([[[-160], [40]], [[240], [500]]]), np.diag([2, 3, 4, 1]))
    result = sv.render_slice(img, 'axial', 0, center=40, width=400)
    pixels = np.asarray(Image.open(io.BytesIO(base64.b64decode(result['png_base64']))))
    np.testing.assert_array_equal(pixels[:, :, 0], [[255, 128], [255, 0]])
    assert result['pixel_spacing_mm'] == [3, 2]
    assert result['orientation'] == dict(top='A', right='L', bottom='P', left='R')


def test_measured_mask_overlay_and_grid_rejection():
    img = image(np.zeros((3, 4, 5)))
    mask = image(np.ones((3, 4, 5)))
    result = sv.render_slice(img, 'sagittal', 1, mask=mask, opacity=1)
    pixels = np.asarray(Image.open(io.BytesIO(base64.b64decode(result['png_base64']))))
    assert tuple(pixels[0, 0]) == (98, 216, 189)
    with pytest.raises(ValueError, match='grids differ'):
        sv.render_slice(img, 'axial', 0, mask=image(np.ones((2, 4, 5))))
    with pytest.raises(ValueError, match='binary'):
        sv.render_slice(img, 'axial', 0, mask=image(np.full((3, 4, 5), .5)))


def test_oblique_and_sheared_display_refused():
    affine = np.eye(4); affine[0, 1] = .2
    with pytest.raises(ValueError, match='resampling'):
        sv.geometry(image(affine=affine))


@pytest.mark.parametrize('kwargs', [{'width': 0}, {'center': float('nan')}, {'opacity': 1.1}])
def test_bad_window_parameters(kwargs):
    with pytest.raises(ValueError):
        sv.render_slice(image(), 'axial', 0, **kwargs)


def test_pixel_limit_and_indices_checked_before_data_read(monkeypatch):
    img = image()
    for index in [-1, 5, True]:
        with pytest.raises(ValueError):
            sv.plane_pixels(img, 'axial', index)
    monkeypatch.setattr(sv, 'MAX_PLANE_PIXELS', 2)
    with pytest.raises(ValueError, match='pixel limit'):
        sv.plane_pixels(img, 'axial', 0)
    assert img.dataobj.reads == []


def test_nonfinite_slice_refused():
    with pytest.raises(ValueError, match='non-finite'):
        sv.render_slice(image(np.full((3, 4, 5), np.nan)), 'axial', 0)


@pytest.fixture
def local_case(tmp_path, monkeypatch):
    case = tmp_path / 'CancerVerse/CV_00000001'; (case / 'segmentations').mkdir(parents=True)
    ct = case / 'ct.nii.gz'; ct.write_bytes(b'synthetic CT proxy fixture')
    mask = case / 'segmentations/liver_lesion.nii.gz'; mask.write_bytes(b'synthetic mask proxy fixture')
    study = Study(study_id='CV_00000001', acquired_day=0, available_day=1, coverage=('liver',),
                  scan_sha256=sv.file_sha256(ct), lesions=(Lesion(lesion_id='L1', organ='liver', volume_ml=1,
                  evidence=Evidence(source='CancerVerse/CV_00000001/segmentations/liver_lesion.nii.gz#component=1',
                                    method='mask-volume', sha256=sv.file_sha256(mask))),))
    # synthetic=False exercises the adapter; these bytes are not patient data.
    patient = Patient(patient_id='FIXTURE', source='CancerVerse', source_revision='test', synthetic=False, studies=(study,))
    calls = []
    def load(path):
        calls.append(path)
        return image(np.ones((3, 4, 5)) if 'lesion' in path.name else np.zeros((3, 4, 5)))
    monkeypatch.setattr(sv, 'load_nifti', load)
    return sv.LocalScans(tmp_path), patient, study, ct, mask, calls


def test_catalog_hash_verification_and_proxy_cache(local_case):
    scans, patient, study, ct, mask, calls = local_case
    assert scans.metadata(patient, study, 'liver')['overlay_available']
    assert scans.slice(patient, study, 'liver', 'axial', 0, 40, 400, .4)['overlay']
    assert len(calls) == 2
    ct.write_bytes(b'changed bytes must invalidate cache')
    with pytest.raises(ValueError, match='hash differs'):
        scans.metadata(patient, study, 'liver')


def test_mask_hash_and_path_mismatch_refused(local_case):
    scans, patient, study, ct, mask, calls = local_case
    mask.write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash differs'):
        scans.metadata(patient, study, 'liver')
    bad = study.model_dump(mode='json'); bad['lesions'][0]['evidence']['source'] = '../../outside.nii.gz#component=1'
    with pytest.raises(ValueError, match='reference'):
        scans.metadata(patient, Study.model_validate(bad), 'liver')


def test_empty_annotation_not_invented_and_coverage_checked(local_case):
    scans, patient, study, *_ = local_case
    empty = Study.model_validate({**study.model_dump(mode='json'), 'lesions': []})
    assert not scans.metadata(patient, empty, 'liver')['overlay_available']
    with pytest.raises(ValueError, match='coverage'):
        scans.metadata(patient, study, 'kidney')


def test_api_images_cannot_reveal_future_before_recorded_evaluation(tmp_path):
    patients = demo_patients(); patient = patients['SYN-001']
    with TestClient(create_app(patients, tmp_path / 'api.sqlite')) as client:
        before = f'/api/patients/{patient.patient_id}/studies/{patient.studies[0].study_id}/image'
        future = f'/api/patients/{patient.patient_id}/studies/{next(s.study_id for s in patient.studies if s.acquired_day == 180)}/image'
        query = {'organ': 'liver', 'cutoff_day': 90}
        assert client.get(before, params=query).json()['configured'] is False
        assert client.get(future, params=query).status_code == 404
        headers = {'X-Cancerlab-Request': 'local-research'}
        run = client.post('/api/experiments', headers=headers, json={'patient_id': patient.patient_id,
            'spec': {'organ': 'liver', 'cutoff_day': 90, 'horizon_days': 90}}).json()
        query['run_id'] = run['id']
        assert client.get(future, params=query).status_code == 404
        assert client.post(f"/api/experiments/{run['id']}/reveal", headers=headers, json={}).status_code == 200
        assert client.get(future, params=query).status_code == 200
        assert client.get(future.replace('SYN-001', 'SYN-002'), params=query).status_code == 404
        assert client.get(before, params=query).status_code == 404


def test_api_slice_validation_and_no_configuration(tmp_path):
    patient = demo_patients()['SYN-001']; s = patient.studies[0]
    with TestClient(create_app(db_path=tmp_path / 'api.sqlite')) as client:
        path = f'/api/patients/SYN-001/studies/{s.study_id}/slice'
        query = {'organ': 'liver', 'cutoff_day': 90, 'index': 0}
        assert client.get(path, params=query).status_code == 409
        for invalid in [{'index': -1}, {'width': 0}, {'center': 'nan'}, {'plane': 'invalid'}, {'organ': 'brain'}]:
            assert client.get(path, params={**query, **invalid}).status_code == 422


def test_api_uses_hash_verified_configured_catalog(local_case, tmp_path):
    scans, patient, study, *_ = local_case
    with TestClient(create_app({patient.patient_id: patient}, tmp_path / 'api.sqlite', scans.root)) as client:
        path = f'/api/patients/{patient.patient_id}/studies/{study.study_id}'
        query = {'organ': 'liver', 'cutoff_day': 1}
        assert client.get(path + '/image', params=query).json()['configured']
        response = client.get(path + '/slice', params={**query, 'index': 0})
        assert response.status_code == 200
        assert response.json()['png_base64'].startswith('iVBOR')
        assert response.headers['cache-control'] == 'no-store'


def test_real_nifti_scan_viewer(tmp_path):
    nib = pytest.importorskip('nibabel')
    values = np.arange(60, dtype=np.int16).reshape(3, 4, 5)
    img = nib.Nifti1Image(values, np.diag([-2., 3., 4., 1.]))
    img.header.set_xyzt_units('mm'); path = tmp_path / 'scan.nii.gz'; nib.save(img, path)
    loaded = sv.load_nifti(path)
    pixels, _ = sv.plane_pixels(loaded, 'axial', 2)
    np.testing.assert_array_equal(pixels, values[:, :, 2].T[::-1, :])
