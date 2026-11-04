# nsp2nup repo notes

Handoff notes for the nsp2nup repo. Written so a future session (or you) can pick it up cold.

## Where the project stands

- **Works:** Switch 1 NSPs -> `.nup` (base + updates + DLC, name/icon/NACP). Tested for real on Link's Awakening with hactool 1.4.0.
- **Works:** already-extracted game folders (`exefs\` + `romfs\`) -> `.nup`, no keys or decrypter needed.
- **Works:** Switch 2 NSPs, tested for real on Donkey Kong Bananza with the bundled patched hactool. Stock hactool 1.4.0 always prints info (`-x` only adds extract to the default info+extract) and its NPDM printer follows offsets without bounds checks, so it crashes on Switch 2 program metadata. The bundled build (`hactool-1.4.0-nsp2nup.patch`) makes `-x` extract-only and skips an NPDM it can't parse. An old Ryujinx (LibHac 0.16.1) extracted Donkey Kong Bananza fine with the same keys, so keys/crypto aren't the issue.
- **Building the patched hactool:** apply the patch to SciresM/hactool tag 1.4.0 and build as usual (mingw-w64, or `zig cc -target x86_64-windows-gnu`).
- **Decrypters supported:** `hactool.exe` (SciresM) or `hactoolnet.exe` (LibHac). Found next to the script, in `tools\`, or on PATH; hactoolnet wins if both exist; `--tool PATH` overrides.
- **Status:** personal project, public only so a55uka can see it. Not for actual usage: no releases, no support (README says so at the top).

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

## Next steps (roughly in order)

1. **Ask a55uka for a license** (issue on a55uka/nup), mentioning nsp2nup as a personal project since their README says they don't know of a Switch 1 converter.
2. **Only if a55uka is interested:** offer a `nacp=` option for nup's `pack()` so nsp2nup stops patching `meta.app_meta` from outside.
3. **Release exe (only if this stops being personal-only):** GitHub Actions workflow that builds `nsp2nup.exe` with PyInstaller.
4. **Metadata for extracted folders:** let users drop a Control NCA extraction (`control.nacp` + icons) beside `exefs\`/`romfs\` so folder mode gets names and icons too.
5. **Switch 2:** works with the patched hactool (tested on Donkey Kong Bananza). If a later title fails on something new (e.g. compressed NCA sections, which hactool doesn't support), extend the patch or add a LibHac-based engine to the `Hac` class.
6. **Unsupported for now:** `.nsz`/`.xci`, DLC updates (NUP v1 reserves that kind), multi-program titles (only the main program is packed).
