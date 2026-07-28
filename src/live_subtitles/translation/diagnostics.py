"""Translation-specific checks that never load a tokenizer or model."""

from __future__ import annotations

import importlib
from typing import Any

from ..config import (
    DEFAULT_TRANSLATION_ENGINE,
    DEFAULT_TRANSLATION_MODEL,
    hugging_face_model_cache_dir,
)
from ..diagnostics import Check, DiagnosticReport
from ..runtime_paths import is_frozen


def _import(name: str, checks: list[Check]) -> Any | None:
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        checks.append(Check("FAIL", name, f"not importable: {exc}"))
        return None
    checks.append(Check("OK", name, str(getattr(module, "__version__", "version unavailable"))))
    return module


def collect_translation_diagnostics() -> DiagnosticReport:
    """Inspect dependencies, CUDA, and cache presence without model loading."""

    checks: list[Check] = []
    torch_module = _import("torch", checks)
    _import("transformers", checks)
    frozen = is_frozen()
    checks.append(Check("OK", "Frozen state", str(frozen)))
    if torch_module is None:
        checks.extend(
            (
                Check("FAIL", "Package runtime family", "cannot be determined"),
                Check("WARN", "Torch CUDA version", "cannot be checked"),
                Check("WARN", "CUDA available", "cannot be checked"),
                Check("WARN", "CUDA device", "cannot be checked"),
                Check("WARN", "Selected translation device", "cannot be determined"),
            )
        )
    else:
        torch_cuda_version = getattr(getattr(torch_module, "version", None), "cuda", None)
        runtime_family = (
            "source"
            if not frozen
            else "cpu"
            if torch_cuda_version is None
            else "gpu"
        )
        checks.extend(
            (
                Check("OK", "Package runtime family", runtime_family),
                Check("OK", "Torch CUDA version", str(torch_cuda_version)),
            )
        )
        try:
            cuda_available = bool(torch_module.cuda.is_available())
            checks.append(Check("OK" if cuda_available else "WARN", "CUDA available", str(cuda_available)))
            device = torch_module.cuda.get_device_name(0) if cuda_available else "none"
            checks.append(Check("OK" if cuda_available else "WARN", "CUDA device", device))
            checks.append(
                Check(
                    "OK",
                    "Selected translation device",
                    "cuda" if cuda_available else "cpu",
                )
            )
        except Exception as exc:
            checks.extend(
                (
                    Check("WARN", "CUDA available", f"query failed: {exc}"),
                    Check("WARN", "CUDA device", "cannot be checked"),
                    Check("WARN", "Selected translation device", "cannot be determined"),
                )
            )

    model_cache = hugging_face_model_cache_dir(DEFAULT_TRANSLATION_MODEL)
    checks.extend(
        (
            Check(
                "OK",
                "Default translation candidate",
                f"{DEFAULT_TRANSLATION_ENGINE}: {DEFAULT_TRANSLATION_MODEL}",
            ),
            Check("OK" if model_cache.exists() else "WARN", "Model cache", f"{model_cache} ({'exists' if model_cache.exists() else 'not cached'})"),
            Check("WARN", "First model load", "requires internet if the model is not cached"),
            Check("OK", "Offline translation", "available after caching with HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1"),
        )
    )
    return DiagnosticReport(tuple(checks))
