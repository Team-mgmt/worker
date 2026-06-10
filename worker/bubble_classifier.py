from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import aiofiles
import botocore.exceptions
import numpy as np
from PIL import Image

from .paths import CACHE_DIR

if TYPE_CHECKING:
    from typing import Any as S3Client

try:
    import torch
    from torch import nn
    from torchvision import transforms
    from torchvision.models import resnet18
except Exception as exc:  # pragma: no cover - exercised only in non-ML runtimes
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    transforms = None  # type: ignore[assignment]
    resnet18 = None  # type: ignore[assignment]
    _TORCH_IMPORT_ERROR: Exception | None = exc
else:
    _TORCH_IMPORT_ERROR = None


_S3_NOT_FOUND_CODES = {"NoSuchKey", "404", "NotFound"}
_MODEL_CACHE_LOCK = asyncio.Lock()
_MODEL_CACHE: dict[str, "ResNet18BubbleClassifier"] = {}


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Unsupported model URI: {uri}")
    without_scheme = uri[len("s3://") :]
    bucket, _, key = without_scheme.partition("/")
    if not bucket or not key:
        raise ValueError(f"Invalid S3 model URI: {uri}")
    return bucket, key


def _model_cache_path(model_uri: str) -> Path:
    suffix = Path(model_uri).suffix or ".pt"
    digest = hashlib.sha256(model_uri.encode("utf-8")).hexdigest()
    return Path(CACHE_DIR) / "bubble_classifier" / f"{digest}{suffix}"


async def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    async with aiofiles.open(tmp, "wb") as fp:
        await fp.write(content)
    os.replace(tmp, path)


async def _materialize_model_file(client: S3Client, model_uri: str) -> Path:
    if not model_uri.startswith("s3://"):
        return Path(model_uri)

    local_path = _model_cache_path(model_uri)
    if local_path.exists():
        return local_path

    bucket, key = _parse_s3_uri(model_uri)
    try:
        response = await client.get_object(Bucket=bucket, Key=key)
    except botocore.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in _S3_NOT_FOUND_CODES:
            raise FileNotFoundError(f"Bubble classifier model not found: {model_uri}") from exc
        raise
    body = await response["Body"].read()
    await _atomic_write_bytes(local_path, body)
    return local_path


@dataclass(frozen=True)
class ResNet18BubbleClassifier:
    model_uri: str
    model: Any
    device: Any
    transform: Any

    def predict_filled_probability(self, image: np.ndarray) -> float:
        if image.ndim != 2:
            raise ValueError(f"Expected grayscale bubble crop, got shape={image.shape}")

        pil_image = Image.fromarray(image)
        tensor = self.transform(pil_image).unsqueeze(0).to(self.device)
        with torch.no_grad():
            logits = self.model(tensor)
            probabilities = torch.softmax(logits, dim=1)
        return float(probabilities[0, 1].item())


async def get_or_load_resnet18_bubble_classifier(client: S3Client, model_uri: str) -> ResNet18BubbleClassifier:
    if _TORCH_IMPORT_ERROR is not None:  # pragma: no cover - depends on runtime environment
        raise RuntimeError("Torch / torchvision is unavailable in this worker environment") from _TORCH_IMPORT_ERROR

    async with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(model_uri)
        if cached is not None:
            return cached

        local_path = await _materialize_model_file(client, model_uri)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        checkpoint = torch.load(local_path, map_location=device)
        state_dict_obj = checkpoint.get("model_state_dict", checkpoint) if isinstance(checkpoint, dict) else checkpoint
        if not isinstance(state_dict_obj, dict):
            raise ValueError(f"Unsupported ResNet18 checkpoint format at {model_uri}")

        model = resnet18(weights=None)
        model.fc = nn.Linear(model.fc.in_features, 2)
        model.load_state_dict(cast(dict[str, Any], state_dict_obj))
        model.to(device)
        model.eval()

        classifier = ResNet18BubbleClassifier(
            model_uri=model_uri,
            model=model,
            device=device,
            transform=transforms.Compose(
                [
                    transforms.Resize((224, 224)),
                    transforms.Grayscale(num_output_channels=3),
                    transforms.ToTensor(),
                    transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
                ]
            ),
        )
        _MODEL_CACHE[model_uri] = classifier
        return classifier
