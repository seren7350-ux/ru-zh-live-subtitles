"""Build a Windows CPU offline executable from the validated onedir and model bundle."""
import argparse
import hashlib

import os
from pathlib import Path
import shutil
import subprocess
import tarfile


def main():
    ap = argparse.ArgumentParser()
    for arg in ("runtime", "models", "work", "output"):
        ap.add_argument(arg, type=Path)
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    archive = args.work / "payload.tar.xz"
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from model_bundle import validate_model_bundle
    from cpu_package_policy import validate_cpu_distribution
    validate_model_bundle(args.models)
    validate_cpu_distribution(args.runtime)
    records = []
    with archive.open("wb") as sink, subprocess.Popen(
        ["7z", "a", "-txz", "-mx=3", "-mmt=4", "-si", "-so", "payload.xz"],
        stdin=subprocess.PIPE, stdout=sink
    ) as proc:
        with proc.stdin, tarfile.open(fileobj=proc.stdin, mode="w|", dereference=True) as tar:
            for root, prefix in ((args.runtime, "app"), (args.models, "profile/ru-zh-live-subtitles/models")):
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        name = prefix + "/" + path.relative_to(root).as_posix()
                        tar.add(path, name, recursive=False)
                        with path.open("rb") as f:
                            records.append(hashlib.file_digest(f,"sha256").hexdigest() + " " + name)
        if proc.wait():
            raise RuntimeError("compression failed")
    index = args.work / "index.txt"
    index.write_text("\n".join(records),encoding="utf-8")
    with archive.open("rb") as f:
        ident = hashlib.file_digest(f,"sha256").hexdigest()
    source = args.work / "Launcher.cs"
    source.write_text(Path(__file__).with_name("Launcher.cs").read_text().replace("__PAYLOAD_HASH__",ident),encoding="utf-8")
    stub = args.work / "launcher.exe"
    csc = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    subprocess.run([csc,"/nologo","/target:winexe","/platform:x64","/r:System.Windows.Forms.dll",
                    "/resource:"+str(index)+",index","/out:"+str(stub),source],check=True)
    with args.output.open("xb") as target:
        for path in (stub,archive):
            with path.open("rb") as src:
                shutil.copyfileobj(src,target,1024*1024)
        target.write(stub.stat().st_size.to_bytes(8,"little"))


if __name__ == "__main__":
    main()

