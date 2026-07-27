"""Prepare the official Silero VAD ONNX asset without installing its wheel."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable
from urllib.request import urlopen

PACKAGE_NAME = "silero-vad"
PACKAGE_VERSION = "6.2.1"
WHEEL_FILENAME = "silero_vad-6.2.1-py3-none-any.whl"
WHEEL_URL = (
    "https://files.pythonhosted.org/packages/0b/2b/"
    "48566f29a8b53d856ceb1994f209122749b3fda0a733a07e82047257de7a/"
    "silero_vad-6.2.1-py3-none-any.whl"
)
WHEEL_SHA256 = "09de93c4d874bb19c53e62a47dd38be5f163cedad2b5599583231f2a84ef79cb"
MODEL_MEMBER = "silero_vad/data/silero_vad.onnx"
MODEL_SHA256 = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
MODEL_SIZE_BYTES = 2_327_524
LICENSE_MEMBER = "silero_vad-6.2.1.dist-info/licenses/LICENSE"
SOURCE = "PyPI silero-vad 6.2.1 official wheel"


class VadAssetError(RuntimeError):
    """Raised when the pinned VAD asset cannot be safely prepared or verified."""


@dataclass(frozen=True)
class VadAssetInfo:
    package_name: str
    package_version: str
    wheel_filename: str
    wheel_sha256: str
    wheel_member: str
    model_sha256: str
    model_size_bytes: int
    source: str
    prepared_at: str
    cache_dir: Path
    model_path: Path
    license_path: Path
    metadata_path: Path


def vad_cache_dir() -> Path:
    """Return the per-user model cache without creating it."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".cache"
    return base / "ru-zh-live-subtitles" / "models" / "silero-vad" / PACKAGE_VERSION


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return _sha256_stream(stream)


def _metadata_payload(prepared_at: str) -> dict[str, Any]:
    return {
        "package_name": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "wheel_filename": WHEEL_FILENAME,
        "wheel_sha256": WHEEL_SHA256,
        "wheel_member": MODEL_MEMBER,
        "model_sha256": MODEL_SHA256,
        "model_size_bytes": MODEL_SIZE_BYTES,
        "source": SOURCE,
        "prepared_at": prepared_at,
    }


def _asset_info(cache_dir: Path, prepared_at: str) -> VadAssetInfo:
    return VadAssetInfo(
        **_metadata_payload(prepared_at),
        cache_dir=cache_dir,
        model_path=cache_dir / "silero_vad.onnx",
        license_path=cache_dir / "LICENSE",
        metadata_path=cache_dir / "metadata.json",
    )


def validate_vad_assets(cache_dir: Path | None = None) -> VadAssetInfo:
    """Return verified cache information or raise with a preparation hint."""

    resolved_cache = (cache_dir or vad_cache_dir()).expanduser().resolve()
    model_path = resolved_cache / "silero_vad.onnx"
    license_path = resolved_cache / "LICENSE"
    metadata_path = resolved_cache / "metadata.json"
    if not model_path.is_file() or not license_path.is_file() or not metadata_path.is_file():
        raise VadAssetError(
            f"Silero VAD cache is incomplete at {resolved_cache}. Run 'live-subtitles vad-prepare'."
        )
    if model_path.stat().st_size != MODEL_SIZE_BYTES:
        raise VadAssetError(
            f"Silero VAD model size mismatch at {model_path}; refusing to use it."
        )
    actual_sha = sha256_file(model_path)
    if actual_sha != MODEL_SHA256:
        raise VadAssetError(
            f"Silero VAD model SHA-256 mismatch at {model_path}; refusing to use it."
        )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VadAssetError(f"Unable to read VAD metadata at {metadata_path}: {exc}") from exc
    expected = _metadata_payload(str(metadata.get("prepared_at", "")))
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise VadAssetError(
                f"Silero VAD metadata field {key!r} does not match the pinned asset."
            )
    return _asset_info(resolved_cache, str(metadata["prepared_at"]))


def _download_wheel(target: Path, opener: Callable[..., Any]) -> None:
    try:
        with opener(WHEEL_URL, timeout=60) as response, target.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    except Exception as exc:
        raise VadAssetError(f"Unable to download {WHEEL_FILENAME} from official PyPI: {exc}") from exc


def _safe_member(archive: zipfile.ZipFile, member: str) -> bytes:
    try:
        info = archive.getinfo(member)
    except KeyError as exc:
        raise VadAssetError(f"Pinned wheel member is missing: {member}") from exc
    if info.is_dir():
        raise VadAssetError(f"Pinned wheel member is not a file: {member}")
    return archive.read(info)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_vad_assets(
    *,
    cache_dir: Path | None = None,
    opener: Callable[..., Any] = urlopen,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[VadAssetInfo, bool]:
    """Prepare pinned files atomically; return information and whether download occurred."""

    resolved_cache = (cache_dir or vad_cache_dir()).expanduser().resolve()
    if resolved_cache.exists():
        try:
            return validate_vad_assets(resolved_cache), False
        except VadAssetError:
            if (resolved_cache / "silero_vad.onnx").exists():
                raise

    resolved_cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="ru-zh-silero-vad-", dir=resolved_cache.parent
    ) as temporary_dir:
        wheel_path = Path(temporary_dir) / WHEEL_FILENAME
        _download_wheel(wheel_path, opener)
        actual_wheel_sha = sha256_file(wheel_path)
        if actual_wheel_sha != WHEEL_SHA256:
            raise VadAssetError(
                f"Wheel SHA-256 mismatch: expected {WHEEL_SHA256}, got {actual_wheel_sha}."
            )
        try:
            with zipfile.ZipFile(wheel_path) as archive:
                model_bytes = _safe_member(archive, MODEL_MEMBER)
                license_bytes = _safe_member(archive, LICENSE_MEMBER)
        except zipfile.BadZipFile as exc:
            raise VadAssetError(f"Downloaded wheel is not a valid ZIP archive: {exc}") from exc
        actual_model_sha = hashlib.sha256(model_bytes).hexdigest()
        if len(model_bytes) != MODEL_SIZE_BYTES or actual_model_sha != MODEL_SHA256:
            raise VadAssetError("The ONNX model in the official wheel failed pinned size/SHA checks.")

        prepared_at = now().astimezone(timezone.utc).isoformat()
        metadata_bytes = json.dumps(
            _metadata_payload(prepared_at), ensure_ascii=False, indent=2
        ).encode("utf-8")
        _atomic_write(resolved_cache / "silero_vad.onnx", model_bytes)
        _atomic_write(resolved_cache / "LICENSE", license_bytes)
        _atomic_write(resolved_cache / "metadata.json", metadata_bytes)

    return validate_vad_assets(resolved_cache), True
