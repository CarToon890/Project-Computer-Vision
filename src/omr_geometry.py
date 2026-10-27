"""Marker-based form registration shared by CLA scores and CNN row crops."""
from pathlib import Path
import sys
import csv
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageOps

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import build_answer_pilot as reader


def read_image(path: Path, conversion_map: dict[str, str], data_root: Path) -> np.ndarray:
    root = data_root.resolve()
    if reader.ROOT != root:
        reader.ROOT, reader.META = root, root / 'data/metadata'
        reader.registration_reference.cache_clear()
        train_references.cache_clear()
    source = path
    if path.suffix.lower() in {'.heic', '.heif'}:
        relative = path.resolve().relative_to(data_root.resolve()).as_posix()
        normalized = conversion_map.get(relative)
        if not normalized:
            raise ValueError(f'HEIC image has no normalized JPEG mapping: {path}')
        source = data_root / normalized
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        if image.width > image.height:
            image = image.transpose(Image.Transpose.ROTATE_270)
        return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


@lru_cache(maxsize=1)
def train_references():
    """Precomputed geometry from other Train sheets; no answer labels are read."""
    portable = reader.META / 'form_references.npz'
    if portable.is_file():
        from omr_form_references import load_references
        return load_references(portable)[1]
    with (reader.META / 'sheet_splits.csv').open(encoding='utf-8-sig', newline='') as f:
        train = {r['sheet_id'] for r in csv.DictReader(f) if r['split'] == 'train'}
    with (reader.META / 'image_inventory_verified.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['pair_status'] == 'verified'
                and r['capture_role'] == 'B' and r['sheet_id'] in train]
    result = []
    sift = cv2.SIFT_create(nfeatures=6500)
    for row in rows:
        try:
            reference, centers, _ = reader.register_form(reader.load_gray(row))
        except ValueError:
            continue
        reference = reader.normalize_illumination(reference)
        keys, descriptors = sift.detectAndCompute(reference, None)
        if descriptors is not None:
            result.append((row['sheet_id'], centers, keys, descriptors))
        if len(result) == 3:
            break
    return result


def train_form_fallback(gray, source_sheet_id):
    sift = cv2.SIFT_create(nfeatures=6500)
    for rotation, work in [(0, gray), (180, np.rot90(gray, 2).copy())]:
        work = reader.normalize_illumination(work)
        keys, descriptors = sift.detectAndCompute(work, None)
        if descriptors is None:
            continue
        for sid, centers, reference_keys, reference_descriptors in train_references():
            if sid == source_sheet_id:
                continue
            matches = cv2.BFMatcher().knnMatch(descriptors, reference_descriptors, k=2)
            good = [pair[0] for pair in matches if len(pair) == 2 and pair[0].distance < .68*pair[1].distance]
            if len(good) < 40:
                continue
            src = np.float32([keys[m.queryIdx].pt for m in good])
            dst = np.float32([reference_keys[m.trainIdx].pt for m in good])
            cv2.setRNGSeed(20261025)
            matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3)
            if matrix is None or mask is None or not np.isfinite(matrix).all():
                continue
            pts = dst[mask.ravel().astype(bool)]
            if len(pts) < 40:
                continue
            coverage = cv2.contourArea(cv2.convexHull(pts))/(reader.WIDTH*reader.HEIGHT)
            if len(pts) < 40 or coverage < .35 or (pts[:, 1] < 330).sum() < 6 or (pts[:, 1] > 1050).sum() < 6:
                continue
            # Warp only the source pixels. Reference marks/labels never fill answers.
            aligned = cv2.warpPerspective(work, matrix, (reader.WIDTH, reader.HEIGHT), borderValue=255)
            try:
                local_centers = reader.locate_grid(aligned)
            except ValueError:
                local_centers = centers
            return aligned, local_centers, {'mode': 'train-form-homography',
                'reference_sheet': sid, 'inliers': len(pts), 'coverage': round(coverage, 4),
                'input_rotation': rotation}
    raise ValueError('No spatially supported form registration; no answer crops generated.')


