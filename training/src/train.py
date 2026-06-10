from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.models import ConvNeXt_Tiny_Weights, ResNet18_Weights, convnext_tiny, resnet18


LABEL_TO_INDEX = {
    "not-filled": 0,
    "filled": 1,
}


@dataclass(frozen=True)
class ManifestRow:
    image_uri: str
    label: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a bubble binary classifier.")
    parser.add_argument("--train-csv", type=Path, required=True)
    parser.add_argument("--val-csv", type=Path, required=True)
    parser.add_argument("--test-csv", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True, help="Local image cache root.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", choices=("resnet18", "convnext_tiny"), required=True)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--early-stopping-patience",
        type=int,
        default=None,
        help="Stop when val_filled_f1 does not improve for this many consecutive epochs.",
    )
    parser.add_argument(
        "--early-stopping-min-delta",
        type=float,
        default=0.0,
        help="Minimum val_filled_f1 improvement required to reset early stopping patience.",
    )
    parser.add_argument("--profile", type=str, default=None, help="Unused in training, reserved for future expansion.")
    parser.add_argument("--s3-backup-uri", type=str, default=None, help="Optional S3 directory to upload outputs.")
    return parser.parse_args()


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Unsupported URI: {uri}")
    without_scheme = uri[len("s3://") :]
    bucket, _, key = without_scheme.partition("/")
    if not bucket or not key:
        raise ValueError(f"Invalid S3 URI: {uri}")
    return bucket, key


def s3_uri_to_local_path(cache_dir: Path, uri: str) -> Path:
    bucket, key = parse_s3_uri(uri)
    return cache_dir / bucket / Path(key)


def load_manifest(csv_path: Path) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            label_name = row["label"]
            if label_name not in LABEL_TO_INDEX:
                raise ValueError(f"Unknown label: {label_name}")
            rows.append(
                ManifestRow(
                    image_uri=row["image_uri"],
                    label=LABEL_TO_INDEX[label_name],
                )
            )
    return rows


class BubbleDataset(Dataset[tuple[torch.Tensor, int]]):
    def __init__(self, rows: list[ManifestRow], cache_dir: Path, image_size: int) -> None:
        self.rows = rows
        self.cache_dir = cache_dir
        self.transform = transforms.Compose(
            [
                transforms.Resize((image_size, image_size)),
                transforms.Grayscale(num_output_channels=3),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
            ]
        )

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        row = self.rows[index]
        path = s3_uri_to_local_path(self.cache_dir, row.image_uri)
        with Image.open(path) as image:
            tensor = self.transform(image)
        return tensor, row.label


def build_model(model_name: str) -> nn.Module:
    if model_name == "resnet18":
        model = resnet18(weights=ResNet18_Weights.DEFAULT)
        model.fc = nn.Linear(model.fc.in_features, 2)
        return model
    if model_name == "convnext_tiny":
        model = convnext_tiny(weights=ConvNeXt_Tiny_Weights.DEFAULT)
        model.classifier[2] = nn.Linear(model.classifier[2].in_features, 2)
        return model
    raise ValueError(f"Unsupported model: {model_name}")


def evaluate(model: nn.Module, loader: DataLoader[tuple[torch.Tensor, int]], device: torch.device) -> dict[str, float]:
    model.eval()
    loss_sum = 0.0
    total = 0
    criterion = nn.CrossEntropyLoss()
    tp = 0
    tn = 0
    fp = 0
    fn = 0

    with torch.no_grad():
        for inputs, targets in loader:
            inputs = inputs.to(device)
            targets = targets.to(device)
            logits = model(inputs)
            loss = criterion(logits, targets)
            preds = torch.argmax(logits, dim=1)

            batch_size = targets.size(0)
            loss_sum += float(loss.item()) * batch_size
            total += batch_size
            target_list = targets.cpu().tolist()
            pred_list = preds.cpu().tolist()
            for target, pred in zip(target_list, pred_list, strict=True):
                if target == 1 and pred == 1:
                    tp += 1
                elif target == 0 and pred == 0:
                    tn += 1
                elif target == 0 and pred == 1:
                    fp += 1
                elif target == 1 and pred == 0:
                    fn += 1

    accuracy = (tp + tn) / max(total, 1)
    filled_precision = tp / max(tp + fp, 1)
    filled_recall = tp / max(tp + fn, 1)
    filled_f1 = 0.0
    if filled_precision + filled_recall > 0:
        filled_f1 = 2 * filled_precision * filled_recall / (filled_precision + filled_recall)
    metrics = {
        "loss": loss_sum / max(total, 1),
        "accuracy": accuracy,
        "filled_precision": filled_precision,
        "filled_recall": filled_recall,
        "filled_f1": filled_f1,
    }
    return metrics


