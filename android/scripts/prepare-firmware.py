"""Use the A1 firmware built from this checkout, or its matching published release."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://chilchiltrips-boop.github.io/areion-flight-console/firmware-release/"
FILENAMES = {"bootloader.bin", "partitions.bin", "selector.bin", "application.bin", "arduino-sources.zip"}


def download(name, dest):
    with urlopen(BASE + name, timeout=90) as response, (dest / name).open("wb") as output:
        shutil.copyfileobj(response, output)


def validate(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    parts = [*manifest["images"].values(), manifest["sources"]]
    if manifest["board"] != "Areion FC A1" or {item["file"] for item in parts} != FILENAMES:
        raise ValueError("Unexpected A1 release manifest")
    for item in parts:
        raw = (folder / item["file"]).read_bytes()
        if len(raw) != item["bytes"] or sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("Incorrect release asset: " + item["file"])
    source_root = ROOT / "firmware"
    files = {path.relative_to(source_root).as_posix(): path for path in source_root.rglob("*") if path.is_file()}
    with ZipFile(folder / "arduino-sources.zip") as archive:
        if set(archive.namelist()) != set(files) or any(archive.read(name) != path.read_bytes() for name, path in files.items()):
            raise ValueError("Firmware sources differ. Build this checkout's A1 firmware using the Pages build.")
    return manifest["version"]


def main():
    target = ROOT / "build/firmware-release"
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        print("Using verified A1 firmware", validate(target))
        return
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        folder = Path(tmp)
        download("manifest.json", folder)
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda name: download(name, folder), FILENAMES))
        version = validate(folder)
        folder.rename(target)
        print("Bundled published A1 firmware", version)


if __name__ == "__main__":
    main()