def paper_candidates(gray):
    """Enlarge a visible convex paper boundary before locating printed markers."""
    blurred = cv2.GaussianBlur(gray, (5,5), 0)
    _, white = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    masks = [cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((17,17),np.uint8)),
             cv2.morphologyEx(cv2.Canny(blurred,40,130),cv2.MORPH_CLOSE,np.ones((7,7),np.uint8))]
    seen=[]
    for mask in masks:
        contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:8]:
            if not .15*gray.size < cv2.contourArea(contour) < .995*gray.size:
                continue
            quad=cv2.approxPolyDP(contour,.025*cv2.arcLength(contour,True),True)
            if len(quad)!=4 or not cv2.isContourConvex(quad):
                continue
            pts=quad[:,0].astype(np.float32)
            center=pts.mean(0)
            pts=pts[np.argsort(np.arctan2(pts[:,1]-center[1],pts[:,0]-center[0]))]
            pts=np.roll(pts,-int(np.argmin(pts.sum(1))),axis=0)
            width=np.linalg.norm(pts[0]-pts[1])+np.linalg.norm(pts[2]-pts[3])
            height=np.linalg.norm(pts[1]-pts[2])+np.linalg.norm(pts[3]-pts[0])
            if width>height:pts=np.roll(pts,-1,axis=0)
            if any(np.mean(np.linalg.norm(pts-previous,axis=1))<20 for previous in seen):
                continue
            seen.append(pts)
            matrix=cv2.getPerspectiveTransform(pts,np.float32([[0,0],[reader.WIDTH-1,0],
                [reader.WIDTH-1,reader.HEIGHT-1],[0,reader.HEIGHT-1]]))
            yield cv2.warpPerspective(gray,matrix,(reader.WIDTH,reader.HEIGHT),borderValue=255)
            if len(seen)>=3:return


def relaxed_marker_registration(gray):
    """Account for perspective that moves the upper marker rail inward."""
    for rotation,image in [(0,gray),(180,np.rot90(gray,2).copy())]:
        for mode,work in [('raw',image),('flat61',reader.normalize_illumination(image)),
                          ('flat101',reader.normalize_illumination(image,101))]:
            try:
                aligned=reader.align_markers(work)
                centers=reader.locate_grid(aligned,relaxed=True)
                if any(not (14<=x<reader.WIDTH-14 and 14<=y<reader.HEIGHT-14) for points in centers for x,y in points):
                    continue
                return aligned,centers,{'mode':'relaxed-marker-grid','illumination':mode,'input_rotation':rotation}
            except ValueError:
                continue
    # A genuine upper marker can be partly cut by the photo edge. This last
    # recovery requires the original strict 25-row/20-column-bar grid support.
    for rotation,image in [(0,gray),(180,np.rot90(gray,2).copy())]:
        for mode,work in [('raw',image),('flat61',reader.normalize_illumination(image)),
                          ('flat101',reader.normalize_illumination(image,101))]:
            try:
                aligned=reader.align_markers(work,allow_clipped_top=True)
                centers=reader.locate_grid(aligned)
                if any(not (14<=x<reader.WIDTH-14 and 14<=y<reader.HEIGHT-14) for points in centers for x,y in points):
                    continue
                return aligned,centers,{'mode':'clipped-marker-strict-grid','illumination':mode,'input_rotation':rotation}
            except ValueError:
                continue
    raise ValueError('No spatially supported form registration; no answer crops generated.')


def grid_alignment(centers):
    grid=np.asarray(centers,dtype=np.float32).reshape(4,25,5,2)
    row_spans=[float(np.ptp(grid[:,row,:,1])) for row in range(25)]
    group_spans=[float(np.ptp(grid[col,row,:,1])) for col in range(4) for row in range(25)]
    column_spans=[float(np.ptp(grid[col,:,option,0])) for col in range(4) for option in range(5)]
    return {'max_row_tilt_px':max(row_spans),'p95_group_tilt_px':float(np.percentile(group_spans,95)),
            'max_column_slant_px':max(column_spans)}


