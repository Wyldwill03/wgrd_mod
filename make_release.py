#!/usr/bin/env python3
"""
make_release.py  —  package a WGRD mod release for Wyldwill03/wgrd_mod
=====================================================================
Run AFTER apply_all_mods.py has produced NDF_Win_mod.dat / ZZ_Win_mod.dat.

It:
  * bundles the modded .dat files into  mod_files.zip
  * writes  manifest.json  (version, per-file target path + SHA-256, MP checksum)
  * (optional) uploads both as assets on a GitHub Release via the `gh` CLI

Usage
-----
  python make_release.py --version 1.0.0
  python make_release.py --version 1.0.1 --upload            # needs `gh auth login`
  python make_release.py --version 1.0.0 --notes "First public build"

Output goes to  installer/release/ .
"""

import os, sys, json, hashlib, zipfile, argparse, subprocess

HERE  = os.path.dirname(os.path.abspath(__file__))
ZDIR  = os.path.dirname(HERE)                          # ...\claude zone
OUT   = os.path.join(HERE, "release")
REPO  = "Wyldwill03/wgrd_mod"

# modded file  ->  path inside the game's ...\Data\WarGame\PC
FILES = [
    (os.path.join(ZDIR, "NDF_Win_mod.dat"), "131544/NDF_Win.dat"),
    (os.path.join(ZDIR, "ZZ_Win_mod.dat"),  "130278/131544/ZZ_Win.dat"),
]
ASSET = "mod_files.zip"


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="release version, e.g. 1.0.0")
    ap.add_argument("--notes", default="", help="release notes / changelog")
    ap.add_argument("--upload", action="store_true", help="create the GitHub release via gh")
    args = ap.parse_args()

    for src, _ in FILES:
        if not os.path.isfile(src):
            sys.exit(f"ERROR: missing {src} — run apply_all_mods.py first.")

    os.makedirs(OUT, exist_ok=True)

    # 1) bundle the modded .dat files (stored at their game basename)
    zip_path = os.path.join(OUT, ASSET)
    print(f"  bundling -> {ASSET}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for src, rel in FILES:
            z.write(src, os.path.basename(rel))

    # 2) checksums + MP checksum
    entries, hashes = [], []
    for src, rel in FILES:
        h = sha256(src)
        hashes.append(h)
        entries.append({"path": rel, "sha256": h, "asset": ASSET,
                        "size": os.path.getsize(src)})
        print(f"    {rel}  sha256={h[:16]}...  {os.path.getsize(src)/1e6:.1f} MB")
    mp_checksum = hashlib.sha256("".join(sorted(hashes)).encode()).hexdigest()[:16].upper()

    manifest = {
        "version": args.version,
        "repo": REPO,
        "files": entries,
        "mp_checksum": mp_checksum,
        "notes": args.notes,
    }
    man_path = os.path.join(OUT, "manifest.json")
    json.dump(manifest, open(man_path, "w", encoding="utf-8"), indent=2)
    print(f"  wrote manifest.json  (MP checksum {mp_checksum})")

    # 3) optional upload
    if args.upload:
        tag = "v" + args.version
        print(f"  creating GitHub release {tag} on {REPO} ...")
        cmd = ["gh", "release", "create", tag, zip_path, man_path,
               "-R", REPO, "-t", f"WGRD Mod {tag}", "-n", args.notes or f"WGRD Mod {tag}"]
        try:
            subprocess.run(cmd, check=True)
            print("  uploaded.")
        except FileNotFoundError:
            print("  !! `gh` CLI not found — install GitHub CLI or upload the two files in")
            print(f"     {OUT}  manually as assets on a release tagged {tag}.")
        except subprocess.CalledProcessError as e:
            print(f"  !! gh failed ({e}). Upload {ASSET} + manifest.json manually to release {tag}.")
    else:
        print(f"\n  Done. Upload these two files as assets on a GitHub release tagged v{args.version}:")
        print(f"     {zip_path}")
        print(f"     {man_path}")
        print("  (or re-run with --upload if you have the `gh` CLI authenticated.)")


if __name__ == "__main__":
    main()
