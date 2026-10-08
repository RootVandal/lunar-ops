"""Download the files listed in data/manifest.yaml and pin their SHA-256.

First download of a file records sha256/size/Last-Modified in
data/manifest.lock.json. Later runs re-verify local files against the lock and
refuse to continue if a file changed, so every result can be traced to exact
bytes.

Usage:
    python -m lunarops.fetch            # MVP set
    python -m lunarops.fetch --set optional --only pds_ldem_80m
    python -m lunarops.fetch --verify   # re-hash local files only
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import requests
import yaml

from .paths import DATA

MANIFEST = DATA / "manifest.yaml"
LOCK = DATA / "manifest.lock.json"
CHUNK = 1 << 20


class FetchError(RuntimeError):
    pass


def load_manifest() -> dict:
    with MANIFEST.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_lock() -> dict:
    if LOCK.exists():
        return json.loads(LOCK.read_text(encoding="utf-8"))
    return {}


def save_lock(lock: dict) -> None:
    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def download(entry: dict, dest: Path) -> tuple[str, str]:
    """Stream to a .part file, check the size, then move into place."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    with requests.get(entry["url"], stream=True, timeout=60) as r:
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "")
        if "text/html" in ctype:
            raise FetchError(f"{entry['id']}: server returned HTML, not data ({entry['url']})")
        last_mod = r.headers.get("Last-Modified", "")
        got = 0
        with part.open("wb") as f:
            for block in r.iter_content(CHUNK):
                f.write(block)
                h.update(block)
                got += len(block)
                if entry.get("size"):
                    print(f"\r  {entry['id']}: {got / 1e6:8.1f} / {entry['size'] / 1e6:.1f} MB", end="", flush=True)
    print()
    if entry.get("size") and got != entry["size"]:
        part.unlink(missing_ok=True)
        raise FetchError(f"{entry['id']}: size {got} != manifest {entry['size']} (source changed?)")
    part.replace(dest)
    return h.hexdigest(), last_mod


def run(selected_set: str, only: set[str] | None, verify_only: bool) -> int:
    manifest = load_manifest()
    lock = load_lock()
    failures = 0
    for entry in manifest["files"]:
        if entry["set"] != selected_set and not (only and entry["id"] in only):
            continue
        if only and entry["id"] not in only:
            continue
        if entry.get("range_only"):
            print(f"skip {entry['id']}: range-read only, never downloaded whole")
            continue
        dest = DATA / entry["dest"]
        pinned = lock.get(entry["id"])
        try:
            if dest.exists():
                digest = sha256_of(dest)
                if pinned and pinned["sha256"] != digest:
                    raise FetchError(f"{entry['id']}: local file does not match pinned sha256")
                if not pinned:
                    lock[entry["id"]] = {"sha256": digest, "size": dest.stat().st_size,
                                         "url": entry["url"], "pinned_utc": _now()}
                print(f"ok   {entry['id']} {digest[:12]}")
                continue
            if verify_only:
                print(f"miss {entry['id']}")
                failures += 1
                continue
            print(f"get  {entry['id']}")
            digest, last_mod = download(entry, dest)
            if pinned and pinned["sha256"] != digest:
                raise FetchError(f"{entry['id']}: downloaded bytes differ from pinned sha256 (upstream changed)")
            lock[entry["id"]] = {"sha256": digest, "size": dest.stat().st_size, "url": entry["url"],
                                 "last_modified": last_mod, "pinned_utc": pinned["pinned_utc"] if pinned else _now()}
            save_lock(lock)
            print(f"ok   {entry['id']} {digest[:12]}")
        except (FetchError, requests.RequestException) as exc:
            print(f"FAIL {exc}", file=sys.stderr)
            failures += 1
    save_lock(lock)
    return 1 if failures else 0


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", default="mvp")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    sys.exit(run(a.set, set(a.only) if a.only else None, a.verify))


if __name__ == "__main__":
    main()
