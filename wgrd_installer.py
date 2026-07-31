#!/usr/bin/env python3
"""
WGRD Mod Installer  —  Wyldwill03/wgrd_mod
============================================
One-file, stdlib-only installer for the Wargame: Red Dragon gameplay mod.

What it does
------------
  * Auto-detects the WGRD install via Steam (app 251060).
  * Backs up the modified .dat files + your Steam profile REGARDLESS of their
    current state (vanilla, or already touched by a cosmetic/skin mod), into
    <game>\\Data\\WarGame\\PC\\_WGRDMOD_BACKUP\\ — so a revert is always exact.
  * Installs by dropping in the full modded .dat files (fetched from the repo's
    latest GitHub Release), verified by SHA-256.
  * Shows an "MP checksum" so you and your friends can confirm you're on the same
    build (WGRD's own sync check enforces this in-game; this is the pre-flight).
  * Reverts to the backed-up originals on demand.
  * Notifies when a newer release exists and can one-click update.

No third-party packages: tkinter, urllib, hashlib, zipfile, winreg, ctypes only,
so `pyinstaller --onefile --noconsole` yields a clean single .exe.
"""

import os, sys, json, hashlib, shutil, tempfile, threading, time, traceback
import urllib.request, urllib.error, zipfile, datetime

# ------------------------------------------------------------------ config ----
REPO_OWNER   = "Wyldwill03"
REPO_NAME    = "wgrd_mod"
STEAM_APPID  = "251060"                       # Wargame: Red Dragon
GAME_SUBPATH = os.path.join("steamapps", "common", "Wargame Red Dragon", "Data", "WarGame", "PC")
BACKUP_DIR   = "_WGRDMOD_BACKUP"              # created under ...\PC\
STATE_FILE   = "state.json"                   # inside the backup dir
APP_TITLE    = "WGRD Mod Installer"
USER_AGENT   = "WGRD-ModInstaller"
IS_WIN       = os.name == "nt"

# ------------------------------------------------------------- small helpers --
def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()

def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024

def _ver_tuple(v):
    out = []
    for p in str(v).lstrip("vV").replace("-", ".").split("."):
        out.append(int(p) if p.isdigit() else 0)
    return tuple(out)

def newer(remote, local):
    """True if remote version string is newer than local (local may be None)."""
    if not local:
        return True
    return _ver_tuple(remote) > _ver_tuple(local)

# --------------------------------------------------------- steam / game find --
def _steam_path():
    if not IS_WIN:
        return None
    try:
        import winreg
        for root, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(root, key) as k:
                    val = winreg.QueryValueEx(k, "SteamPath" if root == winreg.HKEY_CURRENT_USER else "InstallPath")[0]
                    if val and os.path.isdir(val):
                        return os.path.normpath(val)
            except OSError:
                continue
    except Exception:
        pass
    # common fallbacks
    for p in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if os.path.isdir(p):
            return p
    return None

def _steam_libraries(steam):
    """All Steam library roots (main + libraryfolders.vdf entries)."""
    libs = [steam]
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    try:
        import re
        txt = open(vdf, "r", encoding="utf-8", errors="ignore").read()
        for m in re.finditer(r'"path"\s*"([^"]+)"', txt):
            libs.append(m.group(1).replace("\\\\", "\\"))
    except Exception:
        pass
    seen, out = set(), []
    for l in libs:
        n = os.path.normpath(l)
        if n.lower() not in seen and os.path.isdir(n):
            seen.add(n.lower()); out.append(n)
    return out

def find_game():
    """Return the ...\\Data\\WarGame\\PC path, or None."""
    steam = _steam_path()
    if steam:
        for lib in _steam_libraries(steam):
            pc = os.path.join(lib, GAME_SUBPATH)
            if os.path.isdir(pc):
                return pc
    return None

