# nsp2nup repo notes

Handoff notes for the nsp2nup repo. Written so a future session (or you) can pick it up cold.

## Where the project stands

- **Works:** Switch 1 NSPs -> `.nup` (base + updates + DLC, name/icon/NACP). Tested for real on Link's Awakening with hactool 1.4.0.
- **Works:** already-extracted game folders (`exefs\` + `romfs\`) -> `.nup`, no keys or decrypter needed. An empty `base\` (dumps that keep only the fully patched update) is left out and the update is packed standalone.
- **Works:** repair mode. Dropping a `.nup` with an empty base package rebuilds it as `Name (fixed).nup` (streamed extract with checksum checks, then repack), keeping metadata. Tested for real: the rebuilt Pokémon Pokopia v655360 boots in Eglantine.
- **Works:** Switch 2 NSPs, tested for real on Donkey Kong Bananza with the bundled patched hactool. Stock hactool 1.4.0 always prints info (`-x` only adds extract to the default info+extract) and its NPDM printer follows offsets without bounds checks, so it crashes on Switch 2 program metadata. The bundled build (`hactool-1.4.0-nsp2nup.patch`) makes `-x` extract-only and skips an NPDM it can't parse. An old Ryujinx (LibHac 0.16.1) extracted Donkey Kong Bananza fine with the same keys, so keys/crypto aren't the issue.
- **Building the patched hactool:** apply the patch to SciresM/hactool tag 1.4.0 and build as usual (mingw-w64, or `zig cc -target x86_64-windows-gnu`).
- **Decrypters supported:** `hactool.exe` (SciresM) or `hactoolnet.exe` (LibHac). Found next to the script, in `tools\`, or on PATH; hactoolnet wins if both exist; `--tool PATH` overrides.
- **Status:** personal project, public only so a55uka can see it. Not for actual usage: releases are test builds (marked pre-release), no support (README says so at the top).

## Rules this repo must follow

1. **Never commit keys, games or other decrypters.** No `prod.keys`, `title.keys`, `.nsp`, `.nup`, `hactoolnet.exe`, `LibHac.dll`. (The bundled `hactool.exe` is the one exception, see rule 2.) `.gitignore` already blocks them; check `git status` before every commit anyway.
2. **The repo and release zips include `hactool.exe`** (hactool 1.4.0 + `hactool-1.4.0-nsp2nup.patch`, reports itself as `1.4.0-nsp2nup1`), the patch, **and `hactool_LICENSE.txt`** (ISC requires the notice). Decided by KaboWabo, accepting the takedown risk; if GitHub issues or a notice say it has to go, KaboWabo removes it. Still never bundle hactoolnet/LibHac (removed from GitHub by a Nintendo DMCA takedown, May 2025).
3. **No decryption code in nsp2nup itself.** `nsp2nup.py` only drives hactool as a separate program; decryption stays in hactool (SciresM's code plus the small patch).
4. **nup license:** a55uka/nup has no LICENSE file. Ask them for one with an issue on a55uka/nup. Until they add one, share nsp2nup only through this GitHub repo (Code -> Download ZIP), not as a standalone zip with a bundled copy of nup.
5. **Credits:** README credits "KaboWabo/Kabosune (me :3)" and "AI assistance (Claude Opus 5.5)". No AI credits in code. Commits made with AI help end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never put session or conversation links anywhere in the repo or in commits.

## The repo

- **GitHub:** https://github.com/Kabosune/nsp2nup, a public fork of https://github.com/a55uka/nup.
- **Layout:** the converter lives at `tools/nsp2nup/` next to nup's own `tools/nup/`, and uses nup straight from the repo (no bundled copy). Everything else in the repo is a55uka's, unchanged.
- **Branches:** `meow` is a55uka's default branch, kept identical to upstream. nsp2nup lives on the `nsp2nup` branch, which is meow plus `tools/nsp2nup/`.
- **Getting upstream changes:** on GitHub, open the `meow` branch and click **Sync fork**, then merge `meow` into `nsp2nup`. nsp2nup only adds its own folder, so this shouldn't conflict.
- **Standalone copy:** outside the repo, the same folder works on its own with a copy of nup in `lib/nup/` (nsp2nup checks `lib/` first, then `../nup`). Don't share that copy publicly until nup has a license (rule 4).

### Getting it on your PC

Install Git for Windows if you don't have it: https://git-scm.com/download/win (default options are fine). Then open Command Prompt and run these one at a time, pressing Enter after each.

Go to the folder where you keep projects (change the path if you want):

```
cd %USERPROFILE%\Documents
```

Download the repo with the nsp2nup branch:

```
git clone -b nsp2nup https://github.com/Kabosune/nsp2nup.git
```

The converter is then in `nsp2nup\tools\nsp2nup\`; drag NSPs onto `nsp2nup.bat` there.

### Before every commit

Run `git status` and check that it shows no `.keys`, `.nsp` or `.nup` files, and no `.exe` other than `hactool.exe`. Commit messages made with AI help end with the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line and nothing else (no session links).

## Testing without real games

`tests\` has a fake-NSP generator and stand-in decrypters that mimic hactool and hactoolnet (keys checks, title keys, `--basenca`, hactool's missing-folder and silent-failure quirks). From a folder outside the repo, with Python and zstandard installed:

1. `python tests/make_nsps.py fake` builds three fake NSPs (base, update, DLC) in `fake\`.
2. Copy `tests\mock_hactool.py` next to `nsp2nup.py` as `hactool` (Linux/macOS) or point `--tool` at it.
3. Put any text file containing `header_key = ...` in `fake\prod.keys`.
4. Run nsp2nup on the three NSPs plus `prod.keys`, then check the result with `nup verify` and `nup info`.

The mocks only prove the plumbing. Real games are the real test.

## Waiting on a55uka (sent 2026-11-03)

a55uka maintains nup **and** works on Eglantine, so nup's tracker is the place for both.

- **Issue: license** - asked them to add a LICENSE. Until then, see rule 4.
- **PR: `pack: rewind before the raw copy when streamed compression bails`** (branch `fix-stream-raw-fallback`). Their streaming change (ccd75f9) broke packing any file over 256 MB that doesn't compress ("changed while packing"). Also applied on the `nsp2nup` branch.
- **PR: `cli: fix nup info on Python 3.10 and 3.11`** (branch `fix-py310-fstring`). Backslash inside an f-string, 3.12+ only. Also applied on the `nsp2nup` branch.
- **Issue: empty base ExeFS doesn't boot in Eglantine.** Eglantine's `IsSwitch2Program` (src/core/core.cpp) reads `main.npdm` from the base ExeFS even when it's empty, while its loader (src/core/loader/nup.cpp) correctly uses the update's. Suggested fix included. Also suggested that `nup pack` skip empty exefs/romfs folders.
- **X thread** to a55uka: the tool exists, tested on real Switch 1/2 games, `pack()` has no `nacp=` option.

When they merge a fix, sync `meow` and merge it into `nsp2nup`; the duplicate commits resolve cleanly.

## Next session: make nsp2nup as elegant as nup

KaboWabo's goal: nsp2nup should be **elegant, open-ended and built the way nup is**, so the convenience doesn't come from workarounds. nup's design is the model: one small job each, plain files in between, nothing hidden, any tool can feed or read it. nsp2nup currently gives the better experience but is less elegant inside. Open-ended ideas, roughly in order; pick and refine together:

1. **Split into stages with plain files between them**, like nup.
   - `nsp2nup extract NSPs... -> dump/`: decrypt and arrange into nup's standard layout (`base/`, `updates/<v>/`, `dlc/<tid>/<i>/`), plus the game's metadata as **sidecar files** in the dump (e.g. `control.nacp`, icons per language).
   - `nup pack dump/ game.nup`: nup does the packing, reading the sidecars.
   - Drag-and-drop stays one step (it just runs both), but each stage also works on its own, and a dump made any other way packs the same.
2. **Propose a metadata sidecar convention to nup** (small spec addition): if a dump has `control.nacp` + icons, `nup pack` stores them; `nup extract` writes them back out. That makes extract -> repack lossless, gives folder mode names and icons for free, and replaces next-step 4 below.
3. **Remove every monkeypatch of nup internals** by getting small options upstream: `pack(nacp=...)` (or the sidecars above) instead of patching `meta.app_meta`; skipping empty exefs/romfs folders in discovery instead of patching `discover`; a `NupError` exception instead of `SystemExit` for library callers. Goal: nsp2nup only calls nup's public API.
4. **Package nsp2nup like nup:** a `pyproject.toml` with an `nsp2nup` command (`pip install ./tools/nsp2nup`), depending on nup instead of vendoring it; keep `nsp2nup.bat` as the drag-and-drop front end. The standalone zip becomes a build output.
5. **Decrypter as a clean interface:** one small "engine" protocol (extract NCA section, read CNMT/Control) with hactool and hactoolnet as implementations, so a future Switch 2-aware decrypter (or LibHac) plugs in without touching the rest.
6. **Repair mode:** with sidecars and nup's streaming, repair becomes "extract -> fix layout -> pack", made of the same stages instead of separate code. Consider proposing streamed `extract_tree` upstream (today it reads whole files into memory).
7. **Tests:** turn `tests/` into a pytest suite (fake NSPs, empty base, large incompressible file, repair round-trip, `nup verify --deep` on every output), and run it in GitHub Actions.
8. **Releases:** build the zip (and optionally `nsp2nup.exe`) in Actions from a tag, so releases are reproducible.

Keep the personal-project framing and all the rules above.

## Next steps (roughly in order)

1. **Follow up with a55uka** on the items above once they reply; don't pile on new requests before that.
2. **Only if a55uka is interested:** offer a `nacp=` option (or the sidecar convention) for nup's `pack()` so nsp2nup stops patching `meta.app_meta` from outside.
3. **Releases:** test builds go up as GitHub pre-releases: a zip of `tools/nsp2nup/` plus a copy of `tools/nup/nup` in `lib/nup/`, so it runs on its own (needs Python 3.10+). Optional later: a GitHub Actions workflow that also builds `nsp2nup.exe` with PyInstaller so Python isn't needed.
4. **Metadata for extracted folders** (superseded by the sidecar idea above if nup adopts it): let users drop a Control NCA extraction (`control.nacp` + icons) beside `exefs\`/`romfs\` so folder mode gets names and icons too.
5. **Switch 2:** works with the patched hactool (tested on Donkey Kong Bananza). If a later title fails on something new (e.g. compressed NCA sections, which hactool doesn't support), extend the patch or add a LibHac-based engine to the `Hac` class.
6. **Emulator-side add-on toggles:** the format already keeps base/update/DLC as separate packages, so emulators can turn updates or DLC off without a rebuild. Eglantine currently always uses the newest update and skips DLC in a .nup ("AoC mounting is not supported yet"). Updates can only be turned off when the .nup has a base package (update-only dumps have no unpatched copy).
7. **Unsupported for now:** `.nsz`/`.xci`, DLC updates (NUP v1 reserves that kind), multi-program titles (only the main program is packed).
