import pytest

from cancerlab import cancerverse as cv
from test_cancerverse import manifest_data, source


def test_reviewed_manifest_file_bindings_refuse_changed_ct(source, manifest_data):
    manifest_data['patients'][0]['studies'][0]['expected_scan_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='CT bytes differ'):
        cv.import_records(source, cv.ImportManifest.model_validate(manifest_data), acknowledge_license=True)


def test_reviewed_manifest_file_bindings_refuse_changed_mask(source, manifest_data):
    manifest_data['patients'][0]['studies'][0]['masks'][0]['expected_mask_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='Mask bytes differ'):
        cv.import_records(source, cv.ImportManifest.model_validate(manifest_data), acknowledge_license=True)
