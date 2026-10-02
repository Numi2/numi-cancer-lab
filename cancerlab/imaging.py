"""Mask measurements in physical coordinates; connected components are not tracks."""
from __future__ import annotations
import hashlib, math
from pathlib import Path
import numpy as np
from scipy import ndimage
MAX_VOXELS = 128_000_000

def checked_affine(affine) -> np.ndarray:
    a=np.asarray(affine,dtype=np.float64)
    if a.shape!=(4,4) or not np.isfinite(a).all() or not np.allclose(a[3],[0,0,0,1]): raise ValueError("Expected a finite, homogeneous 4x4 voxel-to-RAS-mm affine")
    determinant=abs(float(np.linalg.det(a[:3,:3])))
    if not math.isfinite(determinant) or determinant<1e-9: raise ValueError("Singular or invalid spatial affine")
    return a

def components(mask, affine_mm, *, max_voxels:int=MAX_VOXELS)->list[dict]:
    a=checked_affine(affine_mm); mask=np.asarray(mask)
    if mask.ndim!=3 or min(mask.shape)<1 or mask.size>max_voxels: raise ValueError("Mask must be nonempty 3D and within the configured voxel limit")
    if mask.dtype.kind not in "buif" or not np.isfinite(mask).all() or not np.isin(mask,[0,1]).all(): raise ValueError("Expected a finite binary mask, not probability or instance labels")
    labels,count=ndimage.label(mask.astype(bool),structure=np.ones((3,3,3),dtype=bool)); counts=np.bincount(labels.ravel(),minlength=count+1); bounds=ndimage.find_objects(labels)
    voxel_ml=abs(float(np.linalg.det(a[:3,:3])))/1000.0; results=[]
    for number,region in enumerate(bounds,1):
        if region is None: continue
        local=labels[region]==number; centroid=np.asarray(ndimage.center_of_mass(local))+[r.start for r in region]; point=a@np.append(centroid,1)
        results.append({"component":number,"voxel_count":int(counts[number]),"volume_ml":float(counts[number]*voxel_ml),"centroid_ras_mm":tuple(float(v) for v in point[:3]),"bbox_ijk":tuple((r.start,r.stop) for r in region)})
    return results

def file_sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def load_nifti(path:Path, *, max_voxels:int=MAX_VOXELS):
    try: import nibabel as nib
    except ImportError as exc: raise ValueError("NIfTI import requires: python -m pip install -e '.[imaging]'") from exc
    image=nib.load(str(path),mmap=True)
    if len(image.shape)!=3 or min(image.shape)<1 or math.prod(image.shape)>max_voxels: raise ValueError("Expected a 3D NIfTI within the configured voxel limit")
    if image.header.get_xyzt_units()[0]!="mm": raise ValueError("Spatial units must explicitly be millimetres; no implicit conversion")
    if not (int(image.header['sform_code']) or int(image.header['qform_code'])): raise ValueError("A defined sform or qform is required; inferred orientation is refused")
    checked_affine(image.affine); return image

def measure_nifti(mask_path:Path, ct_image)->list[dict]:
    image=load_nifti(mask_path)
    if image.shape!=ct_image.shape or not np.allclose(image.affine,ct_image.affine,atol=1e-4,rtol=0): raise ValueError("CT and annotation grids differ; explicit registration/resampling is required")
    return components(np.asanyarray(image.dataobj),image.affine)
