from pathlib import Path

import numpy as np
import pytest

from cancerlab.imaging import checked_affine, components, file_sha256, load_nifti, measure_nifti


def test_anisotropic_volume_and_ras_centroid():
    mask = np.zeros((8, 8, 8), np.uint8)
    mask[1:3, 2:4, 3:5] = 1
    a = np.diag([-2., 3., 4., 1.])
    a[:3, 3] = [100, -20, 5]
    measured = components(mask, a)
    assert len(measured) == 1
    assert measured[0]['voxel_count'] == 8
    assert measured[0]['volume_ml'] == pytest.approx(.192)
    assert measured[0]['centroid_ras_mm'] == pytest.approx((97, -12.5, 19))


def test_shear_uses_determinant_not_column_norm_product():
    a = np.eye(4); a[0, 1] = 2
    assert components(np.ones((2, 2, 2)), a)[0]['volume_ml'] == pytest.approx(.008)


def test_components_are_scan_local_and_26_connected():
    mask = np.zeros((5, 5, 5), np.uint8)
    mask[0, 0, 0] = mask[1, 1, 1] = mask[4, 4, 4] = 1
    measured = components(mask, np.eye(4))
    assert [m['voxel_count'] for m in measured] == [2, 1]
    assert [m['component'] for m in measured] == [1, 2]


def test_empty_binary_annotation_is_not_a_fabricated_lesion():
    assert components(np.zeros((2, 3, 4)), np.eye(4)) == []


@pytest.mark.parametrize('value', [float('nan'), float('inf'), .5, 2, -1])
def test_probabilities_instances_and_invalid_values_refused(value):
    mask = np.zeros((2, 2, 2)); mask[0, 0, 0] = value
    with pytest.raises(ValueError, match='binary'):
        components(mask, np.eye(4))


@pytest.mark.parametrize('shape', [(3, 3), (2, 2, 2, 1), (0, 2, 3)])
def test_invalid_dimensions(shape):
    with pytest.raises(ValueError, match='3D'):
        components(np.zeros(shape), np.eye(4))


def test_memory_limit():
    with pytest.raises(ValueError, match='limit'):
        components(np.zeros((3, 3, 3)), np.eye(4), max_voxels=20)


@pytest.mark.parametrize('a', [np.zeros((4, 4)), np.eye(3), np.full((4, 4), np.nan)])
def test_bad_affine_refused(a):
    with pytest.raises(ValueError):
        checked_affine(a)


def test_file_digest(tmp_path):
    p = tmp_path / 'x'; p.write_bytes(b'abc')
    assert file_sha256(p) == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'


def test_actual_nifti_grid_and_units(tmp_path):
    nib = pytest.importorskip('nibabel')
    mask = np.zeros((8, 8, 8), np.uint8); mask[2:4, 2:4, 2:4] = 1
    a = np.diag([2., 3., 4., 1.])
    ct = nib.Nifti1Image(np.zeros(mask.shape, np.int16), a)
    ct.header.set_xyzt_units('mm')
    ct_path = tmp_path / 'ct.nii.gz'; nib.save(ct, ct_path)
    image = nib.Nifti1Image(mask, a); image.header.set_xyzt_units('mm')
    mask_path = tmp_path / 'mask.nii.gz'; nib.save(image, mask_path)
    loaded = load_nifti(ct_path)
    assert measure_nifti(mask_path, loaded)[0]['volume_ml'] == pytest.approx(.192)
    image.header.set_xyzt_units('unknown'); nib.save(image, mask_path)
    with pytest.raises(ValueError, match='millimetres'):
        measure_nifti(mask_path, loaded)
    image.header.set_xyzt_units('mm'); image.set_sform(np.eye(4), code=1); nib.save(image, mask_path)
    with pytest.raises(ValueError, match='grids differ'):
        measure_nifti(mask_path, loaded)
