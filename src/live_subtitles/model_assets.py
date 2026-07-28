"""Pinned external model specifications and fast offline readiness checks."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .runtime_paths import user_data_directory

SILERO_VERSION = "6.2.1"
GIGAAM_MODEL_ID = "istupakov/gigaam-v3-onnx"
GIGAAM_REVISION = "322c3b29492673eb7d0b434bfa9dfb8653e34d02"
NLLB_MODEL_ID = "facebook/nllb-200-distilled-600M"
NLLB_REVISION = "f8d333a098d19b4fd9a8b18f94170487ad3f821d"
LOWER_HEX_REVISION = re.compile(rb"[0-9a-f]{40}")


class ModelAssetError(RuntimeError):
    """Raised when external model assets are absent or structurally invalid."""


@dataclass(frozen=True)
class ModelAssetSpec:
    key: str
    model_id: str
    cache_name: str | None
    revision: str
    required_files: tuple[str, ...]
    expected_sizes: tuple[tuple[str, int], ...]
    license_id: str


MODEL_SPECS = (
    ModelAssetSpec(
        key="silero-vad",
        model_id=f"silero-vad/{SILERO_VERSION}",
        cache_name=None,
        revision=SILERO_VERSION,
        required_files=("LICENSE", "metadata.json", "silero_vad.onnx"),
        expected_sizes=(("silero_vad.onnx", 2_327_524),),
        license_id="MIT",
    ),
    ModelAssetSpec(
        key="gigaam-v3-e2e-rnnt",
        model_id=GIGAAM_MODEL_ID,
        cache_name="models--istupakov--gigaam-v3-onnx",
        revision=GIGAAM_REVISION,
        required_files=(
            "config.json",
            "v3_e2e_rnnt_decoder.onnx",
            "v3_e2e_rnnt_encoder.onnx",
            "v3_e2e_rnnt_joint.onnx",
            "v3_e2e_rnnt_vocab.txt",
        ),
        expected_sizes=(
            ("config.json", 135),
            ("v3_e2e_rnnt_decoder.onnx", 4_599_910),
            ("v3_e2e_rnnt_encoder.onnx", 885_084_534),
            ("v3_e2e_rnnt_joint.onnx", 2_712_896),
            ("v3_e2e_rnnt_vocab.txt", 13_354),
        ),
        license_id="MIT",
    ),
    ModelAssetSpec(
        key="nllb-200-distilled-600m",
        model_id=NLLB_MODEL_ID,
        cache_name="models--facebook--nllb-200-distilled-600M",
        revision=NLLB_REVISION,
        required_files=(
            "config.json",
            "generation_config.json",
            "pytorch_model.bin",
            "sentencepiece.bpe.model",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
        ),
        expected_sizes=(
            ("config.json", 846),
            ("generation_config.json", 189),
            ("pytorch_model.bin", 2_460_457_927),
            ("sentencepiece.bpe.model", 4_852_054),
            ("special_tokens_map.json", 3_548),
            ("tokenizer.json", 17_331_176),
            ("tokenizer_config.json", 564),
        ),
        license_id="CC-BY-NC-4.0",
    ),
)


@dataclass(frozen=True)
class ModelAssetStatus:
    key: str
    model_id: str
    revision: str
    ready: bool
    location: Path
    cache_root: Path | None
    missing_files: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelAssetsReport:
    model_root: Path
    hf_cache_root: Path
    statuses: tuple[ModelAssetStatus, ...]

    @property
    def ready(self) -> bool:
        return all(status.ready for status in self.statuses)

    @property
    def missing_models(self) -> tuple[ModelAssetStatus, ...]:
        return tuple(status for status in self.statuses if not status.ready)


def user_model_root() -> Path:
    """Return the per-user model root without creating it."""

    return user_data_directory() / "models"


def managed_hf_home(model_root: Path | None = None) -> Path:
    return (model_root or user_model_root()) / "hf-home"


def default_hf_hub_cache() -> Path:
    return Path.home() / ".cache" / "huggingface" / "hub"


def hugging_face_cache_candidates(model_root: Path | None = None) -> tuple[Path, ...]:
    """Return cache candidates in the documented priority order."""

    if explicit_cache := os.environ.get("HF_HUB_CACHE"):
        return (Path(explicit_cache).expanduser(),)
    if explicit_home := os.environ.get("HF_HOME"):
        return (Path(explicit_home).expanduser() / "hub",)
    managed = managed_hf_home(model_root) / "hub"
    default = default_hf_hub_cache()
    return (managed, default) if managed != default else (managed,)


def _check_revision_ref(ref_path: Path, revision: str) -> tuple[str, ...]:
    if not ref_path.is_file():
        return ("refs/main is missing",)
    try:
        raw = ref_path.read_bytes()
    except OSError as exc:
        return (f"refs/main cannot be read ({type(exc).__name__})",)
    problems: list[str] = []
    if len(raw) != 40:
        problems.append(f"refs/main must be exactly 40 bytes (found {len(raw)})")
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append("refs/main contains a UTF-8 BOM")
    if b"\r" in raw or b"\n" in raw:
        problems.append("refs/main contains CR or LF")
    if LOWER_HEX_REVISION.fullmatch(raw) is None:
        problems.append("refs/main is not lowercase hexadecimal")
    if raw != revision.encode("ascii"):
        problems.append(f"refs/main does not match pinned revision {revision}")
    return tuple(problems)


def _check_hf_model(spec: ModelAssetSpec, cache_root: Path) -> ModelAssetStatus:
    assert spec.cache_name is not None
    repository = cache_root / spec.cache_name
    snapshot = repository / "snapshots" / spec.revision
    problems = list(_check_revision_ref(repository / "refs" / "main", spec.revision))
    if not snapshot.is_dir():
        problems.append(f"snapshot {spec.revision} is missing")
    missing: list[str] = []
    expected_sizes = dict(spec.expected_sizes)
    for relative in spec.required_files:
        path = snapshot / relative
        if not path.is_file():
            missing.append(relative)
            continue
        size = path.stat().st_size
        if size <= 0:
            problems.append(f"{relative} is empty")
        expected = expected_sizes.get(relative)
        if expected is not None and size != expected:
            problems.append(
                f"{relative} has size {size}; expected {expected} bytes"
            )
    return ModelAssetStatus(
        key=spec.key,
        model_id=spec.model_id,
        revision=spec.revision,
        ready=not missing and not problems,
        location=snapshot,
        cache_root=cache_root,
        missing_files=tuple(missing),
        problems=tuple(problems),
    )


def _check_silero(spec: ModelAssetSpec, model_root: Path) -> ModelAssetStatus:
    from .realtime.vad_assets import VadAssetError, validate_vad_assets

    location = model_root / "silero-vad" / SILERO_VERSION
    missing = tuple(name for name in spec.required_files if not (location / name).is_file())
    problems: list[str] = []
    if not missing:
        try:
            validate_vad_assets(location)
        except VadAssetError as exc:
            problems.append(str(exc))
    return ModelAssetStatus(
        key=spec.key,
        model_id=spec.model_id,
        revision=spec.revision,
        ready=not missing and not problems,
        location=location,
        cache_root=None,
        missing_files=missing,
        problems=tuple(problems),
    )


def quick_check_model_assets(
    *,
    model_root: Path | None = None,
    hf_cache_roots: Iterable[Path] | None = None,
) -> ModelAssetsReport:
    """Check paths, pinned refs, files and sizes without loading model runtimes."""

    resolved_model_root = (model_root or user_model_root()).expanduser().resolve()
    candidates = tuple(
        path.expanduser().resolve()
        for path in (hf_cache_roots or hugging_face_cache_candidates(resolved_model_root))
    )
    if not candidates:
        candidates = ((managed_hf_home(resolved_model_root) / "hub").resolve(),)

    hf_specs = tuple(spec for spec in MODEL_SPECS if spec.cache_name is not None)
    selected_root = candidates[0]
    selected_statuses = tuple(_check_hf_model(spec, selected_root) for spec in hf_specs)
    for candidate in candidates:
        candidate_statuses = tuple(_check_hf_model(spec, candidate) for spec in hf_specs)
        if all(status.ready for status in candidate_statuses):
            selected_root = candidate
            selected_statuses = candidate_statuses
            break

    silero_spec = next(spec for spec in MODEL_SPECS if spec.cache_name is None)
    return ModelAssetsReport(
        model_root=resolved_model_root,
        hf_cache_root=selected_root,
        statuses=(_check_silero(silero_spec, resolved_model_root), *selected_statuses),
    )


def require_model_assets(report: ModelAssetsReport) -> None:
    if report.ready:
        return
    missing = ", ".join(status.model_id for status in report.missing_models)
    raise ModelAssetError(f"Model setup required: {missing}.")


def configure_offline_environment(report: ModelAssetsReport | None = None) -> None:
    """Apply process-only offline policy and a non-explicit cache fallback."""

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if "HF_HUB_CACHE" not in os.environ and "HF_HOME" not in os.environ:
        selected = report.hf_cache_root if report is not None else managed_hf_home()
        os.environ["HF_HOME"] = str(selected.parent if selected.name == "hub" else selected)


def display_path(path: Path) -> str:
    """Render a path without exposing the user's home directory name."""

    resolved = path.expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        try:
            relative = resolved.relative_to(Path(local).expanduser().resolve())
            return str(Path("%LOCALAPPDATA%") / relative)
        except ValueError:
            pass
    try:
        relative = resolved.relative_to(Path.home().resolve())
        return str(Path("<home>") / relative)
    except ValueError:
        return str(resolved)


def format_model_report(report: ModelAssetsReport) -> str:
    lines = [
        f"Model root: {display_path(report.model_root)}",
        f"Hugging Face cache: {display_path(report.hf_cache_root)}",
    ]
    for status in report.statuses:
        marker = "OK" if status.ready else "FAIL"
        lines.append(
            f"[{marker}] {status.model_id}; revision={status.revision}; "
            f"path={display_path(status.location)}"
        )
        if status.missing_files:
            lines.append("  Missing: " + ", ".join(status.missing_files))
        for problem in status.problems:
            lines.append(f"  Problem: {problem}")
    lines.append(f"Offline readiness: {'READY' if report.ready else 'NOT READY'}")
    return "\n".join(lines)


class ModelAssetsModel:
    """Small stateful wrapper used by Tk callbacks without polling."""

    def __init__(self, *, model_root: Path | None = None) -> None:
        self.model_root = model_root
        self._report: ModelAssetsReport | None = None

    def refresh(self) -> ModelAssetsReport:
        self._report = quick_check_model_assets(model_root=self.model_root)
        return self._report

    def snapshot(self) -> ModelAssetsReport:
        return self._report or self.refresh()
