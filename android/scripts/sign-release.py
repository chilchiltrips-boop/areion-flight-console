"""Sign the tested build's release variant and verify its public update identity."""
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile


def sign(unsigned_apk, output, previous_certificate=None):
    os.umask(0o077)
    try:
        bundle = json.loads(os.environ.pop("AREION_ANDROID_SIGNING_BUNDLE", ""))
        key_bytes = base64.b64decode(bundle["keystore"], validate=True)
        password, alias, fingerprint = (bundle[name] for name in ("password", "alias", "fingerprint"))
        if not key_bytes or not all(isinstance(value, str) and value for value in (password, alias, fingerprint)):
            raise ValueError()
        if not re.fullmatch("[0-9a-f]{64}", fingerprint):
            raise ValueError()
    except (KeyError, TypeError, ValueError, binascii.Error):
        raise SystemExit("Configure the AREION_ANDROID_SIGNING_BUNDLE repository secret with a valid PKCS12 bundle.") from None

    if previous_certificate:
        der = ssl.PEM_cert_to_DER_cert(previous_certificate.read_text())
        if hashlib.sha256(der).hexdigest() != fingerprint:
            raise SystemExit("Signing certificate differs from the previous stable release.")

    apksigner = Path(os.environ["ANDROID_HOME"]) / "build-tools/35.0.0/apksigner"
    output.mkdir(parents=True, exist_ok=True)
    signed_apk = output / "Areion-Drone-Control.apk"
    with tempfile.TemporaryDirectory() as directory:
        key = Path(directory) / "release.p12"
        key.write_bytes(key_bytes)
        key_env = {**os.environ, "AREION_SIGN_PASS": password}
        cert = subprocess.check_output([
            "keytool", "-exportcert", "-alias", alias, "-keystore", key, "-storetype", "PKCS12",
            "-storepass:env", "AREION_SIGN_PASS",
        ], env=key_env)
        if hashlib.sha256(cert).hexdigest() != fingerprint:
            raise SystemExit("PKCS12 certificate does not match the configured SHA-256 fingerprint.")
        subprocess.run([
            apksigner, "sign", "--ks", key, "--ks-type", "PKCS12", "--ks-key-alias", alias,
            "--ks-pass", "env:AREION_SIGN_PASS", "--key-pass", "env:AREION_SIGN_PASS",
            "--v4-signing-enabled", "false", "--out", signed_apk, unsigned_apk,
        ], env=key_env, check=True)

    verified = subprocess.check_output([apksigner, "verify", "--verbose", "--print-certs", signed_apk], text=True)
    signers = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)$", verified, re.MULTILINE)
    if [digest.lower() for digest in signers] != [fingerprint] or "Verified using v2 scheme (APK Signature Scheme v2): true" not in verified:
        raise SystemExit("Signed APK failed the release certificate or Android 8 signature check.")
    (output / "Areion-signing-certificate.pem").write_text(ssl.DER_cert_to_PEM_cert(cert))
    print("Verified APK signer SHA-256:", fingerprint)


if __name__ == "__main__":
    sign(*map(Path, sys.argv[1:]))