def upload_to_s3(local_path: Path, s3_uri: str) -> None:
    subprocess.run(["aws", "s3", "cp", str(local_path), s3_uri], check=True)


def sync_dir_to_s3(local_dir: Path, s3_uri: str) -> None:
    subprocess.run(["aws", "s3", "cp", str(local_dir), s3_uri, "--recursive"], check=True)


def main() -> int:
    args = parse_args()
    if args.early_stopping_patience is not None and args.early_stopping_patience < 1:
        raise ValueError("--early-stopping-patience must be at least 1 when provided.")
    set_seed(args.seed)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    train_rows = load_manifest(args.train_csv)
    val_rows = load_manifest(args.val_csv)
    test_rows = load_manifest(args.test_csv)

    train_dataset = BubbleDataset(train_rows, args.cache_dir, args.image_size)
    val_dataset = BubbleDataset(val_rows, args.cache_dir, args.image_size)
    test_dataset = BubbleDataset(test_rows, args.cache_dir, args.image_size)

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers, pin_memory=True)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers, pin_memory=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model(args.model).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    criterion = nn.CrossEntropyLoss()

    best_val_f1 = -1.0
    best_checkpoint_path = args.output_dir / "best.pt"
    history: list[dict[str, float | int]] = []
    best_epoch = 0
    epochs_without_improvement = 0
    stopped_early = False

    for epoch in range(1, args.epochs + 1):
        model.train()
        running_loss = 0.0
        total = 0

        for inputs, targets in train_loader:
            inputs = inputs.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)

            optimizer.zero_grad()
            logits = model(inputs)
            loss = criterion(logits, targets)
            loss.backward()
            optimizer.step()

            batch_size = targets.size(0)
            running_loss += float(loss.item()) * batch_size
            total += batch_size

        train_loss = running_loss / max(total, 1)
        val_metrics = evaluate(model, val_loader, device)
        epoch_metrics: dict[str, float | int] = {
            "epoch": epoch,
            "train_loss": train_loss,
            **val_metrics,
        }
        history.append(epoch_metrics)

        checkpoint_path = args.output_dir / f"epoch-{epoch:03d}.pt"
        torch.save(
            {
                "epoch": epoch,
                "model_name": args.model,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_metrics": val_metrics,
            },
            checkpoint_path,
        )

        improvement = val_metrics["filled_f1"] - best_val_f1
        if improvement > args.early_stopping_min_delta:
            best_val_f1 = val_metrics["filled_f1"]
            best_epoch = epoch
            epochs_without_improvement = 0
            shutil.copyfile(checkpoint_path, best_checkpoint_path)
        else:
            epochs_without_improvement += 1

        if args.s3_backup_uri:
            sync_dir_to_s3(args.output_dir, args.s3_backup_uri)

        print(
            f"epoch={epoch} train_loss={train_loss:.4f} "
            f"val_loss={val_metrics['loss']:.4f} val_acc={val_metrics['accuracy']:.4f} "
            f"val_filled_f1={val_metrics['filled_f1']:.4f}"
        )

        if (
            args.early_stopping_patience is not None
            and epochs_without_improvement >= args.early_stopping_patience
        ):
            stopped_early = True
            print(
                f"early_stopping_triggered epoch={epoch} best_epoch={best_epoch} "
                f"best_val_filled_f1={best_val_f1:.4f}"
            )
            break

    checkpoint = torch.load(best_checkpoint_path, map_location=device)
    model.load_state_dict(cast(dict[str, torch.Tensor], checkpoint["model_state_dict"]))
    test_metrics = evaluate(model, test_loader, device)

    metrics_path = args.output_dir / "metrics.json"
    with metrics_path.open("w", encoding="utf-8") as fp:
        json.dump(
            {
                "model": args.model,
                "train_rows": len(train_rows),
                "val_rows": len(val_rows),
                "test_rows": len(test_rows),
                "best_epoch": best_epoch,
                "best_val_filled_f1": best_val_f1,
                "stopped_early": stopped_early,
                "history": history,
                "test_metrics": test_metrics,
            },
            fp,
            ensure_ascii=False,
            indent=2,
        )

    if args.s3_backup_uri:
        sync_dir_to_s3(args.output_dir, args.s3_backup_uri)

    print(json.dumps({"model": args.model, "test_metrics": test_metrics}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
