#!/usr/bin/env python3
"""Stage the pinned PC-simulator libraries alongside the A1 Android assets."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
REPOSITORY = "https://github.com/chilchiltrips-boop/dronelab.git"
COMMIT = "0101b6d77ed9750633baf991664f8fce274da8f6"

# Only simulator input, pairing, presentation, and third-party notices.
UPSTREAM_FILES = (
    "companion.css", "flight-input.js", "pairing-code.js", "pairing-qr-ui.js",
    "remote-rtc.js", "js/inline-dialogs.js", "vendor/peerjs.min.js",
    "vendor/peerjs.LICENSE", "vendor/qrgen.js", "vendor/jsqr.js",
    "vendor/LICENSE-jsqr.txt", "vendor/LICENSE-qrcode-generator.txt",
)

def git(source, *args, capture=False, stdin=None):
    result = subprocess.run(["git", "-C", str(source), *args], input=stdin,
                            stdout=subprocess.PIPE if capture else None, check=True)
    return result.stdout


def stage(source, destination):
    revision = git(source, "rev-parse", "--verify", COMMIT + "^{commit}", capture=True)
    if revision.decode().strip() != COMMIT:
        raise ValueError("The DroneLab simulator checkout does not contain the pinned commit")
    for name in UPSTREAM_FILES:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git(source, "show", COMMIT + ":" + name, capture=True))
    shutil.copytree(ROOT / "assets", destination, dirs_exist_ok=True)


def run(output, source):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="areion-sim-") as workspace:
        scratch = Path(workspace)
        if source is None:
            source = scratch / "source"
            source.mkdir()
            git(source, "init", "-q")
            git(source, "remote", "add", "origin", REPOSITORY)
            git(source, "fetch", "--depth=1", "--no-tags", "--filter=blob:none", "origin", COMMIT)
            git(source, "sparse-checkout", "set", "--no-cone", "--stdin",
                stdin=("\n".join("/" + name for name in UPSTREAM_FILES) + "\n").encode())
            git(source, "checkout", "--detach", "--quiet", COMMIT)
        with tempfile.TemporaryDirectory(prefix=".pc-simulator-", dir=output) as temp:
            staged = Path(temp) / "simulator"
            stage(source, staged)
            destination = output / "simulator"
            if destination.exists():
                shutil.rmtree(destination)
            staged.rename(destination)
    print("Prepared PC simulator assets at", output / "simulator")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="generated Android assets root")
    parser.add_argument("--source", type=Path, help="optional local DroneLab Git repository")
    args = parser.parse_args()
    run(args.output.resolve(), args.source)
