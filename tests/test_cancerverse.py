import copy

import pytest
from pydantic import ValidationError

from cancerlab import cancerverse as cv
from cancerlab.models import snapshot


@pytest.fixture
def manifest_data():
    return {'source_revision': 'test-pinned-revision', 'patients': [{'patient_id': 'P001', 'studies': [
        {'case_id': 'CV_00000001', 'acquired_day': 0, 'available_day': 5, 'coverage': ['liver'],
         'annotation_scope': 'complete', 'masks': [{'organ': 'liver', 'reviews': [
             {'component': 1, 'lesion_id': 'L1', 'reviewer_id': 'curator-1', 'available_day': 7}]}]},
        {'case_id': 'CV_00000002', 'acquired_day': 90, 'available_day': 95, 'coverage': ['liver'],
         'annotation_scope': 'complete', 'masks': [{'organ': 'liver', 'reviews': [
             {'component': 1, 'lesion_id': 'L1', 'reviewer_id': 'curator-1', 'available_day': 97}]}]}
    ]}]}


@pytest.fixture
def source(tmp_path, monkeypatch):
    for number in [1, 2]:
        case = tmp_path / 'CancerVerse' / f'CV_{number:08}'
        (case / 'segmentations').mkdir(parents=True)
        (case / 'ct.nii.gz').write_bytes(f'fictional-ct-{number}'.encode())
        (case / 'segmentations/liver_lesion.nii.gz').write_bytes(b'fictional-mask')
    (tmp_path / 'CancerVerse_dataset_metadata.csv').write_text('case_key,person_key\nfictional1,fictionalP\n')
    monkeypatch.setattr(cv, 'load_nifti', lambda path: object())
    monkeypatch.setattr(cv, 'measure_nifti', lambda path, ct: [
        {'component': 1, 'volume_ml': 1.25, 'centroid_ras_mm': (1., 2., 3.), 'voxel_count': 1250}])
    return tmp_path


def test_inspect_does_not_expose_patient_rows(source):
    report = cv.inspect(source)
    assert report['metadata_columns'] == ['case_key', 'person_key']
    assert report['row_count'] == 1
    assert 'fictionalP' not in str(report)


def test_import_requires_license_ack(source, manifest_data):
    with pytest.raises(ValueError, match='license'):
        cv.import_records(source, cv.ImportManifest.model_validate(manifest_data))


def test_import_uses_reviewed_identity_and_evidence_availability(source, manifest_data):
    patients, receipt = cv.import_records(source, cv.ImportManifest.model_validate(manifest_data), acknowledge_license=True)
    p = patients['P001']
    assert not p.synthetic
    assert [s.available_day for s in p.studies] == [7, 97]
    assert len(snapshot(p, 95).studies) == 1
    assert p.studies[0].lesions[0].lesion_id == p.studies[1].lesions[0].lesion_id == 'L1'
    assert p.studies[0].lesions[0].correspondence == 'confirmed'
    assert receipt['studies'][0]['masks'][0]['reviews'][0]['reviewer_id'] == 'curator-1'


def test_unreviewed_components_never_become_longitudinal_tracks(source, manifest_data):
    for s in manifest_data['patients'][0]['studies']:
        s['masks'][0]['reviews'] = []
    patients, _ = cv.import_records(source, cv.ImportManifest.model_validate(manifest_data), acknowledge_license=True)
    observations = [s.lesions[0] for s in patients['P001'].studies]
    assert observations[0].lesion_id != observations[1].lesion_id
    assert all(m.correspondence == 'unverified' for m in observations)


def test_mistyped_component_refused(source, manifest_data):
    manifest_data['patients'][0]['studies'][0]['masks'][0]['reviews'][0]['component'] = 2
    with pytest.raises(ValueError, match='does not exist'):
        cv.import_records(source, cv.ImportManifest.model_validate(manifest_data), acknowledge_license=True)


