# nsp2nup

> **Personal project, not for actual usage.** This is a hobby tool I made for myself. It's public so
> [a55uka](https://github.com/a55uka/nup) (the nup author) can see it. Releases are test builds for debugging and
> trying it out, with no support, and it may change or disappear at any time.

Drag-and-drop converter from Nintendo Switch `.nsp` files to a single [`.nup`](https://github.com/a55uka/nup) container.
Base game, updates and DLC all go into one `.nup`. Works with Switch 1 and Switch 2 games
(tested on The Legend of Zelda: Link's Awakening and Donkey Kong Bananza).

## What it adds over `nup pack`

nup packs folders that are already decrypted, and its metadata (name, icon, version...) has to be
typed in by hand as options. nsp2nup works straight from the NSPs and fills the metadata in from the
game's Control NCA:

| | `nup pack` on its own | nsp2nup |
|---|---|---|
| Input | decrypted `exefs/` + `romfs/` folders | NSPs (or the same folders) |
| Base + updates + DLC | you arrange `base/`, `updates/`, `dlc/` yourself | detected from each NSP's metadata |
| Name (all languages), publisher | `--name`, `--lang-name`, `--publisher` | automatic |
| Display version | `--display-version` | automatic |
| Icons (all languages) | `--icon`, `--lang-icon` with image files you supply | automatic |
| NACP (full control data) | no option | stored automatically |

Already-extracted folders packed with nsp2nup get no metadata either, since it lives in the Control NCA
(see below).

## Setup (once)

1. **Python 3.10+** - install from python.org (tick "Add python.exe to PATH"),
   *or* unzip the "Windows embeddable package" into a folder named `python\` here for a fully portable copy.
2. **A decrypter** - the release zip includes **`hactool.exe`**: hactool 1.4.0 with a small fix
   (`hactool-1.4.0-nsp2nup.patch`) so `-x` only extracts and an NPDM it doesn't understand (e.g. Switch 2)
   is skipped instead of crashing it. ISC license in `hactool_LICENSE.txt`. You can also drop in **`hactoolnet.exe`**;
   if both are there, hactoolnet is used. Use whichever copy is newer -
   older versions may not understand games made for newer firmware.
   hactoolnet is not included (LibHac/hactoolnet was removed from GitHub by a DMCA takedown in May 2025).
3. **Keys** - your `prod.keys` dumped from your own console (Lockpick_RCM). You don't need to place it manually:
   drop it on `nsp2nup.bat` once (alone or together with an NSP) and it's saved to `keys\prod.keys`.

## Use

Select the NSPs (base + any updates + any DLC, in any order) and drag them onto `nsp2nup.bat`.
You can also drop a folder that contains them.

- Output is written next to the base game's NSP as `Game Name [TitleID].nup`.
- Several different games at once is fine - you get one `.nup` per game.
- Title keys are read from the tickets inside the NSPs. If a ticket is missing or console-bound,
  drop a `title.keys` too.
- An update or DLC needs its base game in the same drop (updates patch the base RomFS).
- If one update/DLC fails, the `.nup` is still made without it, with a warning at the end.
- Needs free disk space of roughly 2-3x the NSP size while it runs (temp folder is cleaned up after).

### Already-extracted games (no keys or decrypter needed)

If another tool (e.g. an emulator's "Extract Data") already gave you the game's files, arrange them as
`My Game\exefs\...` and `My Game\romfs\...` and drop the `My Game` folder onto `nsp2nup.bat`.
It's packed as-is into `My Game.nup`. A `base\` / `updates\<version>\` / `dlc\<titleid>\0\` layout works too.
If `base\` is empty because the dumper kept only the fully patched update, it's left out and the update
is packed on its own (marked standalone), carrying the whole game. An empty `base\exefs\` would otherwise
make emulators look for the game's code in the wrong place.
Name, icon and display version aren't available this way (they live in the Control NCA), so emulators
show the title ID instead.

Command line: `py nsp2nup.py [files/folders...] [-o OUTDIR] [--tool PATH] [--level N] [--keep-work]`

## Optional: single .exe

Run `build_exe.bat` once to get `nsp2nup.exe` (PyInstaller). Then Python isn't needed;
drag files onto the .exe the same way. It still needs `hactool.exe` (or `hactoolnet.exe`) and the keys beside it.

## Not supported

- `.nsz` / `.xci` - convert to plain `.nsp` first.
- DLC updates (NUP v1 reserves that package kind).
- Multi-program titles: only the main program is packed (NUP v1 allows one base).

## How it works

1. Reads the NSP (PFS0) and pulls the encrypted title keys out of its `.tik` tickets.
2. hactool/hactoolnet decrypts the metadata NCA; the CNMT says whether it's base/update/DLC and its version.
3. hactool/hactoolnet extracts ExeFS/RomFS into the layout nup expects
   (`base/`, `updates/<version>/`, `dlc/<titleid>/<index>/`); updates use `--basenca` so their RomFS is the full patched tree.
4. Name, publisher, display version, icons and the NACP come from the Control NCA.
5. nup's own reference packer writes the `.nup`.

## Credits

- KaboWabo/Kabosune (me :3)
- AI assistance (Claude Opus 5.5)
- [nup](https://github.com/a55uka/nup) format and packer by a55uka - vendored in `lib/nup` for the standalone zip (in the nup repo, `tools/nup` is used instead)
- [hactool](https://github.com/SciresM/hactool) by SciresM - included as `hactool.exe`, patched (`hactool-1.4.0-nsp2nup.patch`; ISC license, see `hactool_LICENSE.txt`)
- hactoolnet / LibHac by Alex Barney - optional alternative decrypter (not included)
- [zstandard](https://pypi.org/project/zstandard/) Python bindings - vendored in `lib/zstandard` (Windows builds for Python 3.10-3.14)
