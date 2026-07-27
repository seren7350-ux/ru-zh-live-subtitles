"""Conservative Windows Torch hook with evidence-based test-module filtering."""

import os

from PyInstaller.utils.hooks import (
    PY_DYLIB_PATTERNS,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


def _runtime_torch_module(name: str) -> bool:
    """Keep Torch runtime modules while excluding its private test suite."""

    if name.startswith("torch.testing._internal"):
        # torch._refs imports this dtype table during normal Transformers use.
        return name in {
            "torch.testing._internal",
            "torch.testing._internal.common_dtype",
        }
    return not (
        name.startswith("torch.fx.passes.tests")
        or name.startswith("torch.onnx.testing")
        or name.startswith("torch._numpy.testing")
        or name.startswith("torch._dynamo.testing")
    )


# Torch dynamically imports backends and operator packages; collect its runtime
# submodules, but use the predicate above to omit verified test-only modules.
hiddenimports = collect_submodules("torch", filter=_runtime_torch_module)
# Torch's wheel ships runtime configuration/data files alongside Python modules.
datas = collect_data_files(
    "torch",
    excludes=[
        "**/*.h",
        "**/*.hpp",
        "**/*.cuh",
        "**/*.lib",
        "**/*.cpp",
        "**/*.pyi",
        "**/*.cmake",
        "**/testing/_internal/**",
        "**/fx/passes/tests/**",
    ],
)
# Preserve all wheel-provided Torch/CUDA DLLs; no unknown binary is pruned.
binaries = collect_dynamic_libs(
    "torch",
    search_patterns=PY_DYLIB_PATTERNS + ["*.so.*"],
)

module_collection_mode = os.environ.get("RU_ZH_TORCH_COLLECTION_MODE", "pyz+py")
if module_collection_mode not in {"pyz", "pyz+py"}:
    raise RuntimeError(
        "RU_ZH_TORCH_COLLECTION_MODE must be either 'pyz' or 'pyz+py'"
    )
warn_on_missing_hiddenimports = False
