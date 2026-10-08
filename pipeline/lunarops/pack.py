"""Write deterministic gzip copies of the web binaries (web/data/*.bin -> *.bin.gz).

The published site ships only the .gz files (≈ 4 MB instead of ≈ 19 MB); the browser
decompresses them (web/io.js). mtime is fixed so the same input gives the same bytes.

    python -m lunarops.pack
"""
from __future__ import annotations

import gzip
import hashlib

from .paths import WEB_DATA


def main():
    total = 0
    for p in sorted(WEB_DATA.glob("*.bin")):
        raw = p.read_bytes()
        gz = gzip.compress(raw, compresslevel=9, mtime=0)
        assert gzip.decompress(gz) == raw
        out = p.with_name(p.name + ".gz")
        if not out.exists() or out.read_bytes() != gz:
            out.write_bytes(gz)
        total += len(gz)
        print(f"{out.name:42s} {len(gz) / 1e3:7.0f} kB  sha256 {hashlib.sha256(raw).hexdigest()[:12]}")
    print(f"total {total / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
