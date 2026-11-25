#!/usr/bin/env python3
"""Provision the Areion Android signing key from its owner's computer."""

import argparse
import base64
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import stat
import subprocess
import sys
import tempfile


REPOSITORY = "chilchiltrips-boop/areion-flight-console"
SECRET = "AREION_ANDROID_SIGNING_BUNDLE"
ALIAS = "areion-release"
BACKUP = Path.home() / ".areion" / "android-signing"


def command(args, failure, payload=None):
    try:
        result = subprocess.run(args, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        if args[0] == "gh":
            raise ValueError("Install the GitHub CLI (on macOS, 'brew install gh'), then rerun setup.") from None
        if args[0] == "keytool":
            raise ValueError("Install a Java Development Kit that includes keytool, then rerun setup.") from None
        raise
    if result.returncode:
        raise ValueError(failure)
    return result.stdout


def secret_version():
    response = command(
        ["gh", "secret", "list", "--repo", REPOSITORY, "--json", "name,updatedAt"],
        "Cannot list repository secrets. Run 'gh auth login --hostname github.com --web' with an account that can manage Actions secrets.",
    )
    for secret in json.loads(response):
        if secret["name"] == SECRET:
            return secret["updatedAt"]
    return None


def published_fingerprint():
    tags = command(["gh", "api", "--paginate", f"repos/{REPOSITORY}/releases?per_page=100",
                    "--jq", ".[] | select(.draft == false) | .tag_name"],
                   "Cannot check published Android releases. Retry when GitHub is available.")
    releases = []
    for tag in tags.decode().splitlines():
        match = re.fullmatch(r"android-v[0-9.]+-stable\.([0-9]+)", tag)
        if match:
            releases.append((int(match[1]), tag))
    if not releases:
        return None
    tag = max(releases)[1]
    pem = command(["gh", "release", "download", tag, "--repo", REPOSITORY,
                   "--pattern", "Areion-signing-certificate.pem", "--output", "-"],
                  f"Cannot verify the public signing certificate for {tag}. Restore access and retry.")
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem.decode("ascii"))).hexdigest()


def check_private(path, directory=False):
    info = path.lstat()
    right_type = stat.S_ISDIR if directory else stat.S_ISREG
    if info.st_uid != os.getuid() or not right_type(info.st_mode) or info.st_mode & 0o077:
        raise ValueError(f"Check ownership and private permissions on {path}.")


def keytool(directory, operation):
    return command(
        ["keytool", *operation, "-alias", ALIAS, "-storetype", "PKCS12",
         "-keystore", str(directory / "release.p12"),
         "-storepass:file", str(directory / "password")],
        "keytool could not create or read the signing identity. Check the JDK and local backup.",
    )


def sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError as error:
        if (sys.platform == "darwin" and stat.S_ISDIR(os.fstat(fd).st_mode)
                and error.errno in (errno.EINVAL, errno.ENOTSUP)):
            # Some macOS filesystems support flushing files but reject directory fsync.
            os.sync()
        else:
            raise
    finally:
        os.close(fd)


def create_backup():
    with tempfile.TemporaryDirectory(prefix=".key-", dir=BACKUP.parent) as staging:
        stage = Path(staging)
        (stage / "password").write_text(secrets.token_urlsafe(36) + "\n")
        keytool(stage, ["-genkeypair", "-keyalg", "RSA", "-keysize", "4096",
                        "-sigalg", "SHA256withRSA", "-validity", "10000",
                        "-dname", "CN=Areion Drone Control"])
        certificate = keytool(stage, ["-exportcert"])
        (stage / "certificate.pem").write_text(ssl.DER_cert_to_PEM_cert(certificate))
        (stage / "sha256.txt").write_text(hashlib.sha256(certificate).hexdigest() + "\n")
        for path in stage.iterdir():
            sync(path)
        sync(stage)
        stage.rename(BACKUP)
        sync(BACKUP.parent)


def local_identity():
    check_private(BACKUP, directory=True)
    for name in ("release.p12", "password", "certificate.pem", "sha256.txt"):
        check_private(BACKUP / name)
    certificate = keytool(BACKUP, ["-exportcert"])
    fingerprint = hashlib.sha256(certificate).hexdigest()
    if ((BACKUP / "sha256.txt").read_text().strip() != fingerprint or
            ssl.PEM_cert_to_DER_cert((BACKUP / "certificate.pem").read_text()) != certificate):
        raise ValueError("The public certificate and keystore disagree. Restore the matching backup.")
    return fingerprint


def provision(offline):
    remote = None if offline else secret_version()
    published = None if offline or remote else published_fingerprint()
    if not BACKUP.exists():
        if remote or published:
            raise ValueError("This repository already has a signing identity. Restore the original local backup.")
        create_backup()
    fingerprint = local_identity()
    print(f"Signing backup: {BACKUP}\nCertificate SHA-256: {fingerprint}", flush=True)
    if offline:
        return
    # GitHub never returns a secret's value. Use a receipt only for a previously
    # acknowledged upload from this backup. An unknown secret stays untouched.
    receipt = BACKUP / "github-receipt.json"
    if remote:
        if receipt.is_file() and json.loads(receipt.read_text()) == [fingerprint, remote]:
            print("The previously uploaded signing secret is present.")
            return
        raise ValueError("A signing secret already exists. Compare the release APK certificate fingerprint with the one above. The existing secret was preserved.")
    if published and published != fingerprint:
        raise ValueError("The local key differs from the published Android release certificate. Restore the original backup.")
    if secret_version():
        raise ValueError("A signing secret appeared during setup. Rerun to check its identity.")
    payload = {
        "alias": ALIAS,
        "password": (BACKUP / "password").read_text().strip(),
        "keystore": base64.b64encode((BACKUP / "release.p12").read_bytes()).decode("ascii"),
        "fingerprint": fingerprint,
    }
    command(["gh", "secret", "set", SECRET, "--repo", REPOSITORY],
            "GitHub did not confirm the signing secret upload. Your key is backed up. Rerun this command to check.",
            json.dumps(payload).encode("utf-8"))
    remote = secret_version()
    if not remote:
        raise ValueError("GitHub has not confirmed the secret. Rerun setup using this backup.")
    pending = BACKUP / ".receipt.tmp"
    pending.write_text(json.dumps([fingerprint, remote]) + "\n")
    sync(pending)
    pending.replace(receipt)
    sync(BACKUP)
    print(f"Configured {SECRET} for {REPOSITORY}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="prepare or verify the local backup only")
    mode.add_argument("--publish", action="store_true", help="start the signed Android release build after setup")
    args = parser.parse_args()
    os.umask(0o077)
    BACKUP.parent.mkdir(mode=0o700, exist_ok=True)
    check_private(BACKUP.parent, directory=True)
    fd = os.open(BACKUP.parent, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        provision(args.offline)
    finally:
        os.close(fd)
    if args.publish:
        command(["gh", "workflow", "run", "android.yml", "--repo", REPOSITORY,
                 "--ref", "main", "-f", "publish_stable=true"],
                "GitHub did not confirm the release build. Check Actions for the run before retrying with --publish.")
        print(f"Started the Android release build: https://github.com/{REPOSITORY}/actions/workflows/android.yml")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