def find_profiles():
    """List of {id, path} for each userdata\\<id>\\251060\\remote that exists."""
    steam = _steam_path()
    out = []
    if not steam:
        return out
    ud = os.path.join(steam, "userdata")
    if not os.path.isdir(ud):
        return out
    for uid in os.listdir(ud):
        remote = os.path.join(ud, uid, STEAM_APPID, "remote")
        if os.path.isdir(remote) and os.listdir(remote):
            out.append({"id": uid, "path": remote})
    return out

# --------------------------------------------------------------- github i/o ---
def _http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def latest_release():
    """Return {version, manifest_url, assets:{name:url}} or None if none/unreachable."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
    try:
        data = _http_json(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None            # no releases published yet
        raise
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    return {"version": data.get("tag_name", "").lstrip("vV"),
            "assets": assets,
            "notes": data.get("body", "")}

def download(url, dest, progress=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with open(dest, "wb") as f:
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                f.write(b); done += len(b)
                if progress:
                    progress(done, total)

# ----------------------------------------------------------------- state -----
def backup_root(game):     return os.path.join(game, BACKUP_DIR)
def state_path(game):      return os.path.join(backup_root(game), STATE_FILE)

def load_state(game):
    try:
        return json.load(open(state_path(game), "r", encoding="utf-8"))
    except Exception:
        return None

def save_state(game, st):
    os.makedirs(backup_root(game), exist_ok=True)
    json.dump(st, open(state_path(game), "w", encoding="utf-8"), indent=2)

# --------------------------------------------------- core operations ---------
class InstallError(Exception):
    pass

def _atomic_replace(src, dst):
    """Write src into dst atomically on the same volume."""
    tmp = dst + ".tmpinstall"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)

def do_install(game, manifest, staged, profiles_to_backup, log, progress=None):
    """
    manifest : dict from the release (see make_release.py)
    staged   : {rel_path: local_file}  (already downloaded + checksum-verified)
    profiles_to_backup : list of {id, path}
    """
    st = load_state(game) or {}
    st.setdefault("backups", {})
    st.setdefault("profile_backups", [])
    os.makedirs(backup_root(game), exist_ok=True)
    first_install = "installed_version" not in st

    for fe in manifest["files"]:
        rel = fe["path"]
        target = os.path.join(game, *rel.split("/"))
        if not os.path.isfile(target):
            raise InstallError(f"Expected game file missing: {rel}")
        # back up the CURRENT file the very first time we ever touch it (preserves
        # the user's true original — vanilla OR cosmetic-modded — forever).
        if rel not in st["backups"]:
            bname = os.path.basename(target) + ".orig"
            bpath = os.path.join(backup_root(game), bname)
            if not os.path.exists(bpath):
                log(f"  backing up original {rel}")
                shutil.copyfile(target, bpath)
            st["backups"][rel] = {"backup": bname, "orig_sha256": sha256(bpath)}
        # drop in the modded file
        log(f"  installing {rel}")
        _atomic_replace(staged[rel], target)
        got = sha256(target)
        if got != fe["sha256"]:
            raise InstallError(f"Checksum mismatch after install for {rel}\n  expected {fe['sha256']}\n  got      {got}")

    # profile backup — only on first install, per the user's choice
    if first_install and profiles_to_backup:
        for p in profiles_to_backup:
            zpath = os.path.join(backup_root(game), f"profile_{p['id']}.zip")
            if not os.path.exists(zpath):
                log(f"  backing up profile {p['id']}")
                with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
                    for rootd, _, files in os.walk(p["path"]):
                        for fn in files:
                            full = os.path.join(rootd, fn)
                            z.write(full, os.path.relpath(full, p["path"]))
            st["profile_backups"].append({"id": p["id"], "path": p["path"], "zip": os.path.basename(zpath)})

    st["installed_version"] = manifest["version"]
    st["installed_mp_checksum"] = manifest.get("mp_checksum", "")
    st["install_date"] = datetime.datetime.now().isoformat(timespec="seconds")
    save_state(game, st)
    return st

def do_revert(game, restore_profiles, log):
    st = load_state(game)
    if not st or not st.get("backups"):
        raise InstallError("No backup found — nothing to revert.")
    for rel, info in st["backups"].items():
        bpath = os.path.join(backup_root(game), info["backup"])
        target = os.path.join(game, *rel.split("/"))
        if not os.path.isfile(bpath):
            log(f"  !! backup missing for {rel}, skipping")
            continue
        log(f"  restoring {rel}")
        _atomic_replace(bpath, target)
    if restore_profiles:
        for pb in st.get("profile_backups", []):
            zpath = os.path.join(backup_root(game), pb["zip"])
            if os.path.isfile(zpath) and os.path.isdir(pb["path"]):
                log(f"  restoring profile {pb['id']}")
                with zipfile.ZipFile(zpath) as z:
                    z.extractall(pb["path"])
    # clear installed markers but KEEP the original backups on disk (safety)
    st.pop("installed_version", None)
    st.pop("installed_mp_checksum", None)
    st["reverted_date"] = datetime.datetime.now().isoformat(timespec="seconds")
    save_state(game, st)
    log("Reverted to your backed-up originals.")

def verify_install(game, manifest, log):
    """Check the live files against the manifest's modded checksums."""
    ok = True
    for fe in manifest["files"]:
        target = os.path.join(game, *fe["path"].split("/"))
        if not os.path.isfile(target):
            log(f"  MISSING {fe['path']}"); ok = False; continue
        got = sha256(target)
        good = got == fe["sha256"]
        log(f"  {'OK  ' if good else 'DIFF'} {fe['path']}")
        ok = ok and good
    return ok

