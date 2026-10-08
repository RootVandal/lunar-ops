"""Publish the repository to GitHub as ONE squashed public commit, uploaded in small pushes.

GitHub drops HTTPS pushes that take longer than ~30 s, and the uplink here is slow,
so the files are first sent in batches of < 0.9 MB on a temporary branch; the real
single commit then reuses those uploaded objects and is tiny. The full local history
is kept in the local branch `local-history`.

    python tools/publish.py                 # first publish (creates RootVandal/lunar-ops)
    python tools/publish.py --update        # later: push the current state as a new commit

Needs: git, GitHub CLI (`gh auth status` logged in).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

REPO = "RootVandal/lunar-ops"
DESC = ("Where and when can a CLPS lander work at the lunar south pole? Requirements in, feasible sites and dates out "
        "- NASA LOLA terrain, NAIF SPICE, validated against JPL Horizons and NASA GSFC.")
BATCH = 900_000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*args, check=True, quiet=False):
    if not quiet:
        print("$", " ".join(args), flush=True)
    r = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if check and r.returncode != 0:
        sys.exit(f"failed: {' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def push(ref_spec, tries=4):
    for k in range(tries):
        r = subprocess.run(["git", "push", "-f", "origin", ref_spec], cwd=ROOT, text=True, capture_output=True)
        if r.returncode == 0:
            return
        print(f"  push failed ({k + 1}/{tries}), retrying: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''}", flush=True)
    sys.exit("push kept failing; rerun the script (already uploaded batches are kept)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="push the current main as a new public commit")
    a = ap.parse_args()
    if run("git", "status", "--porcelain", quiet=True):
        sys.exit("commit or stash your changes first")
    files = run("git", "ls-files", quiet=True).splitlines()
    sizes = {f: os.path.getsize(os.path.join(ROOT, f)) for f in files}
    too_big = [f for f, s in sizes.items() if s > BATCH]
    if too_big:
        sys.exit(f"files larger than {BATCH} bytes cannot be pushed on this link: {too_big}")

    if not a.update:
        if subprocess.run(["gh", "repo", "view", REPO], cwd=ROOT, capture_output=True).returncode != 0:
            run("gh", "repo", "create", REPO, "--public", "--description", DESC)
        remotes = run("git", "remote", quiet=True).split()
        if "origin" not in remotes:
            run("git", "remote", "add", "origin", f"https://github.com/{REPO}.git")
    run("git", "branch", "-f", "local-history", "main")
    tree = run("git", "rev-parse", "main^{tree}", quiet=True)

    # 1) upload blobs in small batches on a temporary branch
    batches, cur, size = [], [], 0
    for f in sorted(files, key=lambda f: sizes[f]):
        if cur and size + sizes[f] > BATCH:
            batches.append(cur); cur, size = [], 0
        cur.append(f); size += sizes[f]
    if cur:
        batches.append(cur)
    index = os.path.join(ROOT, ".git", "publish-index")
    env = dict(os.environ, GIT_INDEX_FILE=index)
    parent = None
    done = []
    for i, b in enumerate(batches, 1):
        done += b
        subprocess.run(["git", "read-tree", "--empty"], cwd=ROOT, env=env, check=True)
        subprocess.run(["git", "update-index", "--add", "--"] + done, cwd=ROOT, env=env, check=True)
        t = subprocess.run(["git", "write-tree"], cwd=ROOT, env=env, text=True, capture_output=True, check=True).stdout.strip()
        cmd = ["git", "commit-tree", t, "-m", f"upload batch {i}"] + (["-p", parent] if parent else [])
        parent = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
        print(f"batch {i}/{len(batches)}: {len(b)} files, {sum(sizes[f] for f in b) / 1e3:.0f} kB", flush=True)
        push(f"{parent}:refs/heads/upload-tmp")
    os.remove(index)

    # 2) the real public commit: one squashed commit with main's tree
    msg = ("LUNAR//OPS: CLPS south-pole mission window finder (independent open-source tool, October 2026)\n\n"
           "Full development history is kept locally; this public history is squashed.")
    if a.update:
        prev = run("git", "ls-remote", "origin", "refs/heads/main", quiet=True).split()
        pub = run("git", "commit-tree", tree, "-p", prev[0], "-m", "Update", quiet=True) if prev else \
            run("git", "commit-tree", tree, "-m", msg, quiet=True)
    else:
        pub = run("git", "commit-tree", tree, "-m", msg, quiet=True)
    push(f"{pub}:refs/heads/main")
    # the first branch pushed to a new repository becomes its default: make sure that is main
    run("gh", "repo", "edit", REPO, "--default-branch", "main", check=False)
    run("git", "push", "origin", "--delete", "upload-tmp", check=False)

    # 3) GitHub Pages from the workflow in .github/workflows/pages.yml
    if not a.update:
        run("gh", "api", "-X", "POST", f"repos/{REPO}/pages", "-f", "build_type=workflow", check=False)
    print(f"\npublished: https://github.com/{REPO}\nsite (after the Pages action finishes, ~1 min): https://rootvandal.github.io/lunar-ops/")


if __name__ == "__main__":
    main()
