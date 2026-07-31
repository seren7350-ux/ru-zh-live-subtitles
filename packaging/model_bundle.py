"""Validate pinned offline model assets and create distributable metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from live_subtitles.model_assets import (  # noqa: E402
    GIGAAM_MODEL_ID,
    GIGAAM_MULTILINGUAL_VARIANT,
    GIGAAM_REVISION,
    MODEL_SPECS,
    NLLB_MODEL_ID,
    NLLB_REVISION,
    SILERO_VERSION,
    ModelAssetSpec,
)

MANIFEST_NAME = "model-manifest.json"
METADATA_NAME = "MODEL_BUNDLE_METADATA.json"
SILERO_MODEL_SHA256 = (
    "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
REVISION_PATTERN = re.compile(rb"[0-9a-f]{40}")


class ModelBundleError(RuntimeError):
    """Raised when an offline model bundle is incomplete or unsafe."""


@dataclass(frozen=True)
class ValidatedModelBundle:
    """Validated, path-free facts that may be embedded in an installer."""

    metadata: dict[str, object]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ModelBundleError("Manifest file path must be a non-empty string.")
    if "\\" in value:
        raise ModelBundleError(f"Manifest path is not canonical POSIX form: {value!r}")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or re.match(r"^[A-Za-z]:/", value)
        or ".." in candidate.parts
        or "." in candidate.parts
    ):
        raise ModelBundleError(f"Manifest path is unsafe: {value!r}")
    if len(candidate.parts) < 2:
        raise ModelBundleError(f"Manifest path is outside the model layout: {value!r}")
    return candidate.as_posix()


def _expected_paths(spec: ModelAssetSpec) -> tuple[str, ...]:
    if spec.cache_name is None:
        prefix = f"silero-vad/{spec.revision}"
        return tuple(f"{prefix}/{name}" for name in spec.required_files)
    prefix = f"hf-home/hub/{spec.cache_name}"
    snapshot = f"{prefix}/snapshots/{spec.revision}"
    return (f"{prefix}/refs/main", *(f"{snapshot}/{name}" for name in spec.required_files))


def _validate_revision_ref(path: Path, revision: str) -> None:
    raw = path.read_bytes()
    if len(raw) != 40:
        raise ModelBundleError(
            f"{path.name} revision ref must be exactly 40 bytes; found {len(raw)}."
        )
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ModelBundleError(f"{path.name} revision ref contains a UTF-8 BOM.")
    if b"\r" in raw or b"\n" in raw:
        raise ModelBundleError(f"{path.name} revision ref contains CR or LF.")
    if REVISION_PATTERN.fullmatch(raw) is None:
        raise ModelBundleError(f"{path.name} revision ref is not lowercase hexadecimal.")
    if raw != revision.encode("ascii"):
        raise ModelBundleError(
            f"{path.name} revision ref does not match pinned revision {revision}."
        )


def _manifest_models(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        raise ModelBundleError("Model manifest root must be a JSON object.")
    if payload.get("schema_version") != 1:
        raise ModelBundleError("Unsupported model manifest schema_version.")
    models = payload.get("models")
    if not isinstance(models, list):
        raise ModelBundleError("Model manifest models must be a JSON array.")
    if not all(isinstance(model, dict) for model in models):
        raise ModelBundleError("Every model manifest entry must be an object.")
    return models


def validate_model_bundle(
    root: Path,
    *,
    specs: Iterable[ModelAssetSpec] = MODEL_SPECS,
    fixed_sha256: Mapping[str, str] | None = None,
) -> ValidatedModelBundle:
    """Fully validate an explicit bundle without consulting caches or the network."""

    bundle_root = root.expanduser().resolve()
    if not bundle_root.is_dir():
        raise ModelBundleError(f"Model assets root does not exist: {bundle_root}")
    manifest_path = bundle_root / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ModelBundleError(f"Required model manifest is missing: {MANIFEST_NAME}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelBundleError(f"Model manifest cannot be read: {exc}") from exc

    selected_specs = tuple(specs)
    models = _manifest_models(manifest)
    by_key: dict[str, dict[str, object]] = {}
    for model in models:
        key = model.get("key")
        if not isinstance(key, str) or key in by_key:
            raise ModelBundleError("Model manifest contains a missing or duplicate key.")
        by_key[key] = model
    expected_keys = {spec.key for spec in selected_specs}
    if set(by_key) != expected_keys:
        raise ModelBundleError(
            "Model manifest keys do not match pinned MODEL_SPECS: "
            f"expected {sorted(expected_keys)}, found {sorted(by_key)}."
        )

    manifest_records: dict[str, tuple[int, str]] = {}
    for spec in selected_specs:
        model = by_key[spec.key]
        expected_identity = {
            "model_id": spec.model_id,
            "revision": spec.revision,
            "license": spec.license_id,
        }
        for field, expected in expected_identity.items():
            if model.get(field) != expected:
                raise ModelBundleError(
                    f"{spec.key} {field} mismatch: expected {expected!r}."
                )
        files = model.get("files")
        if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
            raise ModelBundleError(f"{spec.key} files must be an array of objects.")
        expected_paths = set(_expected_paths(spec))
        observed_paths: set[str] = set()
        model_total = 0
        for record in files:
            relative = _safe_relative_path(record.get("path"))
            if relative in manifest_records:
                raise ModelBundleError(f"Duplicate manifest file path: {relative}")
            size = record.get("size_bytes")
            digest = record.get("sha256")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise ModelBundleError(f"Invalid size for {relative}.")
            if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
                raise ModelBundleError(f"Invalid SHA-256 for {relative}.")
            manifest_records[relative] = (size, digest)
            observed_paths.add(relative)
            model_total += size
        if observed_paths != expected_paths:
            missing = sorted(expected_paths - observed_paths)
            extra = sorted(observed_paths - expected_paths)
            raise ModelBundleError(
                f"{spec.key} manifest file set mismatch; missing={missing}; extra={extra}."
            )
        if model.get("total_size_bytes") != model_total:
            raise ModelBundleError(f"{spec.key} total_size_bytes is inconsistent.")

    actual_paths: set[str] = set()
    for candidate in bundle_root.rglob("*"):
        if candidate.is_symlink():
            raise ModelBundleError(
                f"Symbolic links or reparse-point files are not accepted: "
                f"{candidate.relative_to(bundle_root).as_posix()}"
            )
        if candidate.is_file():
            relative = candidate.relative_to(bundle_root).as_posix()
            if relative != MANIFEST_NAME:
                actual_paths.add(relative)
    expected_actual = set(manifest_records)
    if actual_paths != expected_actual:
        missing = sorted(expected_actual - actual_paths)
        extra = sorted(actual_paths - expected_actual)
        raise ModelBundleError(
            f"Bundle file set mismatch; missing={missing}; extra={extra}."
        )

    fixed = dict(
        {"silero-vad/6.2.1/silero_vad.onnx": SILERO_MODEL_SHA256}
        if fixed_sha256 is None
        else fixed_sha256
    )
    expected_sizes_by_path: dict[str, int] = {}
    for spec in selected_specs:
        prefix = (
            f"silero-vad/{spec.revision}"
            if spec.cache_name is None
            else f"hf-home/hub/{spec.cache_name}/snapshots/{spec.revision}"
        )
        expected_sizes_by_path.update(
            {f"{prefix}/{name}": size for name, size in spec.expected_sizes}
        )

    for relative in sorted(manifest_records, key=str.casefold):
        path = bundle_root / Path(*PurePosixPath(relative).parts)
        manifest_size, manifest_digest = manifest_records[relative]
        actual_size = path.stat().st_size
        if actual_size != manifest_size:
            raise ModelBundleError(
                f"Size mismatch for {relative}: expected {manifest_size}, found {actual_size}."
            )
        pinned_size = expected_sizes_by_path.get(relative)
        if pinned_size is not None and actual_size != pinned_size:
            raise ModelBundleError(
                f"Pinned size mismatch for {relative}: expected {pinned_size}, found {actual_size}."
            )
        actual_digest = sha256_file(path)
        if actual_digest != manifest_digest:
            raise ModelBundleError(f"SHA-256 mismatch for {relative}.")
        pinned_digest = fixed.get(relative)
        if pinned_digest is not None and actual_digest != pinned_digest:
            raise ModelBundleError(f"Pinned SHA-256 mismatch for {relative}.")

    for spec in selected_specs:
        if spec.cache_name is not None:
            ref = (
                bundle_root
                / "hf-home"
                / "hub"
                / spec.cache_name
                / "refs"
                / "main"
            )
            _validate_revision_ref(ref, spec.revision)

    total_bytes = sum(size for size, _ in manifest_records.values())
    if not isinstance(manifest, dict) or manifest.get("total_size_bytes") != total_bytes:
        raise ModelBundleError("Model manifest total_size_bytes is inconsistent.")
    metadata: dict[str, object] = {
        "schema_version": 1,
        "bundle_type": "offline-model-assets",
        "silero_version": SILERO_VERSION,
        "silero_model_sha256": SILERO_MODEL_SHA256,
        "gigaam_model_id": GIGAAM_MODEL_ID,
        "gigaam_variant": GIGAAM_MULTILINGUAL_VARIANT,
        "gigaam_revision": GIGAAM_REVISION,
        "nllb_model_id": NLLB_MODEL_ID,
        "nllb_revision": NLLB_REVISION,
        "file_count": len(manifest_records),
        "total_bytes": total_bytes,
        "manifest_sha256": sha256_file(manifest_path),
        "licenses": {
            "silero": "MIT",
            "gigaam": "MIT",
            "nllb": "CC-BY-NC-4.0",
        },
    }
    return ValidatedModelBundle(metadata=metadata)


def write_metadata(bundle: ValidatedModelBundle, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(bundle.metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_assets_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bundle = validate_model_bundle(args.model_assets_root)
        write_metadata(bundle, args.output)
    except ModelBundleError as exc:
        parser.exit(1, f"Model bundle validation failed: {exc}\n")
    print(json.dumps(bundle.metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