def rectify_answer_plane(gray,centers,registration):
    """Apply the projective warp to source pixels and coordinates before either reader."""
    points=np.asarray(centers,dtype=np.float32)
    if points.shape!=(100,5,2) or not np.isfinite(points).all():
        raise ValueError('A complete finite answer grid is required for perspective correction.')
    before=grid_alignment(points)
    if before['max_row_tilt_px']<=1.5 and before['max_column_slant_px']<=2.:
        return gray,centers,{**registration,'perspective_corrected':False,'page_aligned':True,
            'alignment_before':before,'alignment_after':before,'alignment_policy':'already-aligned-within-tolerance',
            'row_alignment_applied':any(float(np.ptp(row[:,1]))>1. for row in points)}
    grid=points.reshape(4,25,5,2)
    source=np.float32([grid[0,0,0],grid[3,0,4],grid[3,24,4],grid[0,24,0]])
    if not cv2.isContourConvex(source) or cv2.contourArea(source)<40000:
        raise ValueError('Answer-plane corners do not form a supported convex page region.')
    destination=np.float32([[210,360],[845,360],[845,1110],[210,1110]])
    matrix=cv2.getPerspectiveTransform(source,destination)
    if not np.isfinite(matrix).all() or abs(np.linalg.det(matrix))<1e-8:
        raise ValueError('Perspective transformation is not stable.')
    transformed=cv2.perspectiveTransform(points.reshape(-1,1,2),matrix).reshape(100,5,2)
    if any(not (14<=x<reader.WIDTH-14 and 14<=y<reader.HEIGHT-14) for row in transformed for x,y in row):
        raise ValueError('Perspective-corrected bubbles fall outside the page.')
    corrected=cv2.warpPerspective(gray,matrix,(reader.WIDTH,reader.HEIGHT),flags=cv2.INTER_CUBIC,borderValue=255)
    after=grid_alignment(transformed)
    return corrected,transformed.tolist(),{**registration,'perspective_corrected':True,
        'page_aligned':after['p95_group_tilt_px']<=2.,'alignment_before':before,'alignment_after':after,
        'row_alignment_applied':any(float(np.ptp(row[:,1]))>1. for row in transformed),
        'alignment_policy':'answer-plane-four-corner-homography','answer_plane_source_corners':source.tolist(),
        'perspective_matrix':matrix.tolist()}


def locate_form_geometry(gray,source_sheet_id):
    """Locate actual printed anchors; prefer marker-supported grids to unwarped grids."""
    try:
        return reader.register_form(gray)
    except ValueError:
        pass
    try:
        return relaxed_marker_registration(gray)
    except ValueError:
        pass
    try:
        return train_form_fallback(gray,source_sheet_id)
    except ValueError:
        pass
    for paper,boundary in [(p,True) for p in paper_candidates(gray)]+[(gray,False)]:
        try:
            if boundary:
                try:
                    aligned,centers,registration=reader.register_form(paper)
                    return aligned,centers,{**registration,'paper_boundary_rectified':True}
                except ValueError:
                    pass
            centers=reader.locate_grid(paper,relaxed=True)
            bottom=max(y for points in centers for x,y in points)
            left=min(x for points in centers for x,y in points);right=max(x for points in centers for x,y in points)
            squares=[(cx,cy) for cx,cy,x,y,w,h,area in reader.components(paper,100)
                     if 25<=w<=100 and 25<=h<=100 and .65<=w/h<=1.55 and area>500 and cy>bottom+10]
            if not any(x<left for x,y in squares) or not any(x>right for x,y in squares):
                raise ValueError('Direct grid requires both lower form markers to establish orientation.')
            return paper,centers,{'mode':'detected-grid','paper_boundary_rectified':boundary}
        except ValueError:
            continue
    # Uneven lighting can hide a printed rail even when the paper is almost flat.
    # This recovery is reached only after all previous registration paths fail.
    for illumination,work in [('flat61',reader.normalize_illumination(gray)),('flat101',reader.normalize_illumination(gray,101))]:
        try:
            centers=reader.locate_grid(work,relaxed=True)
            bottom=max(y for points in centers for x,y in points)
            left=min(x for points in centers for x,y in points);right=max(x for points in centers for x,y in points)
            squares=[(cx,cy) for cx,cy,x,y,w,h,area in reader.components(work,100)
                if 25<=w<=100 and 25<=h<=100 and .65<=w/h<=1.55 and area>500 and cy>bottom+10]
            if any(x<left for x,y in squares) and any(x>right for x,y in squares):
                return work,centers,{'mode':'direct-normalized-grid','illumination':illumination}
        except ValueError:
            continue
    raise ValueError('No spatially supported form registration; no answer crops generated.')


