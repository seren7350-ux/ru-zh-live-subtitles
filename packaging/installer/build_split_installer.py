"""Build the course installer and its two offline ZIP payloads from a CPU onedir."""

from __future__ import annotations

import argparse
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

        manifest = staging / "runtime-files.txt"
        manifest.write_text(
            "".join(f"{sha256_file(source)}|{name}\n" for name, source in sorted(runtime.items())),
            encoding="utf-8-sig",
        )
        subprocess.run([
            str(iscc), "/Qp", f"/O{staging}", "/Fsetup", "/DSplitPayloads=1",
            f"/DAppVersion={version}", f"/DVersionInfoVersion={version}.0",
            f"/DRuntimeFileManifest={manifest}",
            f"/DAppZipSha256={sha256_file(app_zip)}",
            f"/DRuntimeZipSha256={sha256_file(runtime_zip)}",
            str(script),
        ], check=True)
        output.mkdir()
        for name in ("runtime.zip", "app.zip", "setup.exe"):
            (staging / name).rename(output / name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-dist", required=True, type=Path)
    parser.add_argument("--model-assets-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--iscc", required=True, type=Path)
    args = parser.parse_args()

    cpu_dist = args.cpu_dist.resolve(strict=True)
    models = args.model_assets_root.absolute()
    iscc = args.iscc.resolve(strict=True)
    head = cpu_build_provenance.git_commit(REPO)
    distribution = validate_distribution(cpu_dist, repo_root=REPO, expected_commit=head)
    validate_model_bundle(models)
    version = distribution["cpu_build_provenance"]["application_version"]
    build(
        cpu_dist, models.resolve(), args.output_dir.resolve(), iscc, version,
        Path(__file__).with_name("cpu-only.iss"),
    )


if __name__ == "__main__":
    main()
