"""Non-invasive environment diagnostics for the command-line application."""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from . import __version__
from .config import (
    DEFAULT_ASR_BACKEND,
    DEFAULT_ASR_MODEL,
    PROJECT_ROOT,
    hugging_face_cache_dir,
)

Status = Literal["OK", "WARN", "FAIL"]


@dataclass(frozen=True)
class Check:
    """One human-readable diagnostic result."""

    status: Status
    name: str
    detail: str


@dataclass(frozen=True)
class DiagnosticReport:
    """Complete set of diagnostic checks and summary counts."""

    checks: tuple[Check, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {status: sum(item.status == status for item in self.checks) for status in ("OK", "WARN", "FAIL")}

    @property
    def exit_code(self) -> int:
        return 1 if self.counts["FAIL"] else 0


def _load_module(
    name: str,
    display_name: str,
    checks: list[Check],
    *,
    required: bool = True,
) -> Any | None:
    try:
        module = importlib.import_module(name)
    except Exception as exc:  # diagnostics must survive broken optional/native imports
        checks.append(
            Check("FAIL" if required else "WARN", display_name, f"not importable: {exc}")
        )
        return None
    version = getattr(module, "__version__", "version unavailable")
    checks.append(Check("OK", display_name, str(version)))
    return module


def _default_input_index(sounddevice_module: Any) -> int | None:
    value = sounddevice_module.default.device
    if not isinstance(value, (int, float, str, bytes)):
        try:
            value = value[0]
        except (IndexError, KeyError, TypeError):
            return None
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if index >= 0 else None


def _nvidia_checks(checks: list[Check]) -> None:
    executable = shutil.which("nvidia-smi")
    if not executable:
        checks.extend(
            (
                Check("WARN", "nvidia-smi", "not found"),
                Check("WARN", "GPU names", "not available because nvidia-smi was not found"),
            )
        )
        return
    checks.append(Check("OK", "nvidia-smi", executable))
    try:
        result = subprocess.run(
            [executable, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        names = ", ".join(line.strip() for line in result.stdout.splitlines() if line.strip())
        if result.returncode == 0 and names:
            checks.append(Check("OK", "GPU names", names))
        else:
            detail = result.stderr.strip() or f"nvidia-smi exited with {result.returncode}"
            checks.append(Check("WARN", "GPU names", detail))
    except Exception as exc:
        checks.append(Check("WARN", "GPU names", f"query failed: {exc}"))


def collect_diagnostics() -> DiagnosticReport:
    """Collect status without loading ASR models or opening the microphone."""

    checks: list[Check] = [
        Check("OK", "Application version", __version__),
        Check("OK", "Python executable", sys.executable),
        Check("OK", "Python version", platform.python_version()),
        Check("OK", "Operating system", platform.platform()),
        Check("OK", "Current working directory", str(Path.cwd())),
        Check("OK", "Project root", str(PROJECT_ROOT)),
        Check("OK" if sys.prefix != sys.base_prefix else "WARN", "Virtual environment", "active" if sys.prefix != sys.base_prefix else "not active"),
    ]

    _load_module("numpy", "numpy", checks)
    sounddevice_module = _load_module("sounddevice", "sounddevice", checks)
    _load_module("torch", "torch", checks)
    _load_module("torchaudio", "torchaudio", checks)
    _load_module("transformers", "transformers", checks)
    _load_module("hydra", "hydra-core", checks)
    _load_module("omegaconf", "omegaconf", checks)
    _load_module("onnx_asr", "onnx_asr (legacy ASR only)", checks, required=False)
    onnxruntime_module = _load_module("onnxruntime", "onnxruntime", checks)

    if onnxruntime_module is None:
        checks.extend(
            (
                Check("FAIL", "ONNX Runtime providers", "unavailable"),
                Check("FAIL", "CPUExecutionProvider", "cannot be checked"),
                Check("WARN", "CUDAExecutionProvider", "cannot be checked"),
            )
        )
    else:
        try:
            providers = list(onnxruntime_module.get_available_providers())
            checks.append(Check("OK", "ONNX Runtime providers", ", ".join(providers) or "none"))
            checks.append(Check("OK" if "CPUExecutionProvider" in providers else "FAIL", "CPUExecutionProvider", "available" if "CPUExecutionProvider" in providers else "missing"))
            checks.append(Check("OK" if "CUDAExecutionProvider" in providers else "WARN", "CUDAExecutionProvider", "available" if "CUDAExecutionProvider" in providers else "not installed (CPU baseline is supported)"))
        except Exception as exc:
            checks.extend(
                (
                    Check("FAIL", "ONNX Runtime providers", f"query failed: {exc}"),
                    Check("FAIL", "CPUExecutionProvider", "cannot be checked"),
                    Check("WARN", "CUDAExecutionProvider", "cannot be checked"),
                )
            )

    _nvidia_checks(checks)

    if sounddevice_module is None:
        checks.extend(
            (
                Check("WARN", "Audio input devices", "cannot be checked"),
                Check("WARN", "Default input device", "cannot be checked"),
            )
        )
    else:
        try:
            devices = list(sounddevice_module.query_devices())
            inputs = [(index, device) for index, device in enumerate(devices) if int(device.get("max_input_channels", 0)) > 0]
            checks.append(Check("OK" if inputs else "WARN", "Audio input devices", str(len(inputs))))
            default_index = _default_input_index(sounddevice_module)
            default_name = None
            if default_index is not None and 0 <= default_index < len(devices):
                default_name = str(devices[default_index].get("name", f"device {default_index}"))
            checks.append(Check("OK" if default_name else "WARN", "Default input device", default_name or "not configured"))
        except Exception as exc:
            checks.extend(
                (
                    Check("WARN", "Audio input devices", f"query failed: {exc}"),
                    Check("WARN", "Default input device", "cannot be checked"),
                )
            )

    cache_dir = hugging_face_cache_dir()
    checks.extend(
        (
            Check("OK" if cache_dir.exists() else "WARN", "Hugging Face cache", f"{cache_dir} ({'exists' if cache_dir.exists() else 'not created yet'})"),
            Check("OK", "ASR backend", DEFAULT_ASR_BACKEND),
            Check("OK", "ASR model", DEFAULT_ASR_MODEL),
            Check("WARN", "Model setup", "the immutable snapshot must be staged before first use"),
            Check("OK", "Offline inference", "runtime loading is local_files_only and forces offline mode"),
        )
    )
    return DiagnosticReport(tuple(checks))


def format_report(report: DiagnosticReport) -> str:
    lines = [f"[{item.status}] {item.name}: {item.detail}" for item in report.checks]
    counts = report.counts
    lines.append(
        "Summary: "
        f"total={len(report.checks)} OK={counts['OK']} WARN={counts['WARN']} FAIL={counts['FAIL']}"
    )
    return os.linesep.join(lines)