def test_duplicate_scan_bytes_refused(source, manifest_data):
    (source / 'CancerVerse/CV_00000002/ct.nii.gz').write_bytes((source / 'CancerVerse/CV_00000001/ct.nii.gz').read_bytes())
    with pytest.raises(ValueError, match='duplicate CT'):
        cv.import_records(source, cv.ImportManifest.model_validate(manifest_data), acknowledge_license=True)


def test_missing_annotation_not_empty_mask(source, manifest_data):
    (source / 'CancerVerse/CV_00000001/segmentations/liver_lesion.nii.gz').unlink()
    with pytest.raises(FileNotFoundError):
        cv.import_records(source, cv.ImportManifest.model_validate(manifest_data), acknowledge_license=True)


def test_symlink_escape_refused(source, tmp_path_factory):
    outside = tmp_path_factory.mktemp('outside') / 'private'; outside.write_text('not permitted')
    (source / 'escape').symlink_to(outside)
    with pytest.raises(ValueError, match='inside'):
        cv.inside(source, 'escape')


def test_duplicate_case_identity_refused(manifest_data):
    manifest_data['patients'].append(copy.deepcopy(manifest_data['patients'][0]))
    manifest_data['patients'][1]['patient_id'] = 'P002'
    with pytest.raises(ValidationError, match='appear twice'):
        cv.ImportManifest.model_validate(manifest_data)


def test_complete_annotation_requires_all_covered_masks(manifest_data):
    manifest_data['patients'][0]['studies'][0]['coverage'].append('kidney')
    with pytest.raises(ValidationError, match='every covered organ'):
        cv.ImportManifest.model_validate(manifest_data)


def test_review_before_scan_refused(manifest_data):
    manifest_data['patients'][0]['studies'][1]['masks'][0]['reviews'][0]['available_day'] = 89
    with pytest.raises(ValidationError, match='precede'):
        cv.ImportManifest.model_validate(manifest_data)


def test_import_is_local_and_no_overwrite(source, manifest_data, tmp_path):
    patients, receipt = cv.import_records(source, cv.ImportManifest.model_validate(manifest_data), acknowledge_license=True)
    out = tmp_path / 'output'; receipt_path = tmp_path / 'receipt.json'
    cv.write_import(patients, receipt, out, receipt_path)
    assert (out / 'P001.json').is_file()
    assert receipt_path.is_file()
    with pytest.raises(ValueError, match='overwritten'):
        cv.write_import(patients, receipt, out, receipt_path)


def test_receipt_must_not_be_mixed_with_patient_files(source, manifest_data, tmp_path):
    patients, receipt = cv.import_records(source, cv.ImportManifest.model_validate(manifest_data), acknowledge_license=True)
    with pytest.raises(ValueError, match='outside'):
        cv.write_import(patients, receipt, tmp_path / 'output', tmp_path / 'output/receipt.json')


def test_real_nifti_import(tmp_path, manifest_data):
    nib = pytest.importorskip('nibabel')
    import numpy as np
    for number in [1, 2]:
        case = tmp_path / 'CancerVerse' / f'CV_{number:08}'
        (case / 'segmentations').mkdir(parents=True)
        ct = nib.Nifti1Image(np.full((10, 10, 10), number, dtype=np.int16), np.eye(4))
        ct.header.set_xyzt_units('mm'); nib.save(ct, case / 'ct.nii.gz')
        mask = np.zeros((10, 10, 10), dtype=np.uint8); mask[2:4 + number, 2:4, 2:4] = 1
        image = nib.Nifti1Image(mask, np.eye(4)); image.header.set_xyzt_units('mm')
        nib.save(image, case / 'segmentations/liver_lesion.nii.gz')
    patients, _ = cv.import_records(tmp_path, cv.ImportManifest.model_validate(manifest_data), acknowledge_license=True)
    assert patients['P001'].studies[0].lesions[0].volume_ml == pytest.approx(.012)
    assert patients['P001'].studies[1].lesions[0].volume_ml == pytest.approx(.016)
