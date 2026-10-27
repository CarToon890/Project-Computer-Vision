"""Create unconfirmed OMR proposals in bounded batches, preserving previous runs.

This writes proposals separately. It never writes answer_labels.csv.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from functools import lru_cache
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "data/metadata"
ASSETS = META / "answer_pilot_assets"
OUTPUT = META / "answer_pilot_proposals.json"
WIDTH, HEIGHT = 1000, 1333
REFERENCE = np.float32([[144.7, 1167.6], [891.8, 1160.1], [877.3, 76.5]])
METHOD = "marker-guided-bubble-reader-v1.4"


def components(gray: np.ndarray, threshold: int):
    _, _, stats, centers = cv2.connectedComponentsWithStats((gray < threshold).astype("uint8"), 8)
    return [(*map(float, centers[i]), *map(int, stats[i])) for i in range(1, len(stats))]


def align_markers(gray: np.ndarray, allow_clipped_top=False) -> np.ndarray:
    candidates = []
    for threshold in (45, 70, 100, 130):
        for cx, cy, x, y, w, h, area in components(gray, threshold):
            if 25 <= w <= 100 and 25 <= h <= 100 and .65 <= w / h <= 1.55 and area > 500:
                # Cropped dark background corners cannot establish the upper form marker.
                if not allow_clipped_top and cy < HEIGHT*.52 and (x <= 2 or y <= 2 or x+w >= WIDTH-2 or y+h >= HEIGHT-2):
                    continue
                if not any((cx - c[0]) ** 2 + (cy - c[1]) ** 2 < 64 for c in candidates):
                    candidates.append((cx, cy))
    top = [c for c in candidates if c[1] < HEIGHT * .52 and c[0] > WIDTH * .5]
    bottom = [c for c in candidates if c[1] > HEIGHT * .55]
    if not top or len(bottom) < 2:
        raise ValueError("Could not identify the three form markers.")
    triangles = []
    ratio = (REFERENCE[1, 1] - REFERENCE[2, 1]) / (REFERENCE[1, 0] - REFERENCE[0, 0])
    for bl in bottom:
        for br in bottom:
            span = br[0] - bl[0]
            if span < WIDTH * .35:
                continue
            for tr in top:
                if br[1] - tr[1] < HEIGHT * .35:
                    continue
                cost = (2 * abs(bl[1] - br[1]) + abs(tr[0] - br[0])
                        + .5 * abs(br[1] - tr[1] - ratio * span)) / span
                triangles.append((cost, bl, br, tr))
    if not triangles:
        raise ValueError("Bottom form markers are too close.")
    # Background textures can create squares on any edge; use the whole triangle.
    _, bl, br, tr = min(triangles)
    matrix = cv2.getAffineTransform(np.float32([bl, br, tr]), REFERENCE)
    return cv2.warpAffine(gray, matrix, (WIDTH, HEIGHT), borderValue=255)


def cluster_points(points, axis: int, tolerance: float):
    groups = []
    for point in sorted(points, key=lambda p: p[axis]):
        if not groups or point[axis] - np.mean([p[axis] for p in groups[-1]]) > tolerance:
            groups.append([point])
        else:
            groups[-1].append(point)
    return np.array([np.mean(group, axis=0) for group in groups])


def complete_marker_rail(points):
    """Recover at most one missing printed dash from the five-block spacing pattern."""
    if len(points) != 24:
        return points
    pattern = np.arange(25) + .8 * (np.arange(25)//5)
    fits=[]
    for missing in range(25):
        observed=np.delete(pattern,missing)
        fit=np.polyfit(observed,points[:,1],2)
        error=float(np.sqrt(np.mean((np.polyval(fit,observed)-points[:,1])**2)))
        fits.append((error,missing,float(np.polyval(fit,pattern[missing]))))
    fits.sort()
    if fits[0][0] > 2.5 or fits[1][0]-fits[0][0] < .75:
        return points
    _,index,y=fits[0]
    x=float(np.polyval(np.polyfit(points[:,1],points[:,0],1),y))
    return np.insert(points,index,[x,y],axis=0)


def locate_grid(gray: np.ndarray, relaxed=False):
    for threshold in (80, 105, 130, 155):
        parts = components(gray, threshold)
        dashes = [(cx, cy) for cx, cy, x, y, w, h, area in parts
                  if HEIGHT * (.16 if relaxed else .22) < cy < HEIGHT * (.95 if relaxed else .90) and 12 <= w <= 35
                  and 3 <= h <= 12 and w / h > 1.8 and area > 40]
        left = cluster_points([p for p in dashes if p[0] < WIDTH * (.38 if relaxed else .22)], 1, 12)
        if len(left) != 25:
            # Perspective may move the top of the left marker rail inward.
            left = cluster_points([p for p in dashes if p[0] < WIDTH * (.43 if relaxed else .27)], 1, 12)
        right = cluster_points([p for p in dashes if p[0] > WIDTH * (.72 if relaxed else .85)], 1, 12)
        if relaxed:
            left,right=complete_marker_rail(left),complete_marker_rail(right)
        if len(left) != 25 or len(right) != 25:
            continue
        first_y = float((left[0, 1] + right[0, 1]) / 2)
        last_y = float((left[-1, 1] + right[-1, 1]) / 2)
        bars = [(cx, cy) for cx, cy, x, y, w, h, area in parts
                if WIDTH * .14 < cx < WIDTH * .87 and 3 <= w <= 13
                and 12 <= h <= 36 and h / w > 1.7 and area > 40]
        top = cluster_points([p for p in bars if first_y - 85 < p[1] < first_y - 12], 0, 9)
        bottom = cluster_points([p for p in bars if last_y + 20 < p[1] < last_y + 120], 0, 9)
        if len(top) != 20 or len(bottom) != 20:
            def rail_y(x, row):
                fraction = (x - left[row, 0]) / (right[row, 0] - left[row, 0])
                return left[row, 1] + fraction * (right[row, 1] - left[row, 1])
            top = cluster_points([p for p in bars if rail_y(p[0], 0) - 85 < p[1] < rail_y(p[0], 0) - 12], 0, 9)
            bottom = cluster_points([p for p in bars if rail_y(p[0], -1) + 20 < p[1] < rail_y(p[0], -1) + 120], 0, 9)
        if len(top) != 20 or len(bottom) != 20:
            continue
        points = []
        for column in range(4):
            for row in range(25):
                choices = []
                row_y = (left[row, 1] + right[row, 1]) / 2
                for option in range(5):
                    i = column * 5 + option
                    fraction = (row_y - top[i, 1]) / (bottom[i, 1] - top[i, 1])
                    x = top[i, 0] + fraction * (bottom[i, 0] - top[i, 0])
                    across = (x - left[row, 0]) / (right[row, 0] - left[row, 0])
                    y = left[row, 1] + across * (right[row, 1] - left[row, 1])
                    choices.append((float(x), float(y)))
                points.append(choices)
        return points
    raise ValueError("Expected 25 row markers on each side and 20 option markers at top/bottom.")


def score_options(gray: np.ndarray, centers):
    yy, xx = np.ogrid[-13:14, -13:14]
    radius = xx * xx + yy * yy
    disk = radius <= 5.5 ** 2
    ring = (radius >= 10 ** 2) & (radius <= 13 ** 2)
    scores = []
    for cx, cy in centers:
        x, y = round(cx), round(cy)
        patch = gray[y - 13:y + 14, x - 13:x + 14]
        if patch.shape != disk.shape:
            raise ValueError("A bubble center lies outside the readable page.")
        scores.append(float((patch[ring].mean() - patch[disk].mean()) / 255))
    return scores


def classify(scores):
    order = np.argsort(scores)[::-1]
    maximum, second = float(scores[order[0]]), float(scores[order[1]])
    baseline = float(np.median(np.asarray(scores)[order[2:]]))
    if maximum < .14 and maximum - second < .08:
        return "blank"
    if second > .18 and second - baseline > .14:
        return "multiple"
    return str(int(order[0]) + 1)


def load_gray(row):
    source = ROOT / row["relative_path"]
    if source.suffix.lower() in {".heic", ".heif"}:
        source = META / "annotation_previews" / f"{row['image_id']}.jpg"
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if image.width > image.height:
            image = image.transpose(Image.Transpose.ROTATE_270)
        image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    return gray


def normalize_illumination(gray, size=61):
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((size, size), np.uint8))
    return cv2.divide(gray, np.maximum(background, 1), scale=245)


@lru_cache(maxsize=1)
def registration_reference():
    """Use an image's printed form geometry only, never its answer labels."""
    with (META / "image_inventory_verified.csv").open(newline="", encoding="utf-8-sig") as stream:
        candidates = [r for r in csv.DictReader(stream) if r['pair_status'] == 'verified' and r['capture_role'] == 'B']
    for row in sorted(candidates, key=lambda r: r['sheet_id']):
        gray = load_gray(row)
        try:
            aligned = align_markers(gray)
            centers = locate_grid(aligned)
        except ValueError:
            continue
        mask = np.full_like(aligned, 255)
        for points in centers:
            for cx, cy in points:
                cv2.circle(mask, (round(cx), round(cy)), 15, 0, -1)
        sift = cv2.SIFT_create(nfeatures=6500)
        keypoints, descriptors = sift.detectAndCompute(aligned, mask)
        return aligned, centers, keypoints, descriptors, mask
    raise ValueError('No registered form reference available.')


