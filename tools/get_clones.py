"""Download NASA GSFC DEM error clones (PGDA product 78, Barker et al. 2021) for offline use.

Each clone is a full 5 m DEM = published surface + one Monte Carlo realization of
its error. The PGDA server limits the speed of a single connection, so several
files are fetched in parallel (--jobs). Files mirror the server layout under
<dest>/LOLA_5mpp/<Site>/Clones/; lunarops.dem finds them in data/raw/pgda or in
any folder listed in data/mirror_roots.txt (written here when --dest is used).

    python tools/get_clones.py Site01 Site23 --count 30 --jobs 6 --dest E:/lunarops-pgda

Resumable: rerun the same command after a dropped connection. A file counts as done
only when its size equals the server's Content-Length.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE = "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp"
REPO = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO / "data" / "raw" / "pgda"
CONFIG = REPO / "data" / "mirror_roots.txt"
SITES = {"Site01": "Connecting Ridge", "Site23": "Malapert", "Site06": "Nobile Rim 1",
         "DM2": "Nobile Rim 2", "Haworth": "Haworth"}
_print = threading.Lock()


def say(msg):
    with _print:
        print(msg, flush=True)


def fetch(url: str, out: Path, tries: int = 5) -> str:
    for attempt in range(1, tries + 1):
        try:
            size = int(requests.head(url, timeout=60).headers["Content-Length"])
            if out.exists() and out.stat().st_size == size:
                return f"ok    {out.name} (already complete)"
            part = out.with_suffix(out.suffix + ".part")
            done = part.stat().st_size if part.exists() else 0
            out.parent.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            with requests.get(url, headers={"Range": f"bytes={done}-"}, stream=True, timeout=180) as r:
                r.raise_for_status()
                if r.status_code != 206:
                    done = 0                                   # server sent the whole file
                start = done
                with part.open("ab" if done else "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
                        done += len(chunk)
            if part.stat().st_size != size:
                raise IOError(f"incomplete {part.stat().st_size}/{size}")
            part.replace(out)
            rate = (done - start) / max(time.time() - t0, 1e-3) / 1e3
            return f"done  {out.name}  {size / 1e6:.1f} MB at {rate:.0f} KB/s"
        except (requests.RequestException, IOError) as e:
            say(f"retry {out.name} ({attempt}/{tries}): {e}")
            time.sleep(5 * attempt)
    return f"FAIL  {out.name} — rerun the command to resume"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sites", nargs="+", choices=sorted(SITES))
    ap.add_argument("--count", type=int, default=30, help="clones per site, 1-100 (default 30)")
    ap.add_argument("--jobs", type=int, default=6, help="parallel downloads (default 6)")
    ap.add_argument("--dest", type=Path, default=DEFAULT_ROOT, help="mirror root, e.g. E:/lunarops-pgda")
    ap.add_argument("--surface", action="store_true", help="also download the nominal 5 m surface DEM")
    a = ap.parse_args()
    root = a.dest.resolve()
    if root != DEFAULT_ROOT.resolve():
        roots = CONFIG.read_text().splitlines() if CONFIG.exists() else []
        if str(root) not in roots:
            CONFIG.write_text("\n".join(roots + [str(root)]) + "\n")
        say(f"mirror root registered in {CONFIG.relative_to(REPO)}: {root}")
    root.mkdir(parents=True, exist_ok=True)
    jobs = []
    for s in a.sites:
        need = a.count * {"Site01": 41, "Site23": 71, "Site06": 64, "DM2": 64, "Haworth": 142}[s]
        say(f"{s} ({SITES[s]}): up to {need / 1000:.1f} GB · free on {root.anchor or root}: {shutil.disk_usage(root).free / 1e9:.1f} GB")
        if a.surface:
            name = f"{s}_final_adj_5mpp_surf.tif"
            jobs.append((f"{BASE}/{s}/{name}", root / "LOLA_5mpp" / s / name))
        for i in range(1, a.count + 1):
            name = f"{s}_final_adj_5mpp_{i:04d}_err.tif"
            jobs.append((f"{BASE}/{s}/Clones/{name}", root / "LOLA_5mpp" / s / "Clones" / name))
    fails = 0
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        for f in as_completed([ex.submit(fetch, u, o) for u, o in jobs]):
            msg = f.result()
            fails += msg.startswith("FAIL")
            say(msg)
    say("all files complete" if not fails else f"{fails} file(s) incomplete — rerun to resume")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
