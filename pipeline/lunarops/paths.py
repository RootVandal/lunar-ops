"""Repository paths. Data never lives in git; see data/manifest.yaml."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
KERNELS = RAW / "kernels"
DERIVED = DATA / "derived"
WEB_DATA = ROOT / "web" / "data"
