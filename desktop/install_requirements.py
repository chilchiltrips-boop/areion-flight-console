"""Run with the selected PyCharm interpreter; installs from this folder."""
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parent
    print(f"Installing Areion requirements and SDK using: {sys.executable}", flush=True)
    print(f"Project: {root}", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(root / "requirements.txt")],
        cwd=root, check=False)
    if result.returncode == 0:
        print("Installation complete. Restart any old Python Console, then Run main.py.")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
