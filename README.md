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