def rectify_sheet(image, source_sheet_id=None):
    if image is None or image.ndim != 3 or image.shape[2] != 3 or not image.size:
        raise ValueError('Expected a nonempty BGR source image.')
    rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    rgb = rgb.resize((reader.WIDTH, reader.HEIGHT), Image.Resampling.LANCZOS)
    gray = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2GRAY)
    aligned,centers,registration=locate_form_geometry(gray,source_sheet_id)
    if len(centers) != 100 or any(len(row) != 5 for row in centers):
        raise ValueError('Registration must locate all 100 rows and five options.')
    return rectify_answer_plane(aligned,centers,registration)


def question_centers(centers, question_no):
    if not 1 <= question_no <= 100 or len(centers) != 100:
        raise ValueError('Question must be in 1..100 on a registered 100-row form.')
    return centers[question_no-1]


def bubble_scores(gray, question_no, centers):
    points=question_centers(centers,question_no)
    row,local=straight_row_view(gray,points)
    return np.asarray(reader.score_options(row,local) if row is not None else reader.score_options(gray,points),dtype=np.float32)


def straight_row_view(gray,points,left_padding=14):
    """The same locally straightened source pixels are used by CNN and CLA."""
    points=np.asarray(points,dtype=np.float32)
    if float(np.ptp(points[:,1]))<=1.:
        return None,None
    direction=points[-1]-points[0];length=float(np.linalg.norm(direction))
    if length<40 or direction[0]<=0:raise ValueError('Answer choices do not define a stable ordered row.')
    unit=direction/length;normal=np.float32([-unit[1],unit[0]])
    first=points[0]-unit*left_padding;last=points[-1]+unit*14
    source=np.float32([first-normal*14,last-normal*14,last+normal*14,first+normal*14])
    # width = choice span + the requested left padding + 14 pixels right padding.
    width=round(length)+left_padding+14
    target=np.float32([[0,0],[width-1,0],[width-1,28],[0,28]])
    matrix=cv2.getPerspectiveTransform(source,target)
    row=cv2.warpPerspective(gray,matrix,(width,29),flags=cv2.INTER_CUBIC,borderValue=255)
    local=cv2.perspectiveTransform(points.reshape(-1,1,2),matrix).reshape(5,2).tolist()
    return row,local


def display_row(gray,question_no,centers):
    points=question_centers(centers,question_no)
    row,_=straight_row_view(gray,points,left_padding=48)
    if row is not None:return row
    x1=max(0,round(min(x for x,y in points)-48));x2=min(gray.shape[1],round(max(x for x,y in points)+15))
    y1=max(0,round(min(y for x,y in points)-14));y2=min(gray.shape[0],round(max(y for x,y in points)+15))
    return gray[y1:y2,x1:x2]


def row_crop(gray, question_no, centers):
    points = question_centers(centers, question_no)
    straight,_=straight_row_view(gray,points)
    if straight is not None:return cv2.resize(straight,(160,32),interpolation=cv2.INTER_AREA)
    x1 = max(0, round(min(x for x, y in points))-14)
    x2 = min(gray.shape[1], round(max(x for x, y in points))+15)
    y1 = max(0, round(min(y for x, y in points))-14)
    y2 = min(gray.shape[0], round(max(y for x, y in points))+15)
    crop = gray[y1:y2, x1:x2]
    if not crop.size:
        raise ValueError('Registered answer row lies outside the source image.')
    return cv2.resize(crop, (160, 32), interpolation=cv2.INTER_AREA)