def register_upright(gray):
    for mode, work in [('raw', gray), ('flat61', normalize_illumination(gray)),
                       ('flat101', normalize_illumination(gray, 101))]:
        try:
            aligned = align_markers(work)
            return aligned, locate_grid(aligned), {'mode': mode}
        except ValueError:
            pass
    # A spread of matching printed features is required before using template geometry.
    _, centers, reference_keys, reference_descriptors, _ = registration_reference()
    work = normalize_illumination(gray)
    keys, descriptors = cv2.SIFT_create(nfeatures=6500).detectAndCompute(work, None)
    if descriptors is None or reference_descriptors is None:
        raise ValueError('No usable form markers or printed feature matches.')
    matches = cv2.BFMatcher().knnMatch(descriptors, reference_descriptors, k=2)
    good = [pair[0] for pair in matches if len(pair) == 2 and pair[0].distance < .68 * pair[1].distance]
    if len(good) < 40:
        raise ValueError('Insufficient printed form matches for registration.')
    src = np.float32([keys[m.queryIdx].pt for m in good])
    dst = np.float32([reference_keys[m.trainIdx].pt for m in good])
    matrix, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 3)
    if matrix is None:
        raise ValueError('Printed form registration failed.')
    points = dst[inliers.ravel().astype(bool)]
    if len(points) < 40:
        raise ValueError('Printed form matches have insufficient supported points.')
    coverage = cv2.contourArea(cv2.convexHull(points)) / (WIDTH * HEIGHT)
    if len(points) < 40 or coverage < .35 or (points[:, 1] < 330).sum() < 6 or (points[:, 1] > 1050).sum() < 6:
        raise ValueError('Printed form matches do not span enough of the page.')
    aligned = cv2.warpPerspective(work, matrix, (WIDTH, HEIGHT), borderValue=255)
    try:
        centers = locate_grid(aligned)
    except ValueError:
        # The well-spread printed-feature homography already maps this same form.
        pass
    return aligned, centers, {'mode': 'printed-feature-homography', 'inliers': len(points), 'coverage': round(coverage, 4)}


