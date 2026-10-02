"""Bounded, source-grid CT slices. No automatic resampling or predicted anatomy."""
from __future__ import annotations

import base64
import io
import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .cancerverse import MASK_NAMES, inside
from .imaging import checked_affine, file_sha256, load_nifti
from .models import Patient, Study

# fixed RAS axis, vertical RAS axis, horizontal RAS axis, top/right/bottom/left
PLANES = {'axial': (2, 1, 0, ('A', 'L', 'P', 'R')),
          'coronal': (1, 2, 0, ('S', 'L', 'I', 'R')),
          'sagittal': (0, 2, 1, ('S', 'P', 'I', 'A'))}
MAX_PLANE_PIXELS = 4_194_304


def geometry(image) -> dict:
    a = checked_affine(image.affine)
    shape = tuple(int(n) for n in image.shape)
    if len(shape) != 3 or min(shape) < 1:
        raise ValueError('Expected a nonempty three-dimensional image')
    spacing = np.linalg.norm(a[:3, :3], axis=0)
    direction = a[:3, :3] / spacing
    world_axes = np.argmax(np.abs(direction), axis=0)
    cardinal = np.zeros((3, 3))
    cardinal[world_axes, np.arange(3)] = np.sign(direction[world_axes, np.arange(3)])
    if len(set(world_axes)) != 3 or not np.allclose(direction, cardinal, atol=1e-5, rtol=0):
        raise ValueError('Oblique or sheared scan: explicit resampling is required before this viewer')
    axes = [int(np.where(world_axes == world)[0][0]) for world in range(3)]
    return {'shape_ijk': shape, 'shape_ras': [shape[i] for i in axes],
            'spacing_ras_mm': [float(spacing[i]) for i in axes],
            'source_axis_for_ras': axes,
            'source_direction': [int(cardinal[world, i]) for world, i in enumerate(axes)],
            'origin_ras_mm': [float(v) for v in a[:3, 3]]}


def plane_pixels(image, plane: str, index: int) -> tuple[np.ndarray, dict]:
    if plane not in PLANES:
        raise ValueError('Unknown viewing plane')
    g = geometry(image)
    fixed, vertical, horizontal, labels = PLANES[plane]
    count = g['shape_ras'][fixed]
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count:
        raise ValueError('Slice index is outside the image')
    if g['shape_ras'][vertical] * g['shape_ras'][horizontal] > MAX_PLANE_PIXELS:
        raise ValueError('Slice exceeds the display pixel limit')
    source = g['source_axis_for_ras']
    signs = g['source_direction']
    fixed_index = index if signs[fixed] > 0 else count - 1 - index
    selection = [slice(None)] * 3
    selection[source[fixed]] = fixed_index
    # Proxy slicing reads a plane rather than requesting the entire 3D image.
    values = np.asanyarray(image.dataobj[tuple(selection)])
    remaining = [axis for axis in range(3) if axis != source[fixed]]
    values = values.transpose(remaining.index(source[vertical]), remaining.index(source[horizontal]))
    if signs[vertical] > 0:
        values = values[::-1, :]
    if signs[horizontal] > 0:
        values = values[:, ::-1]
    if values.dtype.kind not in 'buif' or not np.isfinite(values).all():
        raise ValueError('Displayed slice contains non-finite or non-numeric values')
    position = g['origin_ras_mm'][fixed] + signs[fixed] * fixed_index * g['spacing_ras_mm'][fixed]
    return values, {'plane': plane, 'index': index, 'slice_count': count,
                    'position_ras_mm': position, 'orientation': dict(zip(('top', 'right', 'bottom', 'left'), labels)),
                    'pixel_spacing_mm': [g['spacing_ras_mm'][vertical], g['spacing_ras_mm'][horizontal]]}


