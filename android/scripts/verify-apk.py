"""Validate the installed app's offline console and unchanged A1 wire schema."""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
with ZipFile(sys.argv[1]) as apk:
    names = set(apk.namelist())
    prefix = "assets/console/"
    required = ["index.html", "protocol.js", "wifi.js", "ap-session-port.js", "ap-worker-runtime.js",
                "android-console/native-host.js", "android-console/app-entry.js",
                "android-console/mobile.css", "android-console/touch-deck.js", "android-console/touch-deck.css",
                "configuration.js", "scopes.js", "system.js", "assembly/viewer.html", "firmware-release/manifest.json"]
    missing = [name for name in required if prefix + name not in names]
    if missing:
        raise ValueError("Missing APK assets: " + ", ".join(missing))
    index = apk.read(prefix + "index.html").decode()
    bridge = index.index('src="./android-console/native-host.js"')
    entry = index.index('src="./android-console/app-entry.js"')
    if bridge >= entry or 'src="./app.js"></script>' in index:
        raise ValueError("The installed console would start without its native bridge")
    if apk.read(prefix + "protocol.js") != (ROOT / "web/protocol.js").read_bytes():
        raise ValueError("Android and the A1 console use different protocol implementations")
    firmware = json.loads(apk.read(prefix + "firmware-release/manifest.json"))
    for item in [*firmware["images"].values(), firmware["sources"]]:
        data = apk.read(prefix + "firmware-release/" + item["file"])
        if hashlib.sha256(data).hexdigest() != item["sha256"] or len(data) != item["bytes"]:
            raise ValueError("Firmware asset mismatch: " + item["file"])
    if not any(name.startswith("assets/simulator/") and name.endswith(".html") for name in names):
        raise ValueError("Missing PC simulator pairing screen")
    if any(name.endswith((".jks", ".keystore")) for name in names):
        raise ValueError("Signing material cannot be an app asset")
    if "classes.dex" not in names or "AndroidManifest.xml" not in names:
        raise ValueError("Invalid APK")
    print("APK includes the A1 protocol, both touch views and offline firmware", firmware["version"])