# ============================================================ GUI ============
def run_gui():
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("640x520")
    root.minsize(560, 460)

    state = {"game": find_game(), "manifest": None, "release": None, "busy": False}

    # ---- widgets ----
    top = ttk.Frame(root, padding=10); top.pack(fill="x")
    ttk.Label(top, text=APP_TITLE, font=("Segoe UI", 14, "bold")).pack(anchor="w")
    ttk.Label(top, text=f"{REPO_OWNER}/{REPO_NAME}", foreground="#666").pack(anchor="w")

    info = ttk.Frame(root, padding=(10, 0)); info.pack(fill="x")
    game_var = tk.StringVar(value=state["game"] or "Game not found — click Browse")
    inst_var = tk.StringVar(value="")
    latest_var = tk.StringVar(value="")
    row = ttk.Frame(info); row.pack(fill="x", pady=2)
    ttk.Label(row, text="Game:", width=8).pack(side="left")
    ttk.Label(row, textvariable=game_var, foreground="#036").pack(side="left", fill="x", expand=True)
    ttk.Button(row, text="Browse", width=8, command=lambda: browse()).pack(side="right")
    ttk.Label(info, textvariable=inst_var).pack(anchor="w")
    ttk.Label(info, textvariable=latest_var).pack(anchor="w")

    csum_var = tk.StringVar(value="")
    ttk.Label(info, textvariable=csum_var, font=("Consolas", 10, "bold"), foreground="#060").pack(anchor="w", pady=2)

    btns = ttk.Frame(root, padding=10); btns.pack(fill="x")
    b_install = ttk.Button(btns, text="Install / Update", command=lambda: threaded(install_flow))
    b_revert  = ttk.Button(btns, text="Revert to backup", command=lambda: threaded(revert_flow))
    b_verify  = ttk.Button(btns, text="Verify", command=lambda: threaded(verify_flow))
    b_check   = ttk.Button(btns, text="Check for updates", command=lambda: threaded(refresh_release))
    for b in (b_install, b_revert, b_verify, b_check):
        b.pack(side="left", padx=4)

    pb = ttk.Progressbar(root, mode="determinate"); pb.pack(fill="x", padx=10, pady=(0, 4))
    logbox = tk.Text(root, height=14, wrap="word", state="disabled", font=("Consolas", 9))
    logbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # ---- helpers ----
    def log(msg=""):
        logbox.configure(state="normal"); logbox.insert("end", msg + "\n")
        logbox.see("end"); logbox.configure(state="disabled"); root.update_idletasks()

    def set_progress(done, total):
        pb.configure(maximum=max(total, 1), value=done); root.update_idletasks()

    def set_busy(b):
        state["busy"] = b
        for w in (b_install, b_revert, b_verify, b_check):
            w.configure(state="disabled" if b else "normal")

    def threaded(fn):
        if state["busy"]:
            return
        set_busy(True)
        def worker():
            try:
                fn()
            except Exception as e:
                log("ERROR: " + str(e)); log(traceback.format_exc())
                messagebox.showerror(APP_TITLE, str(e))
            finally:
                set_busy(False); set_progress(0, 1)
        threading.Thread(target=worker, daemon=True).start()

    def browse():
        d = filedialog.askdirectory(title="Select ...\\Data\\WarGame\\PC")
        if d and os.path.isfile(os.path.join(d, "131544", "NDF_Win.dat")):
            state["game"] = d; game_var.set(d); refresh_installed()
        elif d:
            messagebox.showwarning(APP_TITLE, "That folder doesn't look like the WGRD PC data folder\n(no 131544\\NDF_Win.dat).")

    def refresh_installed():
        if not state["game"]:
            return
        st = load_state(state["game"])
        if st and st.get("installed_version"):
            inst_var.set(f"Installed: v{st['installed_version']}  ({st.get('install_date','')})")
            if st.get("installed_mp_checksum"):
                csum_var.set("MP checksum: " + st["installed_mp_checksum"])
        else:
            inst_var.set("Installed: (none)")

    def refresh_release():
        log("Checking GitHub for the latest release...")
        rel = latest_release()
        state["release"] = rel
        if rel is None:
            latest_var.set("Latest: (no release published yet)")
            log("No release found on the repo yet.")
            return
        latest_var.set(f"Latest: v{rel['version']}")
        st = load_state(state["game"]) if state["game"] else None
        cur = st.get("installed_version") if st else None
        if newer(rel["version"], cur):
            log(f"Update available: v{rel['version']}" + (f" (you have v{cur})" if cur else ""))
        else:
            log("You are up to date.")

    def fetch_manifest_and_files():
        """Download manifest + mod files from the latest release into a temp dir."""
        rel = state["release"] or latest_release(); state["release"] = rel
        if rel is None:
            raise InstallError("No release is published on the repo yet.")
        if "manifest.json" not in rel["assets"]:
            raise InstallError("Release has no manifest.json asset.")
        tmp = tempfile.mkdtemp(prefix="wgrdmod_")
        log("Downloading manifest...")
        mpath = os.path.join(tmp, "manifest.json")
        download(rel["assets"]["manifest.json"], mpath)
        manifest = json.load(open(mpath, "r", encoding="utf-8"))
        state["manifest"] = manifest
        # download each asset bundle referenced by the manifest
        staged = {}
        for asset_name in {fe["asset"] for fe in manifest["files"]}:
            if asset_name not in rel["assets"]:
                raise InstallError(f"Release missing asset: {asset_name}")
            log(f"Downloading {asset_name} ...")
            apath = os.path.join(tmp, asset_name)
            download(rel["assets"][asset_name], apath, set_progress)
            # each asset is a zip containing the modded .dat(s) at their basename
            with zipfile.ZipFile(apath) as z:
                z.extractall(tmp)
        # map each manifest file to its extracted local path + verify checksum
        for fe in manifest["files"]:
            local = os.path.join(tmp, os.path.basename(fe["path"]))
            if not os.path.isfile(local):
                raise InstallError(f"Asset zip did not contain {os.path.basename(fe['path'])}")
            got = sha256(local)
            if got != fe["sha256"]:
                raise InstallError(f"Downloaded {fe['path']} failed checksum — aborting.")
            staged[fe["path"]] = local
        return manifest, staged, tmp

    def choose_profiles():
        profs = find_profiles()
        if not profs:
            return []
        if len(profs) == 1:
            return profs
        # multiple Steam accounts -> ask
        import tkinter.simpledialog as sd
        ids = ", ".join(p["id"] for p in profs)
        ans = messagebox.askyesnocancel(
            APP_TITLE,
            f"Multiple Steam profiles found:\n  {ids}\n\n"
            "Back up ALL of them?\n\n"
            "Yes = all,  No = pick one,  Cancel = skip profile backup")
        if ans is None:
            return []
        if ans:
            return profs
        pick = sd.askstring(APP_TITLE, f"Enter the profile id to back up:\n{ids}")
        return [p for p in profs if p["id"] == pick]

    def install_flow():
        if not state["game"]:
            raise InstallError("Game folder not set — click Browse.")
        manifest, staged, tmp = fetch_manifest_and_files()
        first = load_state(state["game"]) is None or "installed_version" not in (load_state(state["game"]) or {})
        profs = choose_profiles() if first else []
        log(f"Installing v{manifest['version']} ...")
        st = do_install(state["game"], manifest, staged, profs, log, set_progress)
        shutil.rmtree(tmp, ignore_errors=True)
        csum_var.set("MP checksum: " + st.get("installed_mp_checksum", ""))
        refresh_installed()
        log("Done. Share your MP checksum with anyone you want to play with.")
        messagebox.showinfo(APP_TITLE, f"Installed v{manifest['version']}.\n\nMP checksum:\n{st.get('installed_mp_checksum','')}")

    def revert_flow():
        if not state["game"]:
            raise InstallError("Game folder not set.")
        st = load_state(state["game"])
        has_prof = st and st.get("profile_backups")
        restore_p = False
        if has_prof:
            restore_p = messagebox.askyesno(
                APP_TITLE,
                "Also restore your backed-up Steam profile?\n\n"
                "(Your current decks may reference mod units that won't load on vanilla.\n"
                "Yes = restore your pre-mod decks, No = keep current decks.)")
        log("Reverting...")
        do_revert(state["game"], restore_p, log)
        refresh_installed(); csum_var.set("")
        messagebox.showinfo(APP_TITLE, "Reverted to your backed-up originals.")

    def verify_flow():
        if not state["game"]:
            raise InstallError("Game folder not set.")
        rel = state["release"] or latest_release(); state["release"] = rel
        if not state["manifest"]:
            if rel and "manifest.json" in rel.get("assets", {}):
                tmp = tempfile.mkdtemp(prefix="wgrdmod_")
                mpath = os.path.join(tmp, "manifest.json")
                download(rel["assets"]["manifest.json"], mpath)
                state["manifest"] = json.load(open(mpath, "r", encoding="utf-8"))
            else:
                raise InstallError("No manifest available to verify against.")
        log(f"Verifying against v{state['manifest']['version']} ...")
        ok = verify_install(state["game"], state["manifest"], log)
        log("Installation matches the release." if ok else "Some files DIFFER from the release.")

    # ---- startup ----
    refresh_installed()
    threaded(refresh_release)
    root.mainloop()

# ============================================================ main ==========
def _selftest():
    """Read-only checks you can run on your own machine (no writes, no elevation)."""
    print("game:", find_game())
    print("profiles:", find_profiles())
    g = find_game()
    if g:
        for rel in ("131544/NDF_Win.dat", "130278/131544/ZZ_Win.dat"):
            p = os.path.join(g, *rel.split("/"))
            print(f"  {rel}: {'exists ' + human(os.path.getsize(p)) + ' sha=' + sha256(p)[:12] if os.path.isfile(p) else 'MISSING'}")
    try:
        print("latest release:", latest_release())
    except Exception as e:
        print("release check error:", e)

def _is_admin():
    if not IS_WIN:
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def _elevate():
    import ctypes
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)

def main():
    if "--selftest" in sys.argv:
        _selftest(); return
    if IS_WIN and not _is_admin():
        # relaunch elevated so we can write into Program Files
        try:
            _elevate(); return
        except Exception:
            pass  # fall through; the write will just fail with a clear error
    run_gui()

if __name__ == "__main__":
    main()
