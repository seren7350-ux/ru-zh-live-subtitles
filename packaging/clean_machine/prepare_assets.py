"""Prepare privacy-safe local assets for Windows Sandbox validation.

The generated staging tree is deliberately local and ignored by Git.  It is
not an application distribution mechanism and never downloads model files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator


class AssetPreparationError(RuntimeError):
    """Raised when a candidate asset violates the clean-machine boundary."""


CHUNK_SIZE = 4 * 1024 * 1024
PACKAGE_EXES = ("ru-zh-subtitles-console.exe", "ru-zh-subtitles.exe")
FORBIDDEN_PACKAGE_SUFFIXES = {
    ".bin",
    ".pt",
    ".pth",
    ".safetensors",
    ".wav",
    ".mp3",
    ".flac",
}
APPROVED_PACKAGE_ONNX_PREFIX = "_internal/onnx_asr/preprocessors/data/"
SENSITIVE_PATH_PARTS = {
    ".git",
    ".ssh",
    ".venv",
    ".venv-packaging",
    ".locks",
    "cookies",
    "credentials",
    "stored_tokens",
}
TOKEN_PATTERNS = (
    re.compile(rb"hf_[A-Za-z0-9]{16,}"),
    re.compile(
        rb"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/=-]{12,}",
        re.IGNORECASE,
    ),
    re.compile(rb"Bearer\s+hf_[A-Za-z0-9]{16,}", re.IGNORECASE),
    re.compile(rb"(?:HF_TOKEN|HUGGING_FACE_HUB_TOKEN)\s*[:=]\s*[^\s\"']+", re.IGNORECASE),
)
WINDOWS_USER_PATH = re.compile(rb"[A-Za-z]:\\Users\\[^\\\x00\r\n]+", re.IGNORECASE)
EMAIL_PATTERN = re.compile(rb"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


@dataclass(frozen=True)
class ModelSpec:
    key: str
    model_id: str
    cache_name: str | None
    revision: str
    required_files: tuple[str, ...]
    license_id: str


MODEL_SPECS = (
    ModelSpec(
        key="silero-vad",
        model_id="silero-vad/6.2.1",
        cache_name=None,
        revision="6.2.1",
        required_files=("LICENSE", "metadata.json", "silero_vad.onnx"),
        license_id="MIT",
    ),
    ModelSpec(
        key="gigaam-v3-e2e-rnnt",
        model_id="istupakov/gigaam-v3-onnx",
        cache_name="models--istupakov--gigaam-v3-onnx",
        revision="322c3b29492673eb7d0b434bfa9dfb8653e34d02",
        required_files=(
            "config.json",
            "v3_e2e_rnnt_decoder.onnx",
            "v3_e2e_rnnt_encoder.onnx",
            "v3_e2e_rnnt_joint.onnx",
            "v3_e2e_rnnt_vocab.txt",
        ),
        license_id="MIT",
    ),
    ModelSpec(
        key="nllb-200-distilled-600m",
        model_id="facebook/nllb-200-distilled-600M",
        cache_name="models--facebook--nllb-200-distilled-600M",
        revision="f8d333a098d19b4fd9a8b18f94170487ad3f821d",
        required_files=(
            "config.json",
            "generation_config.json",
            "pytorch_model.bin",
            "sentencepiece.bpe.model",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
        ),
        license_id="CC-BY-NC-4.0",
    ),
)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _iter_files(root: Path) -> Iterator[Path]:
    yield from sorted((path for path in root.rglob("*") if path.is_file()), key=lambda p: p.as_posix().casefold())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_content(
    path: Path,
    *,
    reject_email: bool,
    reject_generic_user_path: bool,
    forbidden_literals: Iterable[bytes],
) -> tuple[list[str], bool, str]:
    findings: set[str] = set()
    generic_user_path_found = False
    overlap = b""
    literals = tuple(item.lower() for item in forbidden_literals if item)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
            sample = overlap + chunk
            lowered = sample.lower()
            if any(literal in lowered for literal in literals):
                findings.add("host absolute path")
            if WINDOWS_USER_PATH.search(sample):
                generic_user_path_found = True
            if reject_generic_user_path and generic_user_path_found:
                findings.add("Windows user path")
            if reject_email and EMAIL_PATTERN.search(sample):
                findings.add("email address")
            if any(pattern.search(sample) for pattern in TOKEN_PATTERNS):
                findings.add("authentication token")
            overlap = sample[-512:]
    return sorted(findings), generic_user_path_found, digest.hexdigest()


def _validate_relative_path(relative: str) -> None:
    path = Path(relative)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", relative):
        raise AssetPreparationError(f"Manifest path must be relative: {relative}")
    lowered = {part.casefold() for part in path.parts}
    rejected = lowered & SENSITIVE_PATH_PARTS
    if rejected:
        raise AssetPreparationError(
            f"Sensitive path component in asset {relative}: {sorted(rejected)}"
        )


def _git_head(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def validate_current_commit(repo_root: Path, expected_commit: str | None) -> str:
    head = _git_head(repo_root.resolve())
    if expected_commit and head != expected_commit:
        raise AssetPreparationError(
            f"Git commit mismatch: expected {expected_commit}, found {head}."
        )
    return head


def analyze_package(
    combined_dir: Path,
    *,
    repo_root: Path,
    user_home: Path,
) -> dict[str, object]:
    root = combined_dir.resolve()
    if not root.is_dir():
        raise AssetPreparationError(f"Combined onedir does not exist: {root}")
    missing = [name for name in PACKAGE_EXES if not (root / name).is_file()]
    if missing:
        raise AssetPreparationError(f"Combined onedir is missing: {', '.join(missing)}")

    forbidden_literals = {
        str(repo_root.resolve()).encode("utf-8", errors="ignore"),
        str(user_home.resolve()).encode("utf-8", errors="ignore"),
        str(repo_root.resolve()).encode("utf-16le", errors="ignore"),
        str(user_home.resolve()).encode("utf-16le", errors="ignore"),
    }
    records: list[dict[str, object]] = []
    third_party_build_path_files: list[str] = []
    total_bytes = 0
    dll_count = 0
    for path in _iter_files(root):
        relative = _relative(path, root)
        _validate_relative_path(relative)
        suffix = path.suffix.casefold()
        if suffix in FORBIDDEN_PACKAGE_SUFFIXES:
            raise AssetPreparationError(f"Forbidden model/audio asset in package: {relative}")
        if suffix == ".onnx" and not relative.casefold().startswith(
            APPROVED_PACKAGE_ONNX_PREFIX.casefold()
        ):
            raise AssetPreparationError(f"Unapproved ONNX model in package: {relative}")
        findings, generic_user_path_found, digest = _scan_content(
            path,
            reject_email=False,
            reject_generic_user_path=False,
            forbidden_literals=forbidden_literals,
        )
        if findings:
            raise AssetPreparationError(
                f"Sensitive content in package file {relative}: {', '.join(findings)}"
            )
        if generic_user_path_found:
            third_party_build_path_files.append(relative)
        size = path.stat().st_size
        total_bytes += size
        dll_count += suffix == ".dll"
        records.append(
            {"path": relative, "size_bytes": size, "sha256": digest}
        )
    return {
        "total_size_bytes": total_bytes,
        "file_count": len(records),
        "dll_count": dll_count,
        "third_party_build_path_marker_files": third_party_build_path_files,
        "files": records,
    }


def _ensure_new_directory(path: Path) -> None:
    if path.exists():
        raise AssetPreparationError(
            f"Refusing to replace existing staging directory: {path.resolve()}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def stage_package(
    combined_dir: Path,
    destination: Path,
    *,
    repo_root: Path,
    expected_commit: str | None = None,
    user_home: Path | None = None,
) -> dict[str, object]:
    head = validate_current_commit(repo_root, expected_commit)
    analysis = analyze_package(
        combined_dir,
        repo_root=repo_root,
        user_home=user_home or Path.home(),
    )
    _ensure_new_directory(destination)
    shutil.copytree(combined_dir.resolve(), destination)
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "combined-onedir",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": head,
        "application_executables": list(PACKAGE_EXES),
        "package_profile": "optimized",
        "model_weights_bundled_in_application": False,
        "machine_paths_included": False,
        **analysis,
    }
    _write_json(destination / "asset-manifest.json", payload)
    return payload


def stage_scripts(
    toolkit_dir: Path,
    destination: Path,
    *,
    test_wav: Path | None = None,
) -> None:
    source = toolkit_dir.resolve()
    if not source.is_dir():
        raise AssetPreparationError(f"Toolkit directory does not exist: {source}")
    source_wav: Path | None = None
    if test_wav is not None:
        source_wav = test_wav.expanduser().resolve()
        if not source_wav.is_file() or source_wav.suffix.casefold() != ".wav":
            raise AssetPreparationError(
                f"The optional test audio must be an existing WAV: {source_wav}"
            )
        try:
            with wave.open(str(source_wav), "rb") as wav_file:
                params = (
                    wav_file.getnchannels(),
                    wav_file.getsampwidth(),
                    wav_file.getframerate(),
                    wav_file.getnframes(),
                )
        except (EOFError, OSError, wave.Error) as exc:
            raise AssetPreparationError(f"Unable to read optional test WAV: {exc}") from exc
        if params[0:3] != (1, 2, 16_000) or params[3] <= 0:
            raise AssetPreparationError(
                "Optional test WAV must be non-empty mono PCM16 at 16000 Hz."
            )
    _ensure_new_directory(destination)
    destination.mkdir(parents=True)
    for name in (
        "package_only_startup.ps1",
        "offline_cache_startup.ps1",
        "collect_results.ps1",
        "result-schema.json",
    ):
        path = source / name
        if not path.is_file():
            raise AssetPreparationError(f"Toolkit file does not exist: {path}")
        shutil.copy2(path, destination / name)
    if source_wav is not None:
        audio_dir = destination / "test-audio"
        audio_dir.mkdir()
        staged_wav = audio_dir / "sample.wav"
        shutil.copy2(source_wav, staged_wav)
        _write_json(
            destination / "test-audio-manifest.json",
            {
                "schema_version": 1,
                "kind": "local-non-sensitive-test-audio",
                "local_test_only": True,
                "must_not_commit": True,
                "must_not_upload": True,
                "files": [
                    {
                        "path": "test-audio/sample.wav",
                        "size_bytes": staged_wav.stat().st_size,
                        "sha256": sha256_file(staged_wav),
                    }
                ],
            },
        )


def _approved_model_source(spec: ModelSpec, *, hf_hub: Path, silero_cache: Path) -> Path:
    if spec.cache_name is None:
        source = silero_cache.resolve()
        if not source.is_dir():
            raise AssetPreparationError(f"Silero cache does not exist: {source}")
        return source
    cache = (hf_hub / spec.cache_name).resolve()
    ref = cache / "refs" / "main"
    if not ref.is_file():
        raise AssetPreparationError(f"Model cache has no refs/main: {spec.model_id}")
    actual_revision = ref.read_text(encoding="utf-8").strip()
    if actual_revision != spec.revision:
        raise AssetPreparationError(
            f"Unexpected revision for {spec.model_id}: {actual_revision}"
        )
    snapshot = cache / "snapshots" / spec.revision
    if not snapshot.is_dir():
        raise AssetPreparationError(f"Pinned snapshot is missing: {spec.model_id}")
    return snapshot


def _copy_model(
    spec: ModelSpec,
    *,
    source: Path,
    destination: Path,
    user_home: Path,
) -> dict[str, object]:
    if spec.cache_name is None:
        target = destination / "silero-vad" / spec.revision
        ref_target = None
    else:
        cache_root = destination / "hf-home" / "hub" / spec.cache_name
        target = cache_root / "snapshots" / spec.revision
        (cache_root / "refs").mkdir(parents=True, exist_ok=True)
        ref_target = cache_root / "refs" / "main"
        ref_target.write_text(spec.revision + "\n", encoding="utf-8")
    target.mkdir(parents=True, exist_ok=True)

    expected = set(spec.required_files)
    actual = {_relative(path, source) for path in _iter_files(source)}
    missing = expected - actual
    if missing:
        raise AssetPreparationError(
            f"Pinned files missing for {spec.model_id}: {sorted(missing)}"
        )
    unexpected = actual - expected
    if unexpected:
        raise AssetPreparationError(
            f"Unapproved files present for {spec.model_id}: {sorted(unexpected)}"
        )
    records: list[dict[str, object]] = []
    if ref_target is not None:
        records.append(
            {
                "path": _relative(ref_target, destination),
                "size_bytes": ref_target.stat().st_size,
                "sha256": sha256_file(ref_target),
            }
        )
    for relative in spec.required_files:
        _validate_relative_path(relative)
        source_file = source / relative
        target_file = target / relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        findings, _, _ = _scan_content(
            source_file,
            reject_email=True,
            reject_generic_user_path=True,
            forbidden_literals=(
                str(user_home.resolve()).encode("utf-8", errors="ignore"),
                str(user_home.resolve()).encode("utf-16le", errors="ignore"),
            ),
        )
        if findings:
            raise AssetPreparationError(
                f"Sensitive content in {spec.model_id}/{relative}: {', '.join(findings)}"
            )
        shutil.copy2(source_file, target_file)
        staged_relative = _relative(target_file, destination)
        records.append(
            {
                "path": staged_relative,
                "size_bytes": target_file.stat().st_size,
                "sha256": sha256_file(target_file),
            }
        )
    return {
        "key": spec.key,
        "model_id": spec.model_id,
        "revision": spec.revision,
        "license": spec.license_id,
        "local_test_only": True,
        "model_weights_bundled_in_application": False,
        "total_size_bytes": sum(int(item["size_bytes"]) for item in records),
        "files": records,
    }


def stage_models(
    *,
    hf_hub: Path,
    silero_cache: Path,
    destination: Path,
    user_home: Path | None = None,
) -> dict[str, object]:
    _ensure_new_directory(destination)
    destination.mkdir(parents=True)
    home = user_home or Path.home()
    models = [
        _copy_model(
            spec,
            source=_approved_model_source(
                spec, hf_hub=hf_hub.resolve(), silero_cache=silero_cache.resolve()
            ),
            destination=destination,
            user_home=home,
        )
        for spec in MODEL_SPECS
    ]
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "local-sandbox-model-staging",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "local_test_only": True,
        "models_bundled_in_application": False,
        "must_not_commit": True,
        "must_not_upload": True,
        "models": models,
        "total_size_bytes": sum(int(item["total_size_bytes"]) for item in models),
    }
    _write_json(destination / "model-manifest.json", payload)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--combined-dir", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--toolkit-dir", type=Path, required=True)
    parser.add_argument("--expected-commit")
    parser.add_argument("--stage-models", action="store_true")
    parser.add_argument("--hf-hub", type=Path)
    parser.add_argument("--silero-cache", type=Path)
    parser.add_argument("--test-wav", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    staging_root = args.staging_root.resolve()
    if staging_root.exists() and any(staging_root.iterdir()):
        raise AssetPreparationError(
            f"Staging root must be new or empty: {staging_root}"
        )
    staging_root.mkdir(parents=True, exist_ok=True)
    package = stage_package(
        args.combined_dir,
        staging_root / "package",
        repo_root=args.repo_root,
        expected_commit=args.expected_commit,
    )
    stage_scripts(
        args.toolkit_dir,
        staging_root / "scripts",
        test_wav=args.test_wav,
    )
    summary: dict[str, object] = {"package": package}
    if args.stage_models:
        if args.hf_hub is None or args.silero_cache is None:
            raise AssetPreparationError(
                "--hf-hub and --silero-cache are required with --stage-models."
            )
        summary["models"] = stage_models(
            hf_hub=args.hf_hub,
            silero_cache=args.silero_cache,
            destination=staging_root / "model-assets",
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
