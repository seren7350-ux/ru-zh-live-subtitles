from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from live_subtitles.realtime import vad_assets


def fake_wheel(model: bytes = b"fake-model", license_text: bytes = b"MIT") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(vad_assets.MODEL_MEMBER, model)
        archive.writestr(vad_assets.LICENSE_MEMBER, license_text)
        archive.writestr("silero_vad/should_not_execute.py", "raise AssertionError('executed')")
    return buffer.getvalue()


def configure_fake_hashes(monkeypatch: pytest.MonkeyPatch, wheel: bytes, model: bytes) -> None:
    monkeypatch.setattr(vad_assets, "WHEEL_SHA256", hashlib.sha256(wheel).hexdigest())
    monkeypatch.setattr(vad_assets, "MODEL_SHA256", hashlib.sha256(model).hexdigest())
    monkeypatch.setattr(vad_assets, "MODEL_SIZE_BYTES", len(model))


def test_missing_cache_requests_vad_prepare(tmp_path: Path) -> None:
    with pytest.raises(vad_assets.VadAssetError, match="vad-prepare"):
        vad_assets.validate_vad_assets(tmp_path / "missing")


def test_prepare_verifies_wheel_without_executing_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model = b"safe-onnx-payload"
    wheel = fake_wheel(model)
    configure_fake_hashes(monkeypatch, wheel, model)
    calls: list[tuple[str, int]] = []

    def opener(url: str, *, timeout: int) -> io.BytesIO:
        calls.append((url, timeout))
        return io.BytesIO(wheel)

    info, downloaded = vad_assets.prepare_vad_assets(
        cache_dir=tmp_path / "cache",
        opener=opener,
        now=lambda: datetime(2026, 7, 27, tzinfo=timezone.utc),
    )
    assert downloaded is True
    assert len(calls) == 1
    assert info.model_path.read_bytes() == model
    assert info.license_path.read_bytes() == b"MIT"
    metadata = json.loads(info.metadata_path.read_text(encoding="utf-8"))
    assert metadata["wheel_member"] == vad_assets.MODEL_MEMBER
    assert metadata["source"] == vad_assets.SOURCE
    assert not (tmp_path / "executed").exists()


def test_verified_cache_never_accesses_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model = b"cached-model"
    wheel = fake_wheel(model)
    configure_fake_hashes(monkeypatch, wheel, model)
    cache = tmp_path / "cache"
    vad_assets.prepare_vad_assets(cache_dir=cache, opener=lambda *args, **kwargs: io.BytesIO(wheel))

    def forbidden(*args: object, **kwargs: object) -> io.BytesIO:
        raise AssertionError("network should not be used")

    info, downloaded = vad_assets.prepare_vad_assets(cache_dir=cache, opener=forbidden)
    assert downloaded is False
    assert info.model_path.read_bytes() == model


def test_corrupt_cached_model_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model = b"expected-model"
    wheel = fake_wheel(model)
    configure_fake_hashes(monkeypatch, wheel, model)
    cache = tmp_path / "cache"
    info, _ = vad_assets.prepare_vad_assets(
        cache_dir=cache, opener=lambda *args, **kwargs: io.BytesIO(wheel)
    )
    info.model_path.write_bytes(b"corrupt")
    with pytest.raises(vad_assets.VadAssetError, match="size mismatch"):
        vad_assets.validate_vad_assets(cache)


def test_bad_download_sha_leaves_no_complete_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wheel = fake_wheel()
    monkeypatch.setattr(vad_assets, "WHEEL_SHA256", "0" * 64)
    cache = tmp_path / "cache"
    with pytest.raises(vad_assets.VadAssetError, match="Wheel SHA-256 mismatch"):
        vad_assets.prepare_vad_assets(
            cache_dir=cache, opener=lambda *args, **kwargs: io.BytesIO(wheel)
        )
    assert not (cache / "silero_vad.onnx").exists()


def test_cache_path_uses_local_app_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert vad_assets.vad_cache_dir() == (
        tmp_path / "ru-zh-live-subtitles" / "models" / "silero-vad" / "6.2.1"
    )
