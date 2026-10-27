"""CLA baseline and small CNN pipeline for the project's 100-question form.

This CLI expects human-verified A/B pairs and a ground-truth answer table.
It never infers labels from answer keys or creates missing labels.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.utils.class_weight import compute_class_weight
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from omr_geometry import read_image, rectify_sheet, row_crop, bubble_scores


CLASSES = ["1", "2", "3", "4", "5", "blank", "multiple", "ambiguous"]
CLASS_TO_INDEX = {label: index for index, label in enumerate(CLASSES)}


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def cla_label(scores: np.ndarray, fill_threshold: float, margin_threshold: float) -> tuple[str, float]:
    order = np.argsort(scores)[::-1]
    active = np.flatnonzero(scores >= fill_threshold)
    if len(active) == 0:
        return "blank", max(0.0, fill_threshold - float(scores[order[0]]))
    if len(active) > 1:
        return "multiple", float(scores[order[1]]) - fill_threshold
    margin = float(scores[order[0]] - scores[order[1]])
    if margin < margin_threshold:
        return "ambiguous", margin
    return str(int(order[0]) + 1), margin


def make_examples(
    inventory: pd.DataFrame,
    labels: pd.DataFrame,
    splits: pd.DataFrame,
    data_root: Path,
    conversion_map: dict[str, str],
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame, pd.DataFrame]:
    verified = inventory[inventory["pair_status"].eq("verified")].copy()
    holds_path = data_root / "data/metadata/pairing_review_holds.csv"
    if holds_path.exists():
        holds = pd.read_csv(holds_path, keep_default_na=False)
        pending = set(holds.loc[holds["review_status"].eq("pending"), "sheet_id"])
        held_sheets = pending & set(verified["sheet_id"])
        if held_sheets:
            raise ValueError(f"Resolve A/B pairing review before training: {sorted(held_sheets)}")
    if verified.empty:
        raise ValueError("No verified A/B pairs. Review pair_decisions.csv and apply it first.")
    pair_counts = verified.groupby("sheet_id")["capture_role"].agg(lambda values: sorted(values.tolist()))
    invalid = pair_counts[pair_counts.map(lambda roles: roles != ["A", "B"])]
    if not invalid.empty:
        raise ValueError(f"Verified sheets without one A and one B: {invalid.index.tolist()[:10]}")
    split_map = splits.set_index("sheet_id")["split"].to_dict()
    labels = labels.copy()
    labels["question_no"] = labels["question_no"].astype(int)
    label_map = labels.set_index(["sheet_id", "question_no"])["ground_truth"].astype(str).to_dict()

    crops, targets, metadata, cla_records = [], [], [], []
    failures = []
    for image in verified.to_dict("records"):
        sheet_id = image["sheet_id"]
        split = split_map.get(sheet_id)
        if split not in {"train", "validation", "test"}:
            raise ValueError(f"No split assigned to verified sheet {sheet_id}")
        source = data_root / image["relative_path"]
        image_started = time.perf_counter()
        metadata_start = len(metadata)
        cla_start = len(cla_records)
        try:
            raw = read_image(source, conversion_map, data_root)
            gray, centers, registration = rectify_sheet(raw, source_sheet_id=sheet_id)
        except Exception as error:
            failures.append({"image_id": image["image_id"], "path": str(source), "error": str(error)})
            continue
        for question_no in range(1, 101):
            raw_target = label_map.get((sheet_id, question_no), "")
            if pd.isna(raw_target):
                raw_target = ""
            if isinstance(raw_target, (float, np.floating)) and float(raw_target).is_integer():
                target = str(int(raw_target))
            else:
                target = str(raw_target).strip().lower()
            if target not in CLASS_TO_INDEX:
                raise ValueError(f"Missing/invalid ground truth for {sheet_id} question {question_no}: {target!r}")
            crops.append(row_crop(gray, question_no, centers))
            targets.append(CLASS_TO_INDEX[target])
            scores = bubble_scores(gray, question_no, centers)
            cla_records.append(
                {
                    "sheet_id": sheet_id,
                    "question_no": question_no,
                    "capture_role": image["capture_role"],
                    "split": split,
                    "ground_truth": target,
                    "registration_mode": registration['mode'],
                    "reference_sheet": registration.get('reference_sheet', ''),
                    "scores": scores,
                }
            )
            metadata.append(
                {
                    "sheet_id": sheet_id,
                    "question_no": question_no,
                    "capture_role": image["capture_role"],
                    "split": split,
                    "ground_truth": target,
                    "image_id": image["image_id"],
                    "registration_mode": registration['mode'],
                    "reference_sheet": registration.get('reference_sheet', ''),
                }
            )
        image_seconds = time.perf_counter() - image_started
        for row in metadata[metadata_start:]:
            row["processing_seconds"] = image_seconds
        for row in cla_records[cla_start:]:
            row["processing_seconds"] = image_seconds
    if failures:
        pd.DataFrame(failures).to_csv("image_failures.csv", index=False)
        raise ValueError(f"{len(failures)} images failed rectification; see image_failures.csv")
    return (
        np.stack(crops).astype(np.uint8),
        np.asarray(targets, dtype=np.int64),
        pd.DataFrame(metadata),
        pd.DataFrame(cla_records),
    )


class RowCNN(nn.Module):
    def __init__(self, num_classes: int = len(CLASSES)) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d((4, 8)),
        )
        self.classifier = nn.Sequential(nn.Flatten(), nn.Linear(64 * 4 * 8, 128), nn.ReLU(), nn.Dropout(0.25), nn.Linear(128, num_classes))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


def predict_cnn(model: nn.Module, crops: np.ndarray, device: torch.device, batch_size: int = 512) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    all_probs = []
    with torch.no_grad():
        for start in range(0, len(crops), batch_size):
            batch = torch.from_numpy(crops[start : start + batch_size, None].astype(np.float32) / 255.0).to(device)
            all_probs.append(torch.softmax(model(batch), dim=1).cpu().numpy())
    probs = np.concatenate(all_probs)
    indices = probs.argmax(axis=1)
    return indices, probs.max(axis=1)


def fit_cla_thresholds(records: pd.DataFrame) -> tuple[float, float]:
    validation = records[records["split"].eq("validation")]
    if validation.empty:
        raise ValueError("Validation split is empty; cannot select CLA thresholds.")
    best = (-1.0, 0.15, 0.08)
    score_rows = validation.to_dict("records")
    for fill in np.linspace(-0.02, 0.35, 30):
        for margin in np.linspace(0.02, 0.22, 15):
            predicted = [cla_label(row["scores"], float(fill), float(margin))[0] for row in score_rows]
            actual = [row["ground_truth"] for row in score_rows]
            accuracy = accuracy_score(actual, predicted)
            if accuracy > best[0]:
                best = (float(accuracy), float(fill), float(margin))
    return best[1], best[2]


def confidence_threshold(actual: np.ndarray, pred: np.ndarray, confidence: np.ndarray, target_precision: float = 0.99) -> float:
    candidates = sorted(set(confidence.tolist()))
    eligible = []
    for threshold in candidates:
        accepted = confidence >= threshold
        if accepted.any() and float((actual[accepted] == pred[accepted]).mean()) >= target_precision:
            eligible.append((float(accepted.mean()), float(threshold)))
    return max(eligible, key=lambda pair: pair[0])[1] if eligible else 1.01


def evaluate_rows(actual: list[str], predicted: list[str]) -> dict[str, object]:
    return {
        "accuracy": float(accuracy_score(actual, predicted)),
        "macro_f1": float(f1_score(actual, predicted, labels=CLASSES, average="macro", zero_division=0)),
        "classification_report": classification_report(actual, predicted, labels=CLASSES, output_dict=True, zero_division=0),
        "confusion_matrix_labels": CLASSES,
        "confusion_matrix": confusion_matrix(actual, predicted, labels=CLASSES).tolist(),
        "coverage": float(np.mean(np.asarray(predicted) != "ambiguous")),
    }


def workflow_predictions(frame: pd.DataFrame, confidence_cutoff: float | None = None) -> pd.DataFrame:
    output = []
    for (sheet_id, question_no), group in frame.groupby(["sheet_id", "question_no"], sort=False):
        indexed = group.set_index("capture_role")
        if "A" not in indexed.index or "B" not in indexed.index:
            raise ValueError(f"Missing A/B prediction for {sheet_id} question {question_no}")
        truth = str(indexed.loc["A", "ground_truth"])
        b_truth = str(indexed.loc["B", "ground_truth"])
        if truth != b_truth:
            raise ValueError(f"A/B ground truth differs for {sheet_id} question {question_no}")
        a_pred = str(indexed.loc["A", "predicted"])
        b_pred = str(indexed.loc["B", "predicted"])
        a_conf = float(indexed.loc["A", "confidence"])
        b_conf = float(indexed.loc["B", "confidence"])
        use_b = a_pred == "ambiguous" or (confidence_cutoff is not None and a_conf < confidence_cutoff)
        selected = b_pred if use_b else a_pred
        if use_b and confidence_cutoff is not None and b_conf < confidence_cutoff:
            selected = "ambiguous"
        output.append({"sheet_id": sheet_id, "question_no": int(question_no), "ground_truth": truth, "a_only": a_pred, "a_then_b": selected, "used_B": use_b})
    return pd.DataFrame(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("."))
    parser.add_argument("--inventory", type=Path, default=Path("data/metadata/image_inventory_verified.csv"))
    parser.add_argument("--labels", type=Path, default=Path("data/metadata/answer_labels.csv"))
    parser.add_argument("--splits", type=Path, default=Path("data/metadata/sheet_splits.csv"))
    parser.add_argument("--heic-map", type=Path, default=Path("data/metadata/heic_conversion_map.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20261025)
    args = parser.parse_args()
    set_seed(args.seed)

    inventory = pd.read_csv(args.data_root / args.inventory)
    labels = pd.read_csv(args.data_root / args.labels)
    splits = pd.read_csv(args.data_root / args.splits)
    conversion_map = {}
    map_path = args.data_root / args.heic_map
    if map_path.exists():
        mapping = pd.read_csv(map_path)
        conversion_map = dict(zip(mapping["source_relative_path"], mapping["normalized_relative_path"]))
    crops, targets, metadata, cla_records = make_examples(inventory, labels, splits, args.data_root, conversion_map)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    train_idx = np.flatnonzero(metadata["split"].eq("train").to_numpy())
    validation_idx = np.flatnonzero(metadata["split"].eq("validation").to_numpy())
    test_idx = np.flatnonzero(metadata["split"].eq("test").to_numpy())
    observed_classes = np.unique(targets[train_idx])
    class_weights = np.ones(len(CLASSES), dtype=np.float32)
    class_weights[observed_classes] = compute_class_weight("balanced", classes=observed_classes, y=targets[train_idx])

    model = RowCNN().to(device)
    loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(class_weights, dtype=torch.float32, device=device))
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    train_ds = TensorDataset(torch.from_numpy(crops[train_idx, None].astype(np.float32) / 255.0), torch.from_numpy(targets[train_idx]))
    train_loader = DataLoader(train_ds, batch_size=128, shuffle=True)
    for epoch in range(args.epochs):
        model.train()
        total_loss = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(x), y)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item())
        print(f"epoch {epoch + 1}/{args.epochs}: loss={total_loss / max(1, len(train_loader)):.4f}")

    val_pred, val_conf = predict_cnn(model, crops[validation_idx], device)
    cnn_cutoff = confidence_threshold(targets[validation_idx], val_pred, val_conf)
    test_pred, test_conf = predict_cnn(model, crops[test_idx], device)
    cnn_rows = metadata.iloc[test_idx].copy()
    cnn_rows["predicted"] = [CLASSES[index] if conf >= cnn_cutoff else "ambiguous" for index, conf in zip(test_pred, test_conf)]
    cnn_rows["confidence"] = test_conf

    cla_fill, cla_margin = fit_cla_thresholds(cla_records)
    cla_rows = cla_records[cla_records["split"].eq("test")].copy()
    cla_labels, cla_conf = [], []
    for scores in cla_rows["scores"]:
        label, confidence = cla_label(scores, cla_fill, cla_margin)
        cla_labels.append(label)
        cla_conf.append(confidence)
    cla_rows["predicted"] = cla_labels
    cla_rows["confidence"] = cla_conf

    results: dict[str, object] = {
        "cnn_validation_confidence_cutoff": cnn_cutoff,
        "cla_fill_threshold": cla_fill,
        "cla_margin_threshold": cla_margin,
        "device": str(device),
        "split_sheets": splits.groupby("split")["sheet_id"].nunique().to_dict(),
        "models": {},
    }
    test_timing = metadata.iloc[test_idx].groupby(["sheet_id", "capture_role"])["processing_seconds"].first().unstack()
    per_sheet_ab = test_timing[["A", "B"]].sum(axis=1)
    results["timing_seconds"] = {
        "mean_per_image": float(test_timing.stack().mean()),
        "mean_A_per_sheet": float(test_timing["A"].mean()),
        "mean_A_plus_B_per_sheet": float(per_sheet_ab.mean()),
    }
    for name, rows in [("cnn", cnn_rows), ("cla", cla_rows)]:
        work = workflow_predictions(rows, cnn_cutoff if name == "cnn" else None)
        truth = work["ground_truth"].astype(str).tolist()
        results["models"][name] = {
            "A_only": evaluate_rows(truth, work["a_only"].astype(str).tolist()),
            "A_then_B": evaluate_rows(truth, work["a_then_b"].astype(str).tolist()),
            "retake_rate": float(work["used_B"].mean()),
        }
        work.to_csv(args.output_dir / f"{name}_test_predictions.csv", index=False)
    (args.output_dir / "evaluation.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    torch.save(model.state_dict(), args.output_dir / "row_cnn.pt")
    print(json.dumps({"evaluation": str(args.output_dir / 'evaluation.json'), "model": str(args.output_dir / 'row_cnn.pt')}, indent=2))


if __name__ == "__main__":
    main()