def render_slice(image, plane: str, index: int, *, mask=None, center: float = 40,
                 width: float = 400, opacity: float = .4) -> dict:
    if not all(math.isfinite(v) for v in (center, width, opacity)) or not (
            -5000 <= center <= 5000 and 1 <= width <= 10000 and 0 <= opacity <= 1):
        raise ValueError('Invalid intensity window or mask opacity')
    values, result = plane_pixels(image, plane, index)
    gray = np.rint(np.clip((values.astype(np.float64) - (center - width / 2)) / width, 0, 1) * 255).astype(np.uint8)
    rgb = np.repeat(gray[..., None], 3, axis=-1)
    if mask is not None:
        if image.shape != mask.shape or not np.allclose(image.affine, mask.affine, atol=1e-4, rtol=0):
            raise ValueError('CT and mask grids differ; overlay refused')
        overlay, _ = plane_pixels(mask, plane, index)
        if not np.isin(overlay, [0, 1]).all():
            raise ValueError('Overlay must be a binary mask')
        selected = overlay.astype(bool)
        rgb[selected] = np.rint((1 - opacity) * rgb[selected] + opacity * np.array([98, 216, 189])).astype(np.uint8)
    output = io.BytesIO()
    Image.fromarray(rgb).save(output, format='PNG')
    return {**result, 'width': rgb.shape[1], 'height': rgb.shape[0],
            'window_center': center, 'window_width': width, 'overlay': mask is not None,
            'png_base64': base64.b64encode(output.getvalue()).decode('ascii')}


class LocalScans:
    """Only dataset-relative paths derived from already-approved canonical records."""
    def __init__(self, root: Path):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('Scan root must be a directory')
        # Per-app cache of bounded NIfTI proxies, not loaded CT arrays.
        self._load = lru_cache(maxsize=8)(self._verified_image)

    @staticmethod
    def _verified_image(path: Path, expected_hash: str, signature: tuple):
        if file_sha256(path) != expected_hash:
            raise ValueError('Local scan or mask hash differs from the imported evidence')
        return load_nifti(path)

    def _read(self, path: Path, expected_hash: str):
        stat = path.stat()
        return self._load(path, expected_hash, (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))

    def images(self, patient: Patient, study: Study, organ: str):
        if patient.synthetic or patient.source != 'CancerVerse' or not re.fullmatch(r'CV_[0-9]{8}', study.study_id):
            raise ValueError('No local CancerVerse scan is configured for this record')
        if not study.scan_sha256:
            raise ValueError('Scan hash is required before displaying local image data')
        if organ not in study.coverage:
            raise ValueError('Organ is not within declared coverage')
        ct_path = inside(self.root, 'CancerVerse', study.study_id, 'ct.nii.gz')
        ct = self._read(ct_path, study.scan_sha256)
        # No hidden path input and no fabricated mask when annotation evidence is absent.
        lesions = [m for m in study.lesions if m.organ == organ and m.evidence.method == 'mask-volume']
        mask, mask_hash = None, None
        if lesions:
            relative = f'CancerVerse/{study.study_id}/segmentations/{MASK_NAMES[organ]}.nii.gz'
            if any(not re.fullmatch(re.escape(relative) + r'#component=[1-9][0-9]*', m.evidence.source) for m in lesions):
                raise ValueError('Mask reference does not match the imported study')
            hashes = {m.evidence.sha256 for m in lesions}
            if len(hashes) != 1:
                raise ValueError('Conflicting mask evidence hashes')
            mask_hash = hashes.pop()
            mask = self._read(inside(self.root, relative), mask_hash)
        return ct, mask, {'scan_sha256': study.scan_sha256, 'mask_sha256': mask_hash,
                          'notice': 'Measured source-grid image. Examinations are not registered. No predicted boundary is shown.'}

    def metadata(self, patient: Patient, study: Study, organ: str) -> dict:
        ct, mask, provenance = self.images(patient, study, organ)
        return {**geometry(ct), **provenance, 'overlay_available': mask is not None,
                'planes': list(PLANES)}

    def slice(self, patient: Patient, study: Study, organ: str, plane: str, index: int,
              center: float, width: float, opacity: float) -> dict:
        ct, mask, provenance = self.images(patient, study, organ)
        return {**render_slice(ct, plane, index, mask=mask, center=center, width=width, opacity=opacity), **provenance}
