"""Build the offline Release attachments from a CPU onedir or existing ZIPs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packaging"))

import cpu_build_provenance
from model_bundle import sha256_file, validate_model_bundle
from validate_cpu_distribution import validate_distribution

RELEASE_ASSET_LIMIT = 2_000_000_000
COPY_BUFFER_BYTES = 4 * 1024 * 1024
INSTALLER_SCRIPT = Path(__file__).with_name("cpu-only.iss")


def write_zip(path: Path, files: dict[str, Path]) -> None:
    with ZipFile(path, mode="x", compression=ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        for relative, source in sorted(files.items()):
            archive.write(source, relative)


def split_onedir(cpu_dist: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    app, runtime = {}, {}
    for source in sorted(cpu_dist.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(cpu_dist)
        # Both EXEs contain the PyInstaller PYZ, including bundled Python dependencies.
        # _internal contains the reusable native libraries and external support files.
        app_metadata = len(relative.parts) > 1 and (
            relative.parts[1].lower().startswith("ru_zh_live_subtitles-")
            and relative.parts[1].lower().endswith(".dist-info")
        )
        # Analysis regenerates this stdlib ZIP with an order that can vary per build.
        build_archive = relative.as_posix() == "_internal/base_library.zip"
        files = runtime if relative.parts[0] == "_internal" and not (app_metadata or build_archive) else app
        files[relative.as_posix()] = source
    return app, runtime


def write_runtime_manifest(
    runtime_zip: Path, manifest: Path, reusable_files: dict[str, Path] | None = None,
) -> None:
    if reusable_files is not None:
        reusable_files = reusable_files.copy()
    with ZipFile(runtime_zip) as archive, manifest.open("w", encoding="utf-8-sig") as output:
        for entry in sorted(archive.infolist(), key=lambda entry: entry.filename):
            if entry.is_dir():
                continue
            digest = hashlib.sha256()
            with archive.open(entry) as source:
                for block in iter(lambda: source.read(COPY_BUFFER_BYTES), b""):
                    digest.update(block)
            checksum = digest.hexdigest()
            if reusable_files is not None and not entry.filename.startswith("models/"):
                source_file = reusable_files.pop(entry.filename, None)
                if source_file is None or sha256_file(source_file) != checksum:
                    raise ValueError(f"Reusable runtime does not match the CPU build: {entry.filename}")
            output.write(f"{checksum}|{entry.filename}\n")
    if reusable_files:
        raise ValueError(f"Reusable runtime is missing CPU build files: {', '.join(sorted(reusable_files))}")


def runtime_part_count(runtime_zip: Path) -> int:
    size = runtime_zip.stat().st_size
    if size < RELEASE_ASSET_LIMIT:
        return 0
    part_size = RELEASE_ASSET_LIMIT - 1
    return (size + part_size - 1) // part_size


def split_runtime_zip(runtime_zip: Path, staging: Path) -> list[Path]:
    remaining = runtime_zip.stat().st_size
    if remaining < RELEASE_ASSET_LIMIT:
        return [runtime_zip]

    parts = []
    with runtime_zip.open("rb") as source:
        while remaining:
            part = staging / f"runtime.zip.{len(parts) + 1:03d}"
            remaining_in_part = min(remaining, RELEASE_ASSET_LIMIT - 1)
            remaining -= remaining_in_part
            with part.open("xb") as output:
                while remaining_in_part:
                    block = source.read(min(remaining_in_part, COPY_BUFFER_BYTES))
                    if not block:
                        raise ValueError("runtime.zip ended while writing its Release parts.")
                    output.write(block)
                    remaining_in_part -= len(block)
            parts.append(part)
    return parts


def build_attachments(
    app_zip: Path, runtime_zip: Path, staging: Path, output: Path, iscc: Path, version: str,
    script: Path = INSTALLER_SCRIPT,
    *, reusable_files: dict[str, Path] | None = None,
) -> None:
    if app_zip.stat().st_size >= RELEASE_ASSET_LIMIT:
        raise ValueError("app.zip exceeds the Release attachment size limit.")

    print("Reading the runtime ZIP manifest", flush=True)
    manifest = staging / "runtime-files.txt"
    write_runtime_manifest(runtime_zip, manifest, reusable_files)
    if reusable_files is None:
        print("Preparing Release runtime attachments", flush=True)
        parts = split_runtime_zip(runtime_zip, staging)
    else:
        print("Runtime matches the CPU build. Publishing app and setup only.", flush=True)
        parts = []
    part_count = runtime_part_count(runtime_zip)
    subprocess.run([
        str(iscc), "/Qp", f"/O{staging}", "/Fsetup", "/DSplitPayloads=1",
        f"/DAppVersion={version}", f"/DVersionInfoVersion={version}.0",
        f"/DRuntimeFileManifest={manifest}", f"/DRuntimePartCount={part_count}",
        f"/DAppZipSha256={sha256_file(app_zip)}",
        f"/DRuntimeZipSha256={sha256_file(runtime_zip)}",
        str(script),
    ], check=True)
    attachments = [*parts, app_zip, staging / "setup.exe"]
    for path in attachments:
        if path.stat().st_size >= RELEASE_ASSET_LIMIT:
            raise ValueError(f"{path.name} exceeds the Release attachment size limit.")
    output.mkdir()
    for path in attachments:
        destination = output / path.name
        if path.parent == staging:
            path.rename(destination)
        else:
            shutil.copyfile(path, destination)


def build(
    cpu_dist: Path, models: Path, output: Path, iscc: Path, version: str, script: Path,
) -> None:
    app, runtime = split_onedir(cpu_dist)
    runtime.update({
        f"models/{path.relative_to(models).as_posix()}": path
        for path in models.rglob("*") if path.is_file()
    })
    if output.exists():
        raise FileExistsError(f"Output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="split-setup-", dir=output.parent) as scratch:
        staging = Path(scratch)
        app_zip = staging / "app.zip"
        runtime_zip = staging / "runtime.zip"
        print("Writing app.zip", flush=True)
        write_zip(app_zip, app)
        print("Writing runtime.zip", flush=True)
        write_zip(runtime_zip, runtime)

        build_attachments(app_zip, runtime_zip, staging, output, iscc, version, script)


def build_update(cpu_dist: Path, runtime_zip: Path, output: Path, iscc: Path, version: str) -> None:
    app, runtime = split_onedir(cpu_dist)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="split-update-", dir=output.parent) as scratch:
        staging = Path(scratch)
        app_zip = staging / "app.zip"
        print("Writing app.zip", flush=True)
        write_zip(app_zip, app)
        build_attachments(app_zip, runtime_zip, staging, output, iscc, version, reusable_files=runtime)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cpu-dist", type=Path)
    source.add_argument("--existing-payloads", type=Path, help="directory containing app.zip and runtime.zip")
    runtime = parser.add_mutually_exclusive_group()
    runtime.add_argument("--model-assets-root", type=Path, help="model bundle for a full CPU build")
    runtime.add_argument("--reuse-runtime", type=Path, help="publish only app.zip and setup.exe using this verified runtime.zip")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--iscc", required=True, type=Path)
    args = parser.parse_args()

    output = args.output_dir.resolve()
    iscc = args.iscc.resolve(strict=True)
    if output.exists():
        raise FileExistsError(f"Output directory already exists: {output}")
    if args.existing_payloads:
        if args.model_assets_root or args.reuse_runtime:
            parser.error("--model-assets-root and --reuse-runtime require --cpu-dist")
        existing = args.existing_payloads.resolve(strict=True)
        app_zip, runtime_zip = existing / "app.zip", existing / "runtime.zip"
        with ZipFile(app_zip) as archive:
            provenance = cpu_build_provenance.validate_metadata(
                json.loads(archive.read(cpu_build_provenance.METADATA_NAME))
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="split-setup-", dir=output.parent) as scratch:
            build_attachments(
                app_zip, runtime_zip, Path(scratch), output, iscc, provenance["application_version"],
            )
        return

    if not args.model_assets_root and not args.reuse_runtime:
        parser.error("provide --model-assets-root or --reuse-runtime with --cpu-dist")
    cpu_dist = args.cpu_dist.resolve(strict=True)
    head = cpu_build_provenance.git_commit(REPO)
    distribution = validate_distribution(cpu_dist, repo_root=REPO, expected_commit=head)
    version = distribution["cpu_build_provenance"]["application_version"]
    if args.reuse_runtime:
        build_update(cpu_dist, args.reuse_runtime.resolve(strict=True), output, iscc, version)
        return
    models = args.model_assets_root.absolute()
    validate_model_bundle(models)
    build(
        cpu_dist, models.resolve(), output, iscc, version, INSTALLER_SCRIPT,
    )


if __name__ == "__main__":
    main()
