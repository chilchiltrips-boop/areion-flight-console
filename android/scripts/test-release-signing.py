"""Exercise stable signing on a real release APK with a disposable offline key."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


scripts = Path(__file__).resolve().parent
unsigned = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as work:
    environment = {**os.environ, "HOME": work}
    subprocess.run([sys.executable, scripts / "setup-signing.py", "--offline"], env=environment, check=True)
    backup = Path(work) / ".areion/android-signing"
    bundle = {
        "keystore": base64.b64encode((backup / "release.p12").read_bytes()).decode("ascii"),
        "password": (backup / "password").read_text().strip(),
        "alias": "areion-release",
        "fingerprint": (backup / "sha256.txt").read_text().strip(),
    }
    environment["AREION_ANDROID_SIGNING_BUNDLE"] = json.dumps(bundle)
    output = Path(work) / "signed"
    command = [sys.executable, scripts / "sign-release.py", unsigned, output]
    subprocess.run([*command, backup / "certificate.pem"], env=environment, check=True)
    if (output / "Areion-signing-certificate.pem").read_text() != (backup / "certificate.pem").read_text():
        raise SystemExit("Released public certificate differs from the owner's backup.")
    bundle["fingerprint"] = "0" * 64
    environment["AREION_ANDROID_SIGNING_BUNDLE"] = json.dumps(bundle)
    rejected = subprocess.run(command, env=environment, capture_output=True, text=True)
    if rejected.returncode == 0 or "does not match the configured SHA-256" not in rejected.stderr:
        raise SystemExit("Signing identity mismatch was not rejected as expected.")
print("Verified release signing and fingerprint mismatch handling with a disposable key.")
