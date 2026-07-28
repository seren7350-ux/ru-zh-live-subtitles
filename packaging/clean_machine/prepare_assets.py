"""Prepare privacy-safe local assets for Windows Sandbox validation.

The generated staging tree is deliberately local and ignored by Git.  It is
not an application distribution mechanism and never downloads model files.
"""

from __future__ import annotations

import argparse
import fnmatch
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
    # Hugging Face tokens are standalone values.  Requiring a left boundary
    # avoids treating URL-safe wheel RECORD hashes such as ``...Hf_...`` as
    # credentials while still rejecting tokens after quotes, ``=``, or space.
    re.compile(rb"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{16,}"),
    re.compile(
        rb"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/=-]{12,}",
        re.IGNORECASE,
    ),
    re.compile(rb"Bearer\s+hf_[A-Za-z0-9]{16,}", re.IGNORECASE),
    re.compile(rb"(?:HF_TOKEN|HUGGING_FACE_HUB_TOKEN)\s*[:=]\s*[^\s\"']+", re.IGNORECASE),
)
WINDOWS_USER_PATH = re.compile(rb"[A-Za-z]:\\Users\\[^\\\x00\r\n]+", re.IGNORECASE)
EMAIL_PATTERN = re.compile(rb"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
CPU_FORBIDDEN_CUDA_DLL_PATTERNS = (
    "c10_cuda.dll",
    "torch_cuda.dll",
    "cudart*.dll",
    "cublas*.dll",
    "cudnn*.dll",
    "cufft*.dll",
    "curand*.dll",
    "cusolver*.dll",
    "cusparse*.dll",
    "nvrtc*.dll",
    "nvjitlink*.dll",
    "cupti*.dll",
    "nvperf*.dll",
)


@dataclass(frozen=True)
class ModelSpec:
    key: str
    model_id: str
    cache_name: str | None
    revision: str
    required_files: tuple[str, ...]
    license_id: str


@dataclass(frozen=True)
class SourceRevisionRef:
    """Validated source-cache ref plus non-sensitive format diagnostics."""

    revision: str
    raw_size_bytes: int
    has_utf8_bom: bool
    has_cr: bool
    has_lf: bool
    terminal_newline: str


@dataclass(frozen=True)
class ApprovedModelSource:
    """Pinned model snapshot and its validated source ref, when applicable."""

    snapshot: Path
    revision_ref: SourceRevisionRef | None


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
    runtime_family: str = "gpu",
) -> dict[str, object]:
    if runtime_family not in {"cpu", "gpu"}:
        raise AssetPreparationError(f"Unsupported package runtime family: {runtime_family}")
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
    cuda_library_files: list[str] = []
    torch_cpu_runtime_present = False
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
        if suffix == ".dll" and any(
            fnmatch.fnmatch(path.name.casefold(), pattern)
            for pattern in CPU_FORBIDDEN_CUDA_DLL_PATTERNS
        ):
            cuda_library_files.append(relative)
        if path.name.casefold() == "torch_cpu.dll":
            torch_cpu_runtime_present = True
        records.append(
            {"path": relative, "size_bytes": size, "sha256": digest}
        )
    if runtime_family == "cpu" and cuda_library_files:
        raise AssetPreparationError(
            "CPU package contains forbidden CUDA libraries: "
            + ", ".join(sorted(cuda_library_files, key=str.casefold))
        )
    if runtime_family == "cpu" and not torch_cpu_runtime_present:
        raise AssetPreparationError("CPU package has no torch_cpu.dll runtime.")
    return {
        "total_size_bytes": total_bytes,
        "file_count": len(records),
        "dll_count": dll_count,
        "third_party_build_path_marker_files": third_party_build_path_files,
        "package_runtime_family": runtime_family,
        "cuda_library_files": sorted(cuda_library_files, key=str.casefold),
        "torch_cpu_runtime_present": torch_cpu_runtime_present,
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


def verify_staged_files(
    root: Path, records: Iterable[dict[str, object]]
) -> None:
    """Verify that one staged tree exactly matches its relative SHA manifest."""

    expected = {str(record["path"]): record for record in records}
    actual = {_relative(path, root) for path in _iter_files(root)}
    if actual != set(expected):
        raise AssetPreparationError(
            "Staged file set does not match its manifest: "
            f"missing={sorted(set(expected) - actual)}, "
            f"unexpected={sorted(actual - set(expected))}"
        )
    for relative, record in expected.items():
        staged_file = root / Path(relative)
        expected_size = int(record["size_bytes"])
        expected_sha = str(record["sha256"])
        if staged_file.stat().st_size != expected_size:
            raise AssetPreparationError(
                f"Staged file size does not match its manifest: {relative}"
            )
        if sha256_file(staged_file) != expected_sha:
            raise AssetPreparationError(
                f"Staged file SHA-256 does not match its manifest: {relative}"
            )


def encode_huggingface_revision_ref(revision: str) -> bytes:
    """Encode one pinned Hugging Face revision without text-mode mutation."""

    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise AssetPreparationError(
            "Hugging Face revision must be exactly 40 lowercase hexadecimal characters."
        )
    try:
        encoded = revision.encode("ascii")
    except UnicodeEncodeError as exc:  # Defensive; the regex already rejects this.
        raise AssetPreparationError("Hugging Face revision must be ASCII.") from exc
    if len(encoded) != 40:
        raise AssetPreparationError("Encoded Hugging Face revision must be exactly 40 bytes.")
    forbidden = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff", b"\r", b"\n", b" ", b"\t", b"\x00")
    if any(marker in encoded for marker in forbidden):
        raise AssetPreparationError("Encoded Hugging Face revision contains forbidden bytes.")
    return encoded


def read_source_revision_ref(path: Path) -> SourceRevisionRef:
    """Read a source cache ref while accepting only explicit benign wrappers.

    A source ref may have a UTF-8 BOM and/or one terminal LF/CRLF because cache
    producers differ. No general whitespace stripping is performed. The staged
    ref is always regenerated by :func:`encode_huggingface_revision_ref`.
    """

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AssetPreparationError(f"Unable to read source revision ref: {path.name}") from exc

    has_utf8_bom = raw.startswith(b"\xef\xbb\xbf")
    payload = raw[3:] if has_utf8_bom else raw
    terminal_newline = "none"
    if payload.endswith(b"\r\n"):
        terminal_newline = "crlf"
        payload = payload[:-2]
    elif payload.endswith(b"\n"):
        terminal_newline = "lf"
        payload = payload[:-1]

    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise AssetPreparationError("Source revision ref must not use UTF-16 encoding.")
    if any(marker in payload for marker in (b"\r", b"\n", b" ", b"\t", b"\x00")):
        raise AssetPreparationError(
            "Source revision ref contains unsupported whitespace or NUL bytes."
        )
    try:
        revision = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise AssetPreparationError("Source revision ref must be ASCII.") from exc
    encode_huggingface_revision_ref(revision)
    return SourceRevisionRef(
        revision=revision,
        raw_size_bytes=len(raw),
        has_utf8_bom=has_utf8_bom,
        has_cr=b"\r" in raw,
        has_lf=b"\n" in raw,
        terminal_newline=terminal_newline,
    )


def stage_package(
    combined_dir: Path,
    destination: Path,
    *,
    repo_root: Path,
    expected_commit: str | None = None,
    user_home: Path | None = None,
    runtime_family: str = "gpu",
) -> dict[str, object]:
    head = validate_current_commit(repo_root, expected_commit)
    analysis = analyze_package(
        combined_dir,
        repo_root=repo_root,
        user_home=user_home or Path.home(),
        runtime_family=runtime_family,
    )
    _ensure_new_directory(destination)
    shutil.copytree(combined_dir.resolve(), destination)
    verify_staged_files(destination, analysis["files"])
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "combined-onedir",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": head,
        "application_executables": list(PACKAGE_EXES),
        "package_profile": "cpu" if runtime_family == "cpu" else "optimized",
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


def _approved_model_source(
    spec: ModelSpec, *, hf_hub: Path, silero_cache: Path
) -> ApprovedModelSource:
    if spec.cache_name is None:
        source = silero_cache.resolve()
        if not source.is_dir():
            raise AssetPreparationError(f"Silero cache does not exist: {source}")
        return ApprovedModelSource(source, None)
    cache = (hf_hub / spec.cache_name).resolve()
    ref = cache / "refs" / "main"
    if not ref.is_file():
        raise AssetPreparationError(f"Model cache has no refs/main: {spec.model_id}")
    source_ref = read_source_revision_ref(ref)
    if source_ref.revision != spec.revision:
        raise AssetPreparationError(
            f"Unexpected revision for {spec.model_id}: {source_ref.revision}"
        )
    snapshot = cache / "snapshots" / spec.revision
    if not snapshot.is_dir():
        raise AssetPreparationError(f"Pinned snapshot is missing: {spec.model_id}")
    return ApprovedModelSource(snapshot, source_ref)


def _copy_model(
    spec: ModelSpec,
    *,
    source: ApprovedModelSource,
    destination: Path,
    user_home: Path,
) -> dict[str, object]:
    snapshot = source.snapshot
    if spec.cache_name is None:
        target = destination / "silero-vad" / spec.revision
        ref_target = None
    else:
        cache_root = destination / "hf-home" / "hub" / spec.cache_name
        target = cache_root / "snapshots" / spec.revision
        (cache_root / "refs").mkdir(parents=True, exist_ok=True)
        ref_target = cache_root / "refs" / "main"
        encoded_revision = encode_huggingface_revision_ref(spec.revision)
        ref_target.write_bytes(encoded_revision)
        written = ref_target.read_bytes()
        if not (
            written == encoded_revision
            and len(written) == 40
            and written.decode("ascii") == spec.revision
        ):
            raise AssetPreparationError(
                f"Staged revision ref verification failed for {spec.model_id}."
            )
    target.mkdir(parents=True, exist_ok=True)

    expected = set(spec.required_files)
    actual = {_relative(path, snapshot) for path in _iter_files(snapshot)}
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
        source_file = snapshot / relative
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
    model_record: dict[str, object] = {
        "key": spec.key,
        "model_id": spec.model_id,
        "revision": spec.revision,
        "license": spec.license_id,
        "local_test_only": True,
        "model_weights_bundled_in_application": False,
        "total_size_bytes": sum(int(item["size_bytes"]) for item in records),
        "files": records,
    }
    if source.revision_ref is not None:
        model_record["source_revision_ref"] = {
            "raw_size_bytes": source.revision_ref.raw_size_bytes,
            "has_utf8_bom": source.revision_ref.has_utf8_bom,
            "has_cr": source.revision_ref.has_cr,
            "has_lf": source.revision_ref.has_lf,
            "terminal_newline": source.revision_ref.terminal_newline,
            "staged_size_bytes": 40,
        }
    return model_record


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
    parser.add_argument(
        "--runtime-family", choices=("cpu", "gpu"), default="gpu"
    )
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
        runtime_family=args.runtime_family,
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
