"""Generate machine-specific Windows Sandbox configurations safely."""

from __future__ import annotations

import argparse
import ctypes
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class SandboxConfigError(RuntimeError):
    """Raised when a host mapping would weaken the clean-machine boundary."""


TOKEN_PATTERN = re.compile(
    r"hf_[A-Za-z0-9]{16,}|Bearer\s+\S+|(?:HF_TOKEN|HUGGING_FACE_HUB_TOKEN)\s*[:=]",
    re.IGNORECASE,
)
FORBIDDEN_PARTS = {".git", ".venv", ".venv-packaging"}


@dataclass(frozen=True)
class SandboxMapping:
    host: Path
    sandbox: str
    read_only: bool


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def host_total_memory_bytes() -> int:
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    try:
        success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError) as exc:
        raise SandboxConfigError("Unable to query Windows physical memory.") from exc
    if not success:
        raise SandboxConfigError("GlobalMemoryStatusEx failed.")
    return int(status.ullTotalPhys)


def sandbox_memory_mb(total_host_bytes: int) -> int:
    """Apply the documented conservative host-memory allocation table."""

    if total_host_bytes >= 32_000_000_000:
        return 16_384
    if total_host_bytes >= 24_000_000_000:
        return 12_288
    if total_host_bytes >= 16_000_000_000:
        return 8_192
    return 4_096


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_host_folder(
    path: Path,
    *,
    role: str,
    repo_root: Path,
    user_home: Path,
) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise SandboxConfigError(f"{role} HostFolder does not exist: {resolved}")
    repo = repo_root.resolve()
    home = user_home.resolve()
    if resolved in {repo, home}:
        raise SandboxConfigError(f"Refusing broad {role} mapping: {resolved}")
    lowered_parts = {part.casefold() for part in resolved.parts}
    rejected = lowered_parts & FORBIDDEN_PARTS
    if rejected:
        raise SandboxConfigError(
            f"Refusing {role} mapping containing {sorted(rejected)}: {resolved}"
        )
    full_hf_cache = home / ".cache" / "huggingface"
    if resolved in {full_hf_cache, full_hf_cache / "hub"}:
        raise SandboxConfigError("Refusing to map the complete user Hugging Face cache.")
    if role == "results" and any(resolved.iterdir()):
        raise SandboxConfigError("The dedicated results HostFolder must be empty.")
    if role != "results" and not _is_relative_to(resolved, repo) and resolved == home:
        raise SandboxConfigError(f"Refusing user-root mapping: {resolved}")
    return resolved


def create_unique_results_directory(results_root: Path, label: str) -> Path:
    root = results_root.resolve()
    if not root.is_dir():
        raise SandboxConfigError(f"Results root does not exist: {root}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = root / f"{label}-{stamp}-{uuid.uuid4().hex[:8]}"
    destination.mkdir()
    return destination


def _mapped_folder(parent: ET.Element, mapping: SandboxMapping) -> None:
    element = ET.SubElement(parent, "MappedFolder")
    ET.SubElement(element, "HostFolder").text = str(mapping.host)
    ET.SubElement(element, "SandboxFolder").text = mapping.sandbox
    ET.SubElement(element, "ReadOnly").text = str(mapping.read_only).lower()


def build_sandbox_xml(
    *,
    package: Path,
    scripts: Path,
    results: Path,
    memory_mb: int,
    model_assets: Path | None = None,
) -> str:
    configuration = ET.Element("Configuration")
    ET.SubElement(configuration, "VGpu").text = "Enable"
    ET.SubElement(configuration, "Networking").text = "Disable"
    ET.SubElement(configuration, "AudioInput").text = "Enable"
    ET.SubElement(configuration, "VideoInput").text = "Disable"
    ET.SubElement(configuration, "PrinterRedirection").text = "Disable"
    ET.SubElement(configuration, "ProtectedClient").text = "Enable"
    ET.SubElement(configuration, "MemoryInMB").text = str(memory_mb)
    mapped = ET.SubElement(configuration, "MappedFolders")
    mappings = [
        SandboxMapping(package, r"C:\Validation\Package", True),
        SandboxMapping(scripts, r"C:\Validation\Scripts", True),
    ]
    if model_assets is not None:
        mappings.append(
            SandboxMapping(model_assets, r"C:\Validation\ModelAssets", True)
        )
    mappings.append(SandboxMapping(results, r"C:\Validation\Results", False))
    for mapping in mappings:
        _mapped_folder(mapped, mapping)

    startup = (
        "offline_cache_startup.ps1" if model_assets is not None else "package_only_startup.ps1"
    )
    command = (
        "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass "
        f'-File "C:\\Validation\\Scripts\\{startup}" '
        '-PackageRoot "C:\\Validation\\Package" '
        '-ResultsRoot "C:\\Validation\\Results"'
    )
    if model_assets is not None:
        command += ' -ModelRoot "C:\\Validation\\ModelAssets"'
    logon = ET.SubElement(configuration, "LogonCommand")
    ET.SubElement(logon, "Command").text = command
    ET.indent(configuration, space="  ")
    serialized = ET.tostring(configuration, encoding="unicode") + "\n"
    ET.fromstring(serialized)
    if TOKEN_PATTERN.search(serialized):
        raise SandboxConfigError("Generated Sandbox XML contains a token marker.")
    return serialized


def generate_config(
    *,
    package: Path,
    scripts: Path,
    results: Path,
    output: Path,
    repo_root: Path,
    user_home: Path,
    memory_mb: int,
    model_assets: Path | None = None,
) -> Path:
    package_path = validate_host_folder(
        package, role="package", repo_root=repo_root, user_home=user_home
    )
    scripts_path = validate_host_folder(
        scripts, role="scripts", repo_root=repo_root, user_home=user_home
    )
    results_path = validate_host_folder(
        results, role="results", repo_root=repo_root, user_home=user_home
    )
    model_path = None
    if model_assets is not None:
        model_path = validate_host_folder(
            model_assets, role="model", repo_root=repo_root, user_home=user_home
        )
    if memory_mb <= 0:
        raise SandboxConfigError("Sandbox memory must be positive.")
    xml = build_sandbox_xml(
        package=package_path,
        scripts=scripts_path,
        results=results_path,
        memory_mb=memory_mb,
        model_assets=model_path,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(xml, encoding="utf-8")
    return output.resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--memory-mb", type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    staging = args.staging_root.resolve()
    results_root = staging / "results"
    results_root.mkdir(parents=True, exist_ok=True)
    memory_mb = args.memory_mb or sandbox_memory_mb(host_total_memory_bytes())
    common = {
        "package": staging / "package",
        "scripts": staging / "scripts",
        "repo_root": args.repo_root,
        "user_home": Path.home(),
        "memory_mb": memory_mb,
    }
    package_results = create_unique_results_directory(results_root, "package-only")
    package_config = generate_config(
        **common,
        results=package_results,
        output=staging / "generated-package-only.wsb",
    )
    model_assets = staging / "model-assets"
    if not model_assets.is_dir():
        raise SandboxConfigError(
            "Model staging is required before generating the offline-cache config."
        )
    offline_results = create_unique_results_directory(results_root, "offline-cache")
    offline_config = generate_config(
        **common,
        model_assets=model_assets,
        results=offline_results,
        output=staging / "generated-offline-cache.wsb",
    )
    print(f"Sandbox memory: {memory_mb} MB")
    print(f"Package-only config: {package_config}")
    print(f"Offline-cache config: {offline_config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
