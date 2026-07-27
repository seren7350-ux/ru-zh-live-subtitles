# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

project_root = Path(SPECPATH).parent

a = Analysis(
    [str(project_root / "packaging" / "entrypoint.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[
        (str(project_root / "README.md"), "."),
        (str(project_root / "THIRD_PARTY_NOTICES.md"), "."),
        (str(Path(sys.base_prefix) / "LICENSE.txt"), "licenses/python"),
        (str(Path(sys.base_prefix) / "tcl" / "tk8.6" / "license.terms"), "licenses/tk"),
    ],
    hiddenimports=[],
    hookspath=[str(project_root / "packaging" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "pip",
        "coverage",
        "sacrebleu",
        "notebook",
        "jupyter",
        "torch.fx.passes.tests",
        "torch.onnx.testing",
        "torch._numpy.testing",
        "torch._dynamo.testing",
        "sympy.testing",
        "transformers.testing_utils",
        "transformers.utils.notebook",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ru-zh-subtitles-console",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ru-zh-subtitles-console",
)
