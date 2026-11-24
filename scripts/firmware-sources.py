"""Make the offline Arduino source bundle from the same checkout as the binaries."""
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

root = Path(__file__).resolve().parents[1] / "firmware"
with ZipFile(sys.argv[1], "w") as archive:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entry = ZipInfo(path.relative_to(root).as_posix(), (2026, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, path.read_bytes())
