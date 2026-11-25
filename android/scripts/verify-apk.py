"""Check the APK contains only the installed AP controller and its shared A1 modules."""
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "android" / "controller"
PREFIX = "assets/controller/"
LOCAL_FILES = {"index.html", "app.js", "controller.js", "controller.css", "native-host.js", "touch-input.js"}
SHARED = json.loads((ROOT / "android" / "shared-modules.json").read_text())


def check_apk(apk_file):
    with ZipFile(apk_file) as apk:
        names = {entry.filename for entry in apk.infolist() if not entry.is_dir()}
        assets = {name for name in names if name.startswith("assets/") and not re.fullmatch(r"assets/dexopt/baseline\.profm?", name)}
        required = {PREFIX + name for name in LOCAL_FILES} | {PREFIX + "shared/" + name for name in SHARED}
        if assets != required:
            raise ValueError(f"Unexpected APK assets: missing {sorted(required - assets)}, extra {sorted(assets - required)}")
        for name in LOCAL_FILES:
            expected = (SOURCE / name).read_bytes()
            if name == "controller.js":
                expected = re.sub(rb"""(['"])\.\./\.\./web/([\w-]+\.js)\1""", rb"\1./shared/\2\1", expected)
            if apk.read(PREFIX + name) != expected:
                raise ValueError("Controller asset differs from source: " + name)
        for name in SHARED:
            if apk.read(PREFIX + "shared/" + name) != (ROOT / "web" / name).read_bytes():
                raise ValueError("Packaged link or command module differs from Areion: " + name)
        for name in names:
            if name.endswith((".jks", ".keystore")):
                raise ValueError("Unexpected signing key in APK")
        if not {"classes.dex", "AndroidManifest.xml"}.issubset(names):
            raise ValueError("Invalid APK")
    print(f"Verified control-only APK with {len(LOCAL_FILES)} controller assets and {len(SHARED)} unchanged A1 modules.")


if __name__ == "__main__":
    check_apk(sys.argv[1])
