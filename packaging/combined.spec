# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

project_root = Path(SPECPATH).parent
sys.path.insert(0, str(project_root / "packaging"))

import optimization_profile
import torch

profile_name = os.environ.get("RU_ZH_PACKAGE_PROFILE", "baseline")
torch_lib = Path(torch.__file__).resolve().parent / "lib"
profile_validation = optimization_profile.validate_profile(
    profile_name,
    torch_version=torch.__version__,
    cuda_version=str(torch.version.cuda),
    torch_dlls=torch_lib.glob("*.dll"),
)

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
a.datas = optimization_profile.filter_collected_datas(profile_name, a.datas)
excluded_binary_names = {
    name.casefold() for name in profile_validation.excluded_binary_names
}
if excluded_binary_names:
    a.binaries = [
        entry
        for entry in a.binaries
        if Path(str(entry[0])).name.casefold() not in excluded_binary_names
    ]
pyz = PYZ(a.pure)

console_exe = EXE(
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

windowed_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ru-zh-subtitles",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    console_exe,
    windowed_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ru-zh-subtitles",
)
