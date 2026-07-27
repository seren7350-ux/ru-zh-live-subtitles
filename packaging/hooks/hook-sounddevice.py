"""Collect the Windows PortAudio binary required by the sounddevice wheel."""

from pathlib import Path

from PyInstaller.utils.hooks import get_module_file_attribute

module_directory = Path(get_module_file_attribute("sounddevice")).parent
portaudio_directory = module_directory / "_sounddevice_data" / "portaudio-binaries"
destination = "_sounddevice_data/portaudio-binaries"

# The default sounddevice Windows backend loads this DLL from package data.
binaries = [(str(portaudio_directory / "libportaudio64bit.dll"), destination)]
# Preserve the upstream PortAudio build/license notice shipped beside the DLL.
datas = [(str(portaudio_directory / "README.md"), destination)]