def register_form(gray):
    try:
        return register_upright(gray)
    except ValueError as original_error:
        try:
            aligned, centers, registration = register_upright(np.rot90(gray, 2).copy())
            return aligned, centers, {**registration, 'input_rotation': 180}
        except ValueError:
            raise original_error


def read_form(row, sheet, role):
    aligned, centers, registration = register_form(load_gray(row))
    output = {"image_id": row["image_id"], "rows": [], "error": "", "registration": registration}
    overlay = cv2.cvtColor(aligned, cv2.COLOR_GRAY2BGR)
    sprite = Image.new("L", (600, 90 * 100), 255)
    for question, points in enumerate(centers, 1):
        scores = score_options(aligned, points)
        proposed = classify(scores)
        ranked = sorted(scores, reverse=True)
        output["rows"].append({"question_no": question, "proposed": proposed,
                               "uncertain": ranked[0] < .22 or ranked[0] - ranked[1] < .12 or registration['mode'] == 'printed-feature-homography',
                               "scores": [round(v, 4) for v in scores]})
        for cx, cy in points:
            cv2.circle(overlay, (round(cx), round(cy)), 10, (0, 140, 255), 1)
        x0 = round(min(p[0] for p in points) - 48)
        x1 = round(max(p[0] for p in points) + 14)
        y0 = round(min(p[1] for p in points) - 13)
        y1 = round(max(p[1] for p in points) + 14)
        crop = Image.fromarray(aligned[max(0, y0):y1, max(0, x0):x1])
        crop.thumbnail((600, 90), Image.Resampling.LANCZOS)
        # Enlarge the row so the full width remains easy to inspect in the sidebar.
        crop = crop.resize((600, 90), Image.Resampling.LANCZOS)
        sprite.paste(crop, (0, (question - 1) * 90))
    sprite_path = ASSETS / f"{sheet}_{role}_rows.jpg"
    sprite.save(sprite_path, quality=92)
    overlay_path = ASSETS / f"{sheet}_{role}_overlay.jpg"
    cv2.imencode(".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tofile(overlay_path)
    output["sprite"] = sprite_path.relative_to(META).as_posix()
    output["overlay"] = overlay_path.relative_to(META).as_posix()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--start", help="First verified sheet ID in a new batch, e.g. S0011.")
    parser.add_argument("--end", help="Last verified sheet ID in a new batch, e.g. S0035.")
    parser.add_argument("--force", action="store_true", help="Replace an earlier pilot before human review begins.")
    args = parser.parse_args()
    if bool(args.start) != bool(args.end):
        raise SystemExit("Provide both --start and --end for a new batch.")
    if not args.start and not 1 <= args.limit <= 10:
        raise SystemExit("The initial pilot is limited to 1-10 verified sheets.")
    with (META / "image_inventory_verified.csv").open(newline="", encoding="utf-8-sig") as stream:
        rows = [r for r in csv.DictReader(stream) if r["pair_status"] == "verified"]
    known = sorted({r["sheet_id"] for r in rows})
    if args.start:
        if args.start not in known or args.end not in known or args.start > args.end:
            raise SystemExit("Batch bounds must be current verified sheet IDs in ascending order.")
        selected = [sheet for sheet in known if args.start <= sheet <= args.end]
        if len(selected) > 25:
            raise SystemExit("Prepare at most 25 sheets per new batch.")
    else:
        selected = known[:args.limit]
    if not selected:
        raise SystemExit("No verified sheets selected.")
    hold_path = META / 'pairing_review_holds.csv'
    if hold_path.exists():
        with hold_path.open(newline='', encoding='utf-8-sig') as stream:
            pending = {r['sheet_id'] for r in csv.DictReader(stream) if r['review_status'] == 'pending'}
        if pending & set(selected):
            raise SystemExit('Resolve A/B pairing holds before reading selected sheets.')
    result = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {"version": 2, "method": METHOD, "sheets": {}, "batches": []}
    previous_batches = result.get("batches", [])
    if result["sheets"] and not previous_batches:
        old_ids = sorted(result["sheets"])
        previous_batches = [{"id": f"{old_ids[0]}-{old_ids[-1]}", "sheet_ids": old_ids,
                             "method": result["method"], "run_id": result["run_id"]}]
    overlap = set(selected) & set(result["sheets"])
    if overlap and not args.force:
        raise SystemExit("Proposals already exist for selected sheets. Keep them fixed during human review.")
    if overlap and any(set(batch["sheet_ids"]) & set(selected) and set(batch["sheet_ids"]) != set(selected) for batch in previous_batches):
        raise SystemExit("Replacement must cover exactly one existing batch; partial replacements are not allowed.")
    ASSETS.mkdir(exist_ok=True)
    new_sheets = {}
    for sheet in selected:
        new_sheets[sheet] = {}
        for role in ("A", "B"):
            row = next(r for r in rows if r["sheet_id"] == sheet and r["capture_role"] == role)
            try:
                read = read_form(row, sheet, role)
            except (ValueError, OSError) as error:
                read = {"image_id": row["image_id"], "rows": [], "error": str(error)}
            new_sheets[sheet][role] = read
            print(f"{sheet} {role}: {len(read['rows'])}/100 proposals {read['error']}", flush=True)
    batch_id = f"{selected[0]}-{selected[-1]}"
    batch_run = hashlib.sha256(json.dumps({"method": METHOD, "sheets": new_sheets}, sort_keys=True).encode()).hexdigest()[:16]
    result["version"] = 2
    result["sheets"].update(new_sheets)
    result["sheet_ids"] = sorted(result["sheets"])
    result["batches"] = [batch for batch in previous_batches if batch["id"] != batch_id]
    result["batches"].append({"id": batch_id, "sheet_ids": selected, "method": METHOD, "run_id": batch_run})
    result["active_batch"] = batch_id
    result["run_id"] = hashlib.sha256(json.dumps(result["batches"], sort_keys=True).encode()).hexdigest()[:16]
    if OUTPUT.exists():
        backups = ROOT / "presentation_build/annotation_pilot"
        backups.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OUTPUT, backups / f"proposals_before_batch_{datetime.now():%Y%m%d_%H%M%S_%f}.json")
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved unconfirmed pilot proposals to {OUTPUT}")


if __name__ == "__main__":
    main()
