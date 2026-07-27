"""Inspect direct, delayed, and recursive PE dependencies inside an onedir."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


PE_SUFFIXES = {".dll", ".exe", ".pyd"}
KNOWN_SYSTEM_DLLS = {
    "advapi32.dll",
    "bcrypt.dll",
    "cabinet.dll",
    "cfgmgr32.dll",
    "combase.dll",
    "comctl32.dll",
    "crypt32.dll",
    "d3d12.dll",
    "dbghelp.dll",
    "gdi32.dll",
    "imm32.dll",
    "iphlpapi.dll",
    "kernel32.dll",
    "mpr.dll",
    "msvcrt.dll",
    "ntdll.dll",
    "ole32.dll",
    "oleaut32.dll",
    "powrprof.dll",
    "rpcrt4.dll",
    "secur32.dll",
    "setupapi.dll",
    "shell32.dll",
    "shlwapi.dll",
    "user32.dll",
    "userenv.dll",
    "version.dll",
    "winhttp.dll",
    "winmm.dll",
    "ws2_32.dll",
}


def _decode_dll(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace")
    return str(value)


def _load_pefile() -> Any:
    try:
        import pefile
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PE analysis requires the packaging extra: install .[packaging]"
        ) from exc
    return pefile


def extract_import_names(pe: Any) -> tuple[list[str], list[str]]:
    """Extract ordinary and delay-load DLL basenames from a parsed PE."""

    imports = sorted(
        {_decode_dll(entry.dll) for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])},
        key=str.casefold,
    )
    delay_imports = sorted(
        {
            _decode_dll(entry.dll)
            for entry in getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])
        },
        key=str.casefold,
    )
    return imports, delay_imports


def is_system_dependency(name: str) -> bool:
    lowered = name.casefold()
    if (
        lowered in KNOWN_SYSTEM_DLLS
        or lowered.startswith("api-ms-win-")
        or lowered.startswith("ext-ms-win-")
    ):
        return True
    windows_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if not windows_root:
        return False
    return any(
        (Path(windows_root) / directory / name).is_file()
        for directory in ("System32", "SysWOW64")
    )


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def reject_absolute_output_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or (path.parts and path.parts[0].endswith(":")):
        raise ValueError(f"Absolute path is not allowed in PE output: {value}")
    return path.as_posix()


def _load_observed(path: Path | None) -> set[str]:
    if path is None:
        return set()
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return {
        reject_absolute_output_path(str(item["relative_path"]))
        for item in payload.get("modules", [])
        if item.get("category") == "dist" and item.get("relative_path")
    }


def analyze_pe_dependencies(
    distribution: Path, loaded_modules: Path | None = None
) -> dict[str, Any]:
    pefile = _load_pefile()
    root = distribution.resolve()
    if not root.is_dir():
        raise ValueError(f"Distribution directory does not exist: {root}")
    binaries = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.casefold() in PE_SUFFIXES
        ),
        key=str,
    )
    relative_by_path = {path: _relative(path, root) for path in binaries}
    canonical_by_casefold = {
        relative.casefold(): relative for relative in relative_by_path.values()
    }
    by_basename: dict[str, list[str]] = defaultdict(list)
    for relative in relative_by_path.values():
        by_basename[PurePosixPath(relative).name.casefold()].append(relative)

    direct: dict[str, Any] = {}
    missing: list[dict[str, str]] = []
    graph: dict[str, set[str]] = defaultdict(set)
    for path in binaries:
        relative = relative_by_path[path]
        try:
            pe = pefile.PE(str(path), fast_load=True)
            pe.parse_data_directories(
                directories=[
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
                ]
            )
            imports, delay_imports = extract_import_names(pe)
            pe.close()
        except pefile.PEFormatError as exc:
            direct[relative] = {"error": type(exc).__name__, "imports": [], "delay_imports": []}
            continue

        def resolve(names: Iterable[str], kind: str) -> list[dict[str, str]]:
            resolved: list[dict[str, str]] = []
            for name in names:
                candidates = sorted(by_basename.get(name.casefold(), []), key=str.casefold)
                if candidates:
                    target = candidates[0]
                    graph[relative].add(target)
                    resolved.append({"name": name, "category": "dist", "path": target})
                elif is_system_dependency(name):
                    resolved.append({"name": name, "category": "system"})
                else:
                    resolved.append({"name": name, "category": "missing"})
                    missing.append({"source": relative, "name": name, "kind": kind})
            return resolved

        direct[relative] = {
            "imports": resolve(imports, "import"),
            "delay_imports": resolve(delay_imports, "delay_import"),
        }

    observed = {
        canonical_by_casefold.get(relative.casefold(), relative)
        for relative in _load_observed(loaded_modules)
    }
    static_entries = sorted(
        {
            relative
            for relative in relative_by_path.values()
            if PurePosixPath(relative).suffix.casefold() in {".exe", ".pyd"}
        },
        key=str.casefold,
    )

    def transitive_closure(entry_paths: Iterable[str]) -> set[str]:
        closure: set[str] = set()
        queue: deque[str] = deque(entry_paths)
        while queue:
            current = queue.popleft()
            if current in closure:
                continue
            closure.add(current)
            queue.extend(sorted(graph.get(current, ()), key=str.casefold))
        return closure

    static_closure = transitive_closure(static_entries)
    entries = sorted(set(static_entries) | observed, key=str.casefold)
    closure = transitive_closure(entries)

    all_dist_binaries = set(relative_by_path.values())
    return {
        "direct_imports": direct,
        "recursive_closure": {
            "entries": entries,
            "files": sorted(closure, key=str.casefold),
            "static_entries": static_entries,
            "static_files": sorted(static_closure, key=str.casefold),
        },
        "missing_dependencies": sorted(
            missing, key=lambda item: (item["source"].casefold(), item["name"].casefold())
        ),
        "loaded_but_not_in_static_closure": sorted(
            observed - static_closure, key=str.casefold
        ),
        "closure_but_not_observed_loaded": sorted(
            (static_closure & all_dist_binaries) - observed, key=str.casefold
        ),
    }


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "direct_imports",
        "recursive_closure",
        "missing_dependencies",
        "loaded_but_not_in_static_closure",
        "closure_but_not_observed_loaded",
    ):
        (output_dir / f"{name}.json").write_text(
            json.dumps(payload[name], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--loaded-modules", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    payload = analyze_pe_dependencies(args.distribution, args.loaded_modules)
    write_outputs(payload, args.output_dir)
    print(f"PE files: {len(payload['direct_imports'])}")
    print(f"Closure files: {len(payload['recursive_closure']['files'])}")
    print(f"Missing dependencies: {len(payload['missing_dependencies'])}")
    print(
        "Loaded but not static closure: "
        f"{len(payload['loaded_but_not_in_static_closure'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
