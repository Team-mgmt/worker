from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import botocore.exceptions
import numpy as np
import pytest

from worker import bubble_classifier


def test_parse_s3_uri_success() -> None:
    bucket, key = bubble_classifier._parse_s3_uri("s3://test-bucket/models/best.pt")
    assert bucket == "test-bucket"
    assert key == "models/best.pt"


@pytest.mark.parametrize("uri", ["https://example.com/model.pt", "s3://bucket-only"])
def test_parse_s3_uri_rejects_invalid_values(uri: str) -> None:
    with pytest.raises(ValueError):
        bubble_classifier._parse_s3_uri(uri)


def test_model_cache_path_uses_suffix() -> None:
    path = bubble_classifier._model_cache_path("s3://bucket/path/to/best.pt")
    assert path.name.endswith(".pt")
    assert path.parent.name == "bubble_classifier"


@pytest.mark.asyncio
async def test_atomic_write_bytes(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "model.bin"
    await bubble_classifier._atomic_write_bytes(target, b"abc123")
    assert target.read_bytes() == b"abc123"


@pytest.mark.asyncio
async def test_materialize_model_file_returns_local_path(tmp_path: Path) -> None:
    local_path = tmp_path / "best.pt"
    local_path.write_bytes(b"weights")
    resolved = await bubble_classifier._materialize_model_file(AsyncMock(), str(local_path))
    assert resolved == local_path


@pytest.mark.asyncio
async def test_materialize_model_file_downloads_from_s3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bubble_classifier, "CACHE_DIR", str(tmp_path))
    response = {"Body": AsyncMock(read=AsyncMock(return_value=b"weights"))}
    client = AsyncMock()
    client.get_object.return_value = response

    resolved = await bubble_classifier._materialize_model_file(client, "s3://bucket/path/best.pt")

    assert resolved.exists()
    assert resolved.read_bytes() == b"weights"
    client.get_object.assert_awaited_once_with(Bucket="bucket", Key="path/best.pt")


@pytest.mark.asyncio
async def test_materialize_model_file_raises_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bubble_classifier, "CACHE_DIR", str(tmp_path))
    client = AsyncMock()
    client.get_object.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "NoSuchKey"}},
        "GetObject",
    )

    with pytest.raises(FileNotFoundError):
        await bubble_classifier._materialize_model_file(client, "s3://bucket/path/best.pt")


@pytest.mark.asyncio
async def test_get_or_load_classifier_raises_when_torch_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bubble_classifier, "_TORCH_IMPORT_ERROR", RuntimeError("missing torch"))
    with pytest.raises(RuntimeError, match="Torch / torchvision is unavailable"):
        await bubble_classifier.get_or_load_resnet18_bubble_classifier(AsyncMock(), "s3://bucket/model.pt")


class _FakeModel:
    def __init__(self) -> None:
        self.fc = SimpleNamespace(in_features=8)
        self.loaded_state_dict: dict[str, object] | None = None
        self.to_device: object | None = None
        self.eval_called = False

    def load_state_dict(self, state_dict: dict[str, object]) -> None:
        self.loaded_state_dict = state_dict

    def to(self, device: object) -> "_FakeModel":
        self.to_device = device
        return self

    def eval(self) -> None:
        self.eval_called = True

    def __call__(self, tensor: object) -> object:
        return tensor


class _FakeTensor:
    def __init__(self, values: list[list[float]]) -> None:
        self._values = values

    def item(self) -> float:
        first_row = self._values[0]
        if len(first_row) == 1:
            return float(first_row[0])
        return float(first_row[1])

    def __getitem__(self, index: tuple[int, int]) -> "_FakeTensor":
        row, col = index
        return _FakeTensor([[self._values[row][col]]])

    def unsqueeze(self, dim: int) -> "_FakeTensor":
        assert dim == 0
        return self

    def to(self, device: object) -> "_FakeTensor":
        return self


class _FakeTransforms:
    @staticmethod
    def Resize(size: tuple[int, int]) -> tuple[str, tuple[int, int]]:
        return ("resize", size)

    @staticmethod
    def Grayscale(num_output_channels: int) -> tuple[str, int]:
        return ("grayscale", num_output_channels)

    @staticmethod
    def ToTensor() -> str:
        return "to_tensor"

    @staticmethod
    def Normalize(mean: list[float], std: list[float]) -> tuple[str, list[float], list[float]]:
        return ("normalize", mean, std)

    @staticmethod
    def Compose(steps: list[object]):
        def _transform(image: object) -> _FakeTensor:
            assert len(steps) == 4
            return _FakeTensor([[0.1, 0.9]])

        return _transform


class _FakeTorch:
    class cuda:
        @staticmethod
        def is_available() -> bool:
            return False

    @staticmethod
    def device(name: str) -> str:
        return name

    @staticmethod
    def load(path: Path, map_location: object) -> dict[str, object]:
        assert map_location == "cpu"
        return {"model_state_dict": {"weight": 1}}

    @staticmethod
    @contextmanager
    def no_grad():
        yield

    @staticmethod
    def softmax(logits: _FakeTensor, dim: int) -> _FakeTensor:
        assert dim == 1
        return logits


@pytest.mark.asyncio
async def test_get_or_load_classifier_builds_and_caches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_model = _FakeModel()
    monkeypatch.setattr(bubble_classifier, "_TORCH_IMPORT_ERROR", None)
    monkeypatch.setattr(bubble_classifier, "_MODEL_CACHE", {})
    monkeypatch.setattr(bubble_classifier, "torch", _FakeTorch)
    monkeypatch.setattr(bubble_classifier, "nn", SimpleNamespace(Linear=lambda in_features, out_features: ("linear", in_features, out_features)))
    monkeypatch.setattr(bubble_classifier, "transforms", _FakeTransforms)
    monkeypatch.setattr(bubble_classifier, "resnet18", lambda weights=None: fake_model)
    monkeypatch.setattr(
        bubble_classifier,
        "_materialize_model_file",
        AsyncMock(return_value=tmp_path / "best.pt"),
    )

    classifier = await bubble_classifier.get_or_load_resnet18_bubble_classifier(AsyncMock(), "s3://bucket/path/best.pt")
    classifier_again = await bubble_classifier.get_or_load_resnet18_bubble_classifier(AsyncMock(), "s3://bucket/path/best.pt")

    assert classifier is classifier_again
    assert classifier.model_uri == "s3://bucket/path/best.pt"
    assert fake_model.loaded_state_dict == {"weight": 1}
    assert fake_model.to_device == "cpu"
    assert fake_model.eval_called is True


def test_predict_filled_probability_uses_transform_and_softmax(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bubble_classifier, "torch", _FakeTorch)
    classifier = bubble_classifier.ResNet18BubbleClassifier(
        model_uri="s3://bucket/path/best.pt",
        model=_FakeModel(),
        device="cpu",
        transform=lambda image: _FakeTensor([[0.25, 0.75]]),
    )

    probability = classifier.predict_filled_probability(np.zeros((10, 10), dtype=np.uint8))

    assert probability == pytest.approx(0.75)


def test_predict_filled_probability_rejects_non_grayscale() -> None:
    classifier = bubble_classifier.ResNet18BubbleClassifier(
        model_uri="s3://bucket/path/best.pt",
        model=_FakeModel(),
        device="cpu",
        transform=lambda image: _FakeTensor([[0.25, 0.75]]),
    )

    with pytest.raises(ValueError, match="Expected grayscale bubble crop"):
        classifier.predict_filled_probability(np.zeros((10, 10, 3), dtype=np.uint8))
