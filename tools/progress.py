"""Live progress of the NASA DEM-clone ensembles (reads the logs of `python -m lunarops.clones`).

    python tools/progress.py LOG [LOG ...]

Shows, per site: files downloaded (only the rows the 0-5 km skyline needs), members
computed (nominal-2021 + clones) and the downloaded volume. Ctrl+C to quit.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

ORDER = ["connecting-ridge-roi4", "nobile-rim-1", "malapert", "nobile-rim-2", "haworth"]
NAME = {"connecting-ridge-roi4": "Connecting Ridge", "nobile-rim-1": "Nobile Rim 1", "malapert": "Malapert",
        "nobile-rim-2": "Nobile Rim 2", "haworth": "Haworth"}
MB_PER_FILE = {"connecting-ridge-roi4": 27.2, "malapert": 35.6, "nobile-rim-1": 34.0, "nobile-rim-2": 34.0, "haworth": 45.4}
CACHE = Path(__file__).resolve().parents[1] / "data" / "raw" / "tiles"
Y, B, G, R, D, X = "\033[93m", "\033[94m", "\033[92m", "\033[91m", "\033[2m", "\033[0m"


def bar(k, n, w=28):
    k = min(k, n)
    f = int(round(w * k / n)) if n else 0
    return f"{Y}{'█' * f}{D}{'░' * (w - f)}{X} {k:>2}/{n:<2}"


def parse(text):
    st, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"(\S+): (\d+) clones \((\d+) on disk", line)
        if m:
            cur = m.group(1); st[cur] = {"n": int(m.group(2)), "disk": int(m.group(3)), "dl": 0, "dl_n": None, "comp": 0, "done": False, "t": None}
            continue
        if cur is None:
            continue
        m = re.match(r"\s+\[(\d+)/(\d+)\] (ok|FAILED)", line)
        if m:
            st[cur]["dl"] = int(m.group(1)); st[cur]["dl_n"] = int(m.group(2))
            st[cur]["t"] = re.search(r"\(([\d.]+) min\)", line).group(1) if "min)" in line else None
            if m.group(3) == "FAILED":
                st[cur]["failed"] = True
        elif line.startswith(("nominal-2021", "clone-")):
            st[cur]["comp"] += 1
        elif line.startswith("wrote") and f"clones_{cur}.json" in line:
            st[cur]["done"] = True
        elif "Traceback" in line:
            st[cur]["error"] = True
    return st


def cache_mb():
    try:
        return sum(p.stat().st_size for p in CACHE.rglob("*") if p.is_file()) / 1e6
    except OSError:
        return 0.0


def main(logs):
    t0, mb0 = time.time(), cache_mb()
    while True:
        text = "\n".join(Path(p).read_text(errors="replace") for p in logs if os.path.exists(p))
        st = parse(text)
        mb = cache_mb()
        rate = (mb - mb0) / max(time.time() - t0, 1) * 1000
        out = [f"{B}LUNAR//OPS · NASA DEM error clones (PGDA product 78){X}   {time.strftime('%H:%M:%S')}",
               f"{D}downloaded this session: {mb - mb0:7.1f} MB · average {rate:5.0f} KB/s · tile cache {mb / 1000:.2f} GB{X}", ""]
        for sid in ORDER:
            s = st.get(sid)
            if s is None:
                out.append(f"  {NAME[sid]:17s} {D}waiting in queue{X}")
                continue
            n_dl = s["dl_n"] if s["dl_n"] is not None else s["n"] + 1 - s["disk"]
            members = s["n"] + 1
            state = f"{G}DONE ✓{X}" if s["done"] else (f"{R}ERROR{X}" if s.get("error") else
                    ("computing" if s["dl"] >= n_dl else "downloading"))
            out.append(f"  {NAME[sid]:17s} download {bar(s['dl'], n_dl)}  compute {bar(s['comp'], members, 14)}  {state}")
            if not s["done"] and s["dl"] < n_dl:
                left = (n_dl - s["dl"]) * MB_PER_FILE[sid]
                out.append(f"  {'':17s} {D}≈ {left:.0f} MB left for this site; files finish in parallel, 8 at a time{X}")
        out.append("")
        out.append(f"{D}Ctrl+C to close this panel (the download keeps running).{X}")
        sys.stdout.write("\033[2J\033[H" + "\n".join(out) + "\n")
        sys.stdout.flush()
        if all(st.get(s, {}).get("done") for s in ORDER):
            print(f"{G}All five sites processed.{X}")
            return
        time.sleep(2)


if __name__ == "__main__":
    if os.name == "nt":
        os.system("")          # enable ANSI colours in the Windows console
    try:
        sys.stdout.reconfigure(encoding="utf-8")      # bars use block characters
    except (AttributeError, ValueError):
        pass
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        pass
