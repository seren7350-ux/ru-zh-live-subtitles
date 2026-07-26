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
    if torch_module is None:
        checks.extend(
            (
                Check("WARN", "CUDA available", "cannot be checked"),
                Check("WARN", "CUDA device", "cannot be checked"),
            )
        )
    else:
        try:
            cuda_available = bool(torch_module.cuda.is_available())
            checks.append(Check("OK" if cuda_available else "WARN", "CUDA available", str(cuda_available)))
            device = torch_module.cuda.get_device_name(0) if cuda_available else "none"
            checks.append(Check("OK" if cuda_available else "WARN", "CUDA device", device))
        except Exception as exc:
            checks.extend(
                (
                    Check("WARN", "CUDA available", f"query failed: {exc}"),
                    Check("WARN", "CUDA device", "cannot be checked"),
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
