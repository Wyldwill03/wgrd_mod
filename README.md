# WGRD Mod Installer

A one-file installer for the Wargame: Red Dragon mod (`Wyldwill03/wgrd_mod`). It
backs up the player's original files, drops in the mod, shows an MP checksum so
friends can confirm they match, and can revert or self-update from GitHub.

---

## For players

1. Download **`WGRD-ModInstaller.exe`** from the repo's
   [latest release](https://github.com/Wyldwill03/wgrd_mod/releases/latest).
2. Run it (it asks for admin — the game lives in Program Files). It auto-finds
   your Steam copy of WGRD.
3. **Install / Update** — backs up your originals, installs the mod, and shows an
   **MP checksum**. Everyone in a lobby needs the same checksum (WGRD's own sync
   check enforces this in-game).
4. **Revert to backup** — puts your game back exactly how it was, including your
   Steam profile if you choose.
5. The installer tells you when a newer version is out and can update in one click.

Your originals live in `…\Wargame Red Dragon\Data\WarGame\PC\_WGRDMOD_BACKUP\` —
don't delete that folder if you want to be able to revert.

**Cosmetic/skin mods:** those live in the texture packages, which this mod does
*not* touch, so they keep working. Your files are backed up regardless of their
state, so a revert is always exact.

---

## For the modder (release workflow)

Everything is stdlib-only Python; no packages to install to *run* the scripts.

### 1. Build the mod
```
python apply_all_mods.py          # produces NDF_Win_mod.dat + ZZ_Win_mod.dat
```

### 2. Package a release
```
cd installer
python make_release.py --version 1.0.0 --notes "First public build"
```
This writes `installer/release/mod_files.zip` + `manifest.json` and prints the
**MP checksum**. Add `--upload` (needs the [`gh` CLI](https://cli.github.com/)
authenticated) to create the GitHub release automatically, or upload those two
files by hand as assets on a release tagged `v1.0.0`.

> The installer finds releases by the tag (`v1.0.0`) and reads `manifest.json`
> for the file paths + checksums, so **always bump `--version` and tag to match.**

### 3. Build the installer .exe (once, or when the installer code changes)
```
pip install pyinstaller
pyinstaller --onefile --noconsole --uac-admin --name WGRD-ModInstaller installer/wgrd_installer.py
```
Ship `dist/WGRD-ModInstaller.exe`. `--uac-admin` makes it request admin on launch
(there's also a self-elevation fallback in the code).

---

## How it works

* **Distribution** = full compressed `.dat` files (gameplay data is only ~44 MB,
  ~22 MB zipped — far smaller than shipping texture layers). `xdelta` binary
  patches are the plan for the several-GB texture layers if those are ever added;
  the installer is structured so that's a drop-in later.
* **Backups** are taken the first time a file is ever touched and never
  overwritten, so they always hold the true original.
* **Updates** just overwrite with the new full file — the backup keeps pointing
  at the original, so install / update / revert never drift.
* **Nothing executable is downloaded** — only data (`.zip` + `manifest.json`),
  each verified by SHA-256 before it's applied.

## Repo layout
```
apply_all_mods.py            # the mod build script (produces the modded .dat files)
installer/
  wgrd_installer.py          # the installer (ship this as a .exe)
  make_release.py            # packages a release
  README.md
  build_installer.bat        # convenience PyInstaller build
  release/                   # build output (gitignored; goes to GitHub Releases)
```
