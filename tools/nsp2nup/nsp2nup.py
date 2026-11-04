"""nsp2nup - convert Nintendo Switch NSP files into a single .nup container.

Drop any mix of base game / update / DLC .nsp files (and your keys) onto
nsp2nup.bat. Files are grouped by game; each game becomes one .nup with
base + updates + DLC inside, written next to the first NSP.

Decryption is done by hactoolnet or hactool. This script handles the rest:
reading the NSP (PFS0), pulling title keys from its tickets, reading the
CNMT to sort out base/update/DLC, laying out the folders nup expects, and
packing with nup's own reference packer.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field

if sys.version_info < (3, 10):
    sys.exit("nsp2nup needs Python 3.10 or newer (python.org/downloads)")

FROZEN = getattr(sys, "frozen", False)
TOOL_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
for _p in (os.path.join(TOOL_DIR, "..", "nup"), os.path.join(TOOL_DIR, "lib")):
    sys.path.insert(0, _p)  # lib/ (standalone zip) wins over ../nup (inside the nup repo)

from nup import format as F  # noqa: E402
from nup import meta as M  # noqa: E402
import nup.pack as P  # noqa: E402
from nup.pack import pack, have_zstd  # noqa: E402
from nup.discover import parse_npdm_program_id  # noqa: E402
from nup.access import iter_children, meta_records  # noqa: E402
from nup.read import NupReader  # noqa: E402

# ---------------------------------------------------------------- constants

META_APPLICATION = 0x80
META_PATCH = 0x81
META_ADDON = 0x82
META_DELTA = 0x83
META_DATA_PATCH = 0x84
META_NAMES = {META_APPLICATION: "base game", META_PATCH: "update",
              META_ADDON: "DLC", META_DELTA: "delta", META_DATA_PATCH: "DLC update"}

CT_META, CT_PROGRAM, CT_DATA, CT_CONTROL = 0, 1, 2, 3

# NACP language slots in order, with their BCP-47 tags (SPEC Appendix B).
NACP_LANGS = [
    ("AmericanEnglish", "en-us"), ("BritishEnglish", "en-gb"), ("Japanese", "ja"),
    ("French", "fr"), ("German", "de"), ("LatinAmericanSpanish", "es-419"),
    ("Spanish", "es"), ("Italian", "it"), ("Dutch", "nl"), ("CanadianFrench", "fr-ca"),
    ("Portuguese", "pt"), ("Russian", "ru"), ("Korean", "ko"),
    ("TraditionalChinese", "zh-hant"), ("SimplifiedChinese", "zh-hans"),
    ("BrazilianPortuguese", "pt-br"),
]


class ConvertError(Exception):
    pass


def log(msg: str = "") -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- PFS0 (the NSP itself)

def read_pfs0(path: str) -> list[tuple[str, int, int]]:
    """Return [(name, absolute offset, size)] for every file in a PFS0/NSP."""
    with open(path, "rb") as fh:
        head = fh.read(0x10)
        if len(head) < 0x10 or head[:4] != b"PFS0":
            raise ConvertError(f"{os.path.basename(path)} is not an NSP (no PFS0 header). "
                               "If it's an .nsz/.xci, convert it to a plain .nsp first.")
        count, strtab_size = struct.unpack_from("<II", head, 4)
        entries = fh.read(count * 0x18)
        strtab = fh.read(strtab_size)
    data_start = 0x10 + count * 0x18 + strtab_size
    out = []
    for i in range(count):
        off, size, name_off, _ = struct.unpack_from("<QQII", entries, i * 0x18)
        end = strtab.find(b"\0", name_off)
        name = strtab[name_off:end if end >= 0 else None].decode("utf-8", "replace")
        out.append((name, data_start + off, size))
    return out


def copy_range(src: str, offset: int, size: int, dst: str) -> None:
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fi.seek(offset)
        left = size
        while left:
            chunk = fi.read(min(left, 8 << 20))
            if not chunk:
                raise ConvertError(f"{os.path.basename(src)} is truncated")
            fo.write(chunk)
            left -= len(chunk)


def read_range(src: str, offset: int, size: int) -> bytes:
    with open(src, "rb") as fh:
        fh.seek(offset)
        return fh.read(size)


# ---------------------------------------------------------------- tickets -> title keys

_SIG_SIZES = {  # signature type -> bytes before the ticket body (sig + padding)
    0x010000: 0x23C, 0x010001: 0x13C, 0x010002: 0x7C,
    0x010003: 0x240, 0x010004: 0x140, 0x010005: 0x80,
}


def parse_ticket(data: bytes) -> tuple[str, str] | None:
    """(rights_id_hex, encrypted_title_key_hex) for a common ticket, else None."""
    if len(data) < 4:
        return None
    body = _SIG_SIZES.get(struct.unpack_from("<I", data, 0)[0])
    if body is None or len(data) < body + 0x170:
        return None
    key_type = data[body + 0x141]
    rights_id = data[body + 0x160: body + 0x170]
    if key_type != 0:
        log(f"  ! ticket {rights_id.hex()} is personalized (console-bound); "
            "its key can't be read from the NSP - add it to title.keys if you have it")
        return None
    return rights_id.hex(), data[body + 0x40: body + 0x50].hex()


# ---------------------------------------------------------------- CNMT / NACP

@dataclass
class Content:
    nca_id: str
    ctype: int
    id_offset: int


@dataclass
class Cnmt:
    title_id: int
    version: int
    meta_type: int
    app_id: int
    contents: list[Content]


def parse_cnmt(data: bytes) -> Cnmt:
    title_id, version, meta_type = struct.unpack_from("<QIB", data, 0)
    ext_size, content_count = struct.unpack_from("<HH", data, 0x0E)
    app_id = title_id
    if meta_type in (META_PATCH, META_ADDON, META_DATA_PATCH) and ext_size >= 8:
        app_id = struct.unpack_from("<Q", data, 0x20)[0]
    contents = []
    pos = 0x20 + ext_size
    for _ in range(content_count):
        nca_id = data[pos + 0x20: pos + 0x30].hex()
        ctype, id_off = data[pos + 0x36], data[pos + 0x37]
        contents.append(Content(nca_id, ctype, id_off))
        pos += 0x38
    return Cnmt(title_id, version, meta_type, app_id, contents)


def parse_nacp(data: bytes) -> dict:
    """Names, publisher and display version out of a control.nacp."""
    def s(raw: bytes) -> str:
        return raw.split(b"\0", 1)[0].decode("utf-8", "replace").strip()

    names, publisher = {}, None
    for i, (_lang, tag) in enumerate(NACP_LANGS):
        base = i * 0x300
        if base + 0x300 > len(data):
            break
        name, pub = s(data[base:base + 0x200]), s(data[base + 0x200:base + 0x300])
        if name:
            names[tag] = name
        if pub and publisher is None:
            publisher = pub
    disp = s(data[0x3060:0x3070]) if len(data) >= 0x3070 else ""
    return {"names": names, "publisher": publisher, "display_version": disp or None}


# ---------------------------------------------------------------- decrypter (hactoolnet or hactool)

DECRYPTERS = ("hactoolnet", "hactool")  # preference order when both are present
_HACTOOL_FAIL = ("unable to match rights id", "invalid nca header", "failed to")


def find_decrypter(explicit: str | None) -> str:
    if explicit:
        if not os.path.isfile(explicit):
            raise ConvertError(f"decrypter not found: {explicit}")
        return explicit
    ext = ".exe" if os.name == "nt" else ""
    for name in DECRYPTERS:
        for c in (os.path.join(TOOL_DIR, name + ext), os.path.join(TOOL_DIR, "tools", name + ext)):
            if os.path.isfile(c):
                return c
    for name in DECRYPTERS:
        on_path = shutil.which(name)
        if on_path:
            return on_path
    raise ConvertError(
        "No decrypter found. Put hactoolnet.exe or hactool.exe in this folder:\n"
        f"    {TOOL_DIR}")


class Hac:
    """Runs hactoolnet or hactool; both take nearly the same NCA options."""

    def __init__(self, exe: str, prod_keys: str, work: str) -> None:
        self.exe, self.prod_keys = exe, prod_keys
        self.is_net = "hactoolnet" in os.path.basename(exe).lower()
        self.name = "hactoolnet" if self.is_net else "hactool"
        self.title_keys: dict[str, str] = {}
        self.tk_file = os.path.join(work, "title.keys")

    def add_title_key(self, rights_id: str, key: str) -> None:
        self.title_keys[rights_id.strip().lower()] = key.strip().lower()

    def _key_for(self, title_id: int | None) -> str | None:
        """Rights IDs start with the title ID; pick the newest key generation."""
        if title_id is None:
            return None
        prefix = f"{title_id:016x}"
        hits = sorted(r for r in self.title_keys if r.startswith(prefix))
        return self.title_keys[hits[-1]] if hits else None

    def nca(self, nca: str, *, what: str, tid: int | None = None,
            exefs: str | None = None, romfs: str | None = None,
            section0: str | None = None, base: str | None = None) -> None:
        opts = [("basenca", base), ("exefsdir", exefs), ("romfsdir", romfs),
                ("section0dir", section0)]
        if self.is_net:
            with open(self.tk_file, "w") as fh:
                fh.write("".join(f"{r} = {k}\n" for r, k in self.title_keys.items()))
            cmd = [self.exe, "-k", self.prod_keys, "--titlekeys", self.tk_file, "-t", "nca"]
            for name, val in opts:
                if val:
                    cmd += ["--" + name, val]
        else:
            # -x = extract. Stock hactool 1.4.0 also prints info with it and crashes on
            # Switch 2 NPDMs; the bundled 1.4.0-nsp2nup1 build makes -x extract-only.
            cmd = [self.exe, "-x", "-k", self.prod_keys, "-t", "nca", "--disablekeywarns"]
            key = self._key_for(tid)
            if key:
                cmd.append("--titlekey=" + key)
            cmd += ["--" + name + "=" + val for name, val in opts if val]
        cmd.append(nca)
        for d in (exefs, romfs, section0):  # hactool only creates the last folder level
            if d:
                os.makedirs(d, exist_ok=True)
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        out = (r.stdout + r.stderr).strip()
        low = out.lower()
        produced = any(d and os.path.isdir(d) and os.listdir(d)
                       for d in (exefs, romfs, section0))
        bad = not self.is_net and any(m in low for m in _HACTOOL_FAIL)
        if r.returncode != 0 or not produced or bad:
            lines = out.splitlines()
            errs = [ln for ln in lines if any(m in ln.lower() for m in
                    ("fail", "error", "invalid", "unable", "missing", "exception"))]
            shown = (errs or lines)[-15:]
            tail = "\n".join("    " + ln for ln in shown)
            if len(errs) > 15:
                tail = f"    ... ({len(errs) - 15} more similar lines)\n" + tail
            elow = "\n".join(errs).lower()
            hint = ""
            if tid is not None and tid >> 56 == 0x04:
                hint = (f"\n  -> this is a Switch 2 title. Stock {self.name} builds crash on Switch 2 "
                        "metadata; use the hactool.exe that comes with nsp2nup (1.4.0-nsp2nup1). "
                        "If that's the one failing, your keys may still be fine - report the "
                        "messages above.")
            elif not errs:
                hint = (f"\n  -> {self.name} stopped without an error message (exit code "
                        f"{r.returncode}) - it probably crashed on something it doesn't "
                        "understand; a newer version may be needed.")
            elif "rights id" in elow or "title key" in elow or "titlekey" in elow:
                hint = "\n  -> missing title key: the ticket wasn't in the NSP; add a title.keys."
            elif "failed to open" in elow or "denied" in elow or "space" in elow:
                hint = ("\n  -> couldn't write the extracted files: check free disk space, and "
                        "that antivirus isn't blocking the temp folder.")
            elif "nca header" in elow or "key" in elow:
                hint = ("\n  -> looks like a key problem: your prod.keys may be older "
                        f"than this game's firmware, or this {self.name} is too old for it.")
            raise ConvertError(f"{self.name} failed on {what}:\n{tail}{hint}")


# ---------------------------------------------------------------- keys

def resolve_keys(dropped: list[str], save: bool) -> tuple[str, str | None]:
    """Pick prod.keys / title.keys: dropped > tool folder > ~/.switch."""
    dropped_prod = [k for k in dropped if "title" not in os.path.basename(k).lower()]
    dropped_title = [k for k in dropped if "title" in os.path.basename(k).lower()]
    store = os.path.join(TOOL_DIR, "keys")

    def pick(drops: list[str], name: str) -> str | None:
        if drops:
            src = drops[0]
            if save:
                os.makedirs(store, exist_ok=True)
                dst = os.path.join(store, name)
                if not (os.path.isfile(dst) and _same(src, dst)):
                    shutil.copyfile(src, dst)
                    log(f"Saved {os.path.basename(src)} as keys\\{name} - "
                        "next time you only need to drop NSPs.")
            return src
        for c in (os.path.join(store, name), os.path.join(TOOL_DIR, name),
                  os.path.join(os.path.expanduser("~"), ".switch", name)):
            if os.path.isfile(c):
                return c
        return None

    prod = pick(dropped_prod, "prod.keys")
    title = pick(dropped_title, "title.keys")
    if not prod:
        raise ConvertError(
            "No prod.keys found. Drop your prod.keys together with the NSP (once is "
            f"enough - it gets saved), or put it in:\n    {store}")
    return prod, title


def _same(a: str, b: str) -> bool:
    def h(p: str) -> bytes:
        with open(p, "rb") as fh:
            return hashlib.sha256(fh.read()).digest()
    return h(a) == h(b)


# ---------------------------------------------------------------- conversion

@dataclass
class Title:
    cnmt: Cnmt
    nsp: str
    ncas: dict[str, str]  # nca_id -> extracted path

    def nca_of(self, ctype: int, id_offset: int = 0) -> str | None:
        for c in self.cnmt.contents:
            if c.ctype == ctype and c.id_offset == id_offset:
                return self.ncas.get(c.nca_id)
        return None


@dataclass
class Game:
    app_id: int
    base: Title | None = None
    updates: list[Title] = field(default_factory=list)
    dlcs: list[Title] = field(default_factory=list)


def unpack_nsp(nsp: str, work: str, hac: Hac) -> list[Title]:
    """Copy NCAs/tickets out of an NSP and read its CNMT(s)."""
    name = os.path.basename(nsp)
    entries = read_pfs0(nsp)
    if any(e[0].lower().endswith(".ncz") for e in entries):
        raise ConvertError(f"{name} contains .ncz (NSZ-compressed) content. "
                           "Decompress it back to a normal NSP first (e.g. with nsz -D).")
    os.makedirs(work, exist_ok=True)
    for fname, off, size in entries:
        if fname.lower().endswith(".tik"):
            tk = parse_ticket(read_range(nsp, off, size))
            if tk:
                hac.add_title_key(*tk)

    ncas: dict[str, str] = {}
    metas: list[str] = []
    for fname, off, size in entries:
        low = fname.lower()
        if not low.endswith(".nca"):
            continue
        dst = os.path.join(work, fname)
        copy_range(nsp, off, size, dst)
        ncas[low.split(".")[0]] = dst
        if low.endswith(".cnmt.nca"):
            metas.append(dst)
    if not metas:
        raise ConvertError(f"{name} has no .cnmt.nca - can't tell what it contains.")

    titles = []
    for meta_nca in metas:
        out = os.path.join(work, "cnmt_" + os.path.basename(meta_nca).split(".")[0])
        hac.nca(meta_nca, what=f"{name} (metadata)", section0=out)
        cnmt_files = [f for f in os.listdir(out) if f.lower().endswith(".cnmt")]
        if not cnmt_files:
            raise ConvertError(f"{name}: metadata NCA had no .cnmt inside")
        with open(os.path.join(out, cnmt_files[0]), "rb") as fh:
            titles.append(Title(parse_cnmt(fh.read()), nsp, ncas))
    return titles


def control_meta(title: Title, hac: Hac, work: str) -> tuple[dict, str | None]:
    """names/icons/publisher/display version (+ raw NACP bytes) from the Control NCA."""
    info: dict = {"names": {}, "icons": {}, "publisher": None, "display_version": None,
                  "nacp": None}
    nca = title.nca_of(CT_CONTROL)
    if not nca:
        return info, None
    out = os.path.join(work, "control")
    try:
        hac.nca(nca, what="control data (name/icon)", tid=title.cnmt.title_id, romfs=out)
    except ConvertError as e:
        log(f"  ! couldn't read name/icon, continuing without it ({str(e).splitlines()[0]})")
        return info, None
    nacp_path = os.path.join(out, "control.nacp")
    if os.path.isfile(nacp_path):
        with open(nacp_path, "rb") as fh:
            info["nacp"] = fh.read()
        info.update({k: v for k, v in parse_nacp(info["nacp"]).items()})
    for lang, tag in NACP_LANGS:
        p = os.path.join(out, f"icon_{lang}.dat")
        if os.path.isfile(p):
            info["icons"][tag] = p
    return info, out


def default_of(d: dict) -> str | None:
    if "en-us" in d:
        return d["en-us"]
    return next(iter(d.values()), None)


def safe_filename(s: str) -> str:
    bad = '<>:"/\\|?*'
    s = "".join("_" if c in bad or ord(c) < 32 else c for c in s).strip(" .")
    return s or "game"


def build_game(game: Game, hac: Hac, work: str, out_dir: str | None, level: int,
               skipped: list[str]) -> str:
    base = game.base
    tid = f"{game.app_id:016X}"
    if base is None:
        kinds = ", ".join(sorted({META_NAMES[t.cnmt.meta_type]
                                  for t in game.updates + game.dlcs}))
        raise ConvertError(
            f"[{tid}] only got {kinds} - drop the base game NSP too. Updates are "
            "patches on top of the base RomFS, so they can't be rebuilt without it.")

    dump = os.path.join(work, f"dump_{tid}")
    log(f"\n== {tid}: extracting base game")
    base_prog = base.nca_of(CT_PROGRAM)
    if not base_prog:
        raise ConvertError(f"[{tid}] base game has no Program NCA")
    extra_programs = [c for c in base.cnmt.contents if c.ctype == CT_PROGRAM and c.id_offset]
    if extra_programs:
        log(f"  ! multi-program title: only the main program is packed "
            f"({len(extra_programs)} extra program(s) skipped - NUP v1 allows one base)")
    hac.nca(base_prog, what="base game program", tid=base.cnmt.title_id,
            exefs=os.path.join(dump, "base", "exefs"),
            romfs=os.path.join(dump, "base", "romfs"))
    if not os.path.isfile(os.path.join(dump, "base", "exefs", "main.npdm")):
        raise ConvertError(f"[{tid}] base program extracted without exefs/main.npdm")

    info, _ = control_meta(base, hac, os.path.join(work, f"ctl_{tid}"))

    for upd in sorted(game.updates, key=lambda t: t.cnmt.version):
        ver = upd.cnmt.version
        log(f"== {tid}: applying update v{ver}")
        prog = upd.nca_of(CT_PROGRAM)
        if not prog:
            log(f"  ! update v{ver} has no Program NCA, skipped")
            continue
        udir = os.path.join(dump, "updates", str(ver))
        try:
            hac.nca(prog, what=f"update v{ver}", tid=upd.cnmt.title_id, base=base_prog,
                    exefs=os.path.join(udir, "exefs"), romfs=os.path.join(udir, "romfs"))
        except ConvertError as e:
            log(f"ERROR: {e}\n  -> update v{ver} left out of the .nup")
            skipped.append(f"update v{ver}")
            shutil.rmtree(udir, ignore_errors=True)

    for dlc in sorted(game.dlcs, key=lambda t: t.cnmt.title_id):
        dtid = f"{dlc.cnmt.title_id:016x}"
        log(f"== {tid}: extracting DLC {dtid.upper()}")
        datas = [c for c in dlc.cnmt.contents if c.ctype == CT_DATA]
        if not datas:
            log(f"  ! DLC {dtid} has no data NCA, skipped")
            continue
        try:
            for c in datas:
                hac.nca(dlc.ncas[c.nca_id], what=f"DLC {dtid}", tid=dlc.cnmt.title_id,
                        romfs=os.path.join(dump, "dlc", dtid, str(c.id_offset), "romfs"))
        except ConvertError as e:
            log(f"ERROR: {e}\n  -> DLC {dtid.upper()} left out of the .nup")
            skipped.append(f"DLC {dtid.upper()}")
            shutil.rmtree(os.path.join(dump, "dlc", dtid), ignore_errors=True)

    # --- name the output
    name = default_of(info["names"])
    stem = f"{safe_filename(name)} [{tid}]" if name else \
        os.path.splitext(os.path.basename(base.nsp))[0]
    out = unique_path(out_dir or os.path.dirname(os.path.abspath(base.nsp)), stem)

    # --- metadata for nup: default name/icon + localized ones that differ
    names: dict = {}
    icons: dict = {}
    if name:
        names[None] = name
        names.update({k: v for k, v in info["names"].items()})
    default_icon = default_of(info["icons"])
    if default_icon:
        icons[None] = default_icon
        with open(default_icon, "rb") as fh:
            dflt = fh.read()
        for tag, p in info["icons"].items():
            with open(p, "rb") as fh:
                if fh.read() != dflt:
                    icons[tag] = p

    log(f"== {tid}: packing {os.path.basename(out)}")
    _with_nacp(info["nacp"], lambda: pack(
        out, dump, level=level, display_version=info["display_version"],
        publisher=info["publisher"], names=names, icons=icons,
        progress=_progress))
    print()
    return out


def _with_nacp(nacp: bytes | None, fn):
    """nup's pack() has no NACP option; add TLV 0x0002 to the app-level meta block."""
    if not nacp:
        return fn()
    orig = M.app_meta

    def app_meta(*a, **k):
        recs = M.parse_block(orig(*a, **k))
        recs[F.TLV_NACP] = nacp
        return M.serialize_block(recs)

    M.app_meta = app_meta
    try:
        return fn()
    finally:
        M.app_meta = orig


_last = [0.0]


def _progress(done: int, total: int, _f) -> None:
    now = time.time()
    if now - _last[0] >= 0.3 or done == total:
        _last[0] = now
        pct = done * 100 // total if total else 100
        sys.stdout.write(f"\r  {done}/{total} files ({pct}%)")
        sys.stdout.flush()


# ---------------------------------------------------------------- main

def is_dump_dir(p: str) -> bool:
    """An already-extracted game: exefs/ + romfs/, or a base/ updates/ dlc/ bundle."""
    return any(os.path.isdir(os.path.join(p, d)) for d in ("exefs", "romfs", "base", "updates"))


def collect_inputs(paths: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    nsps, keys, dumps, nups = [], [], [], []
    for p in paths:
        p = p.strip().strip('"')
        p = os.path.abspath(p) if p else p
        if os.path.isdir(p):
            if is_dump_dir(p):
                dumps.append(p)
                continue
            for f in sorted(os.listdir(p)):
                fp = os.path.join(p, f)
                if f.lower().endswith(".nsp"):
                    nsps.append(fp)
                elif f.lower().endswith(".keys"):
                    keys.append(fp)
                elif os.path.isdir(fp) and is_dump_dir(fp):
                    dumps.append(fp)
        elif p.lower().endswith(".nsp"):
            nsps.append(p)
        elif p.lower().endswith(".keys") and os.path.isfile(p):
            keys.append(p)
        elif p.lower().endswith(".nup") and os.path.isfile(p):
            nups.append(p)
        elif p.lower().endswith((".nsz", ".xci", ".xcz")):
            log(f"! skipping {os.path.basename(p)}: only plain .nsp is supported")
        elif p:
            log(f"! skipping {os.path.basename(p)}: not an .nsp, .nup, .keys or game folder")
    return nsps, keys, dumps, nups


def unique_path(folder: str, stem: str) -> str:
    out = os.path.join(folder, stem + ".nup")
    n = 2
    while os.path.exists(out):
        out = os.path.join(folder, f"{stem} ({n}).nup")
        n += 1
    return out


def _empty_base_title_id(src: str) -> int | None:
    """Title ID for a dump whose base/ has no files (some dumpers keep only the fully
    patched update). nup reads the ID from base/exefs/main.npdm, so take it from the
    newest update's main.npdm instead."""
    base = os.path.join(src, "base")
    if not os.path.isdir(base) or any(files for _, _, files in os.walk(base)):
        return None
    upd = os.path.join(src, "updates")
    if not os.path.isdir(upd):
        return None
    versions = sorted((v for v in os.listdir(upd) if v.isdigit()), key=int, reverse=True)
    for v in versions:
        npdm = os.path.join(upd, v, "exefs", "main.npdm")
        if os.path.isfile(npdm):
            with open(npdm, "rb") as fh:
                tid = parse_npdm_program_id(fh.read())
            if tid:
                return tid
    return None


def _without_base(fn):
    """Pack as an update-only dump, the way nup does when there's no base/ at all.
    An empty base/ (or one with only empty exefs/ romfs/ folders) would otherwise
    become a base package with an empty ExeFS, and emulators then look there for
    the game's code instead of in the update."""
    orig = P.discover

    def discover(src, base_title_id):
        pkgs = [p for p in orig(src, base_title_id) if p.kind != F.KIND_BASE]
        for p in pkgs:
            if p.kind == F.KIND_UPDATE:
                p.flags |= F.PKG_FLAG_STANDALONE_UPDATE
        return pkgs

    P.discover = discover
    try:
        return fn()
    finally:
        P.discover = orig


def pack_dump(src: str, out_dir: str | None, level: int) -> str:
    """Pack an already-extracted game folder (no keys or decrypter needed)."""
    name = os.path.basename(os.path.normpath(src))
    out = unique_path(out_dir or os.path.dirname(os.path.normpath(src)), safe_filename(name))
    log(f"== packing extracted folder {name}")
    base_tid = _empty_base_title_id(src)
    if base_tid is not None:
        log(f"  base\\ is empty: leaving it out; the update ({base_tid:016X}) carries the whole game")
    try:
        if base_tid is None:
            packages = pack(out, src, level=level, progress=_progress)
        else:
            packages = _without_base(lambda: pack(out, src, level=level,
                                                  base_title_id=base_tid, progress=_progress))
    except SystemExit as e:  # nup reports layout problems this way
        raise ConvertError(str(e))
    print()
    for pk in packages:
        log(f"  {F.KIND_NAMES[pk.kind]:<6} {pk.title_id:016X}  v{pk.version}")
    return out


# ---------------------------------------------------------------- repairing .nup files

_CARRY_META = (F.TLV_NACP, F.TLV_ICON, F.TLV_DISPLAY_VERSION, F.TLV_TITLE_NAME,
               F.TLV_PUBLISHER, F.TLV_LOCALIZED_TITLES, F.TLV_LOCALIZED_ICONS)


class _Limited:
    """File-like view of the next `left` bytes of fh (one extent)."""

    def __init__(self, fh, left: int) -> None:
        self.fh, self.left = fh, left

    def read(self, n: int = -1) -> bytes:
        if self.left <= 0:
            return b""
        n = self.left if n is None or n < 0 else min(n, self.left)
        data = self.fh.read(n)
        self.left -= len(data)
        return data


def _tree_files(r: NupReader, dir_index: int, dirs: list | None = None) -> list[tuple[int, str]]:
    """(file index, relative path) for every file under a directory; subfolder
    paths go into `dirs` if given (so empty folders survive a rebuild)."""
    out, stack = [], [(dir_index, "")]
    while stack:
        di, rel = stack.pop()
        for child in iter_children(r, di):
            name = child.name.decode("utf-8", "surrogateescape")
            path = os.path.join(rel, name) if rel else name
            if child.is_dir:
                stack.append((child.index, path))
                if dirs is not None:
                    dirs.append(path)
            else:
                out.append((child.index, path))
    return out


def _extract_streamed(r: NupReader, nup_path: str, files: list, dest: str,
                      done: list, total: int) -> None:
    """Extract files in chunks (no whole-file reads) and check each SHA-256."""
    with open(nup_path, "rb") as src:
        for fi, rel in files:
            name, size, sha, eoff, esz, codec = r.files[fi]
            target = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            h = hashlib.sha256()
            with open(target, "wb") as dst:
                if size:
                    src.seek(eoff)
                    if codec == F.CODEC_RAW:
                        reader = _Limited(src, esz)
                    elif codec == F.CODEC_ZSTD:
                        try:
                            import zstandard
                        except ImportError:
                            raise ConvertError("this .nup is compressed and zstandard isn't "
                                               "available to read it")
                        reader = zstandard.ZstdDecompressor().stream_reader(_Limited(src, esz))
                    else:
                        raise ConvertError(f"{rel}: unknown codec {codec}")
                    while True:
                        chunk = reader.read(4 << 20)
                        if not chunk:
                            break
                        h.update(chunk)
                        dst.write(chunk)
            if os.path.getsize(target) != size or (size and h.digest() != bytes(sha)):
                raise ConvertError(f"{rel}: content doesn't match its checksum (damaged .nup?)")
            done[0] += 1
            _progress(done[0], total, None)


def _with_app_meta(extra: dict[int, bytes], fn):
    """Put carried-over app metadata (name, icons, NACP...) into the new app meta block."""
    if not extra:
        return fn()
    orig = M.app_meta

    def app_meta(*a, **k):
        recs = M.parse_block(orig(*a, **k))
        recs.update(extra)
        return M.serialize_block(recs)

    M.app_meta = app_meta
    try:
        return fn()
    finally:
        M.app_meta = orig


def repair_nup(path: str, out_dir: str | None, level: int, keep_work: bool) -> str | None:
    """Rebuild a .nup whose base package has no files (it hides the update's ExeFS).
    Writes '<name> (fixed).nup' and leaves the original alone. None = nothing to fix."""
    name = os.path.splitext(os.path.basename(path))[0]
    folder = out_dir or os.path.dirname(os.path.abspath(path))
    log(f"== checking {os.path.basename(path)}")
    with NupReader(path) as r:
        pkgs = list(r.packages)
        base = next((p for p in pkgs if p.kind == F.KIND_BASE), None)
        updates = [p for p in pkgs if p.kind == F.KIND_UPDATE]
        if base is None or not updates or _tree_files(r, base.root_dir):
            log("  nothing to repair (no empty base package)")
            return None
        log("  base package is empty: rebuilding with the update carrying the whole game")

        extra: dict[int, bytes] = {}
        for p in [base] + [q for q in pkgs if q is not base]:
            for t, payload in meta_records(r, p):
                if t in _CARRY_META and t not in extra:
                    extra[t] = payload

        jobs = [(u.root_dir, os.path.join("updates", str(u.version))) for u in updates]
        seen: dict[int, int] = {}
        for a in (p for p in pkgs if p.kind == F.KIND_ADDON):
            n = seen.get(a.title_id, 0)
            seen[a.title_id] = n + 1
            jobs.append((a.root_dir, os.path.join("dlc", f"{a.title_id:016x}", str(n))))
        for p in pkgs:
            if p.kind not in (F.KIND_BASE, F.KIND_UPDATE, F.KIND_ADDON):
                log(f"  ! skipping a {F.KIND_NAMES.get(p.kind, p.kind)} package (not supported)")

        file_lists, all_dirs = [], []
        for d, sub in jobs:
            dirs: list[str] = []
            file_lists.append((_tree_files(r, d, dirs), sub))
            all_dirs += [os.path.join(sub, x) for x in dirs]
        total = sum(len(f) for f, _ in file_lists)
        need = sum(r.files[fi][1] for f, _ in file_lists for fi, _ in f)
        work = os.path.join(folder, f"_nsp2nup_tmp_{os.getpid()}")
        free = shutil.disk_usage(folder).free
        if free < need * 2:
            log(f"  ! low disk space: about {need * 2 / 2**30:.1f} GB needed while repairing, "
                f"{free / 2**30:.1f} GB free")
        dump = os.path.join(work, name)
        log(f"  extracting {total} files ({need / 2**30:.1f} GB) to a temp folder")
        try:
            done = [0]
            for d in all_dirs:
                os.makedirs(os.path.join(dump, d), exist_ok=True)
            for files, sub in file_lists:
                _extract_streamed(r, path, files, os.path.join(dump, sub), done, total)
            print()
        except BaseException:
            if not keep_work:
                shutil.rmtree(work, ignore_errors=True)
            raise
    out = unique_path(folder, safe_filename(name) + " (fixed)")
    log(f"  packing {os.path.basename(out)}")
    try:
        packages = _with_app_meta(extra, lambda: pack(out, dump, level=level,
                                                      progress=_progress))
    except SystemExit as e:
        raise ConvertError(str(e))
    finally:
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)
    print()
    for pk in packages:
        log(f"  {F.KIND_NAMES[pk.kind]:<6} {pk.title_id:016X}  v{pk.version}")
    return out


def convert_nsps(nsps: list[str], key_files: list[str], args) -> tuple[list, int]:
    made: list = []
    failed = 0
    prod_keys, user_title_keys = resolve_keys(key_files, save=not args.no_save_keys)
    hac_exe = find_decrypter(args.tool)

    work_root = args.out_dir or os.path.dirname(os.path.abspath(nsps[0]))
    work = os.path.join(work_root, f"_nsp2nup_tmp_{os.getpid()}")
    os.makedirs(work, exist_ok=True)

    hac = Hac(hac_exe, prod_keys, work)
    log(f"Using {hac.name}: {hac_exe}")
    if user_title_keys:
        with open(user_title_keys, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                rid, sep, key = ln.replace(",", "=").partition("=")
                if sep and len(rid.strip()) == 32 and len(key.strip()) == 32:
                    hac.add_title_key(rid, key)

    try:
        games: dict[int, Game] = {}
        for i, nsp in enumerate(nsps):
            log(f"Reading {os.path.basename(nsp)}")
            try:
                titles = unpack_nsp(nsp, os.path.join(work, f"nsp{i}"), hac)
            except ConvertError as e:
                log(f"ERROR: {e}")
                failed += 1
                continue
            for t in titles:
                c = t.cnmt
                kind = META_NAMES.get(c.meta_type, hex(c.meta_type))
                log(f"  {kind:<9} {c.title_id:016X}  v{c.version}")
                g = games.setdefault(c.app_id, Game(c.app_id))
                if c.meta_type == META_APPLICATION:
                    if g.base is not None:
                        log("  ! duplicate base game, using the first one")
                    else:
                        g.base = t
                elif c.meta_type == META_PATCH:
                    if any(u.cnmt.version == c.version for u in g.updates):
                        log("  ! duplicate update version, using the first one")
                    else:
                        g.updates.append(t)
                elif c.meta_type == META_ADDON:
                    if any(d.cnmt.title_id == c.title_id for d in g.dlcs):
                        log("  ! duplicate DLC, using the first one")
                    else:
                        g.dlcs.append(t)
                else:
                    log(f"  ! {kind} content isn't supported by NUP v1, skipped")

        for g in games.values():
            if not (g.base or g.updates or g.dlcs):
                continue
            skipped: list[str] = []
            try:
                out = build_game(g, hac, os.path.join(work, f"g{g.app_id:016x}"),
                                 args.out_dir, args.level, skipped)
                made.append((out, skipped))
            except ConvertError as e:
                log(f"ERROR: {e}")
                failed += 1
    finally:
        if args.keep_work:
            log(f"(temp files kept in {work})")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return made, failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="nsp2nup",
        description="Convert NSP files (base, updates, DLC) or already-extracted game "
                    "folders (exefs/ + romfs/) into .nup containers. "
                    "Pass NSPs, .keys files or folders in any order. A dropped .nup is "
                    "checked and repaired into '<name> (fixed).nup' if needed.")
    ap.add_argument("inputs", nargs="*",
                    help=".nsp files, prod.keys/title.keys, extracted game folders, "
                         "folders containing NSPs, or .nup files to repair")
    ap.add_argument("-o", "--out-dir", help="where to write .nup files (default: next to the input)")
    ap.add_argument("--tool", "--hactoolnet", dest="tool",
                    help="path to hactoolnet or hactool if it isn't next to this tool")
    ap.add_argument("--level", type=int, default=3, help="zstd level (default 3)")
    ap.add_argument("--keep-work", action="store_true", help="don't delete the temp folder")
    ap.add_argument("--no-save-keys", action="store_true",
                    help="don't copy dropped keys into the keys folder")
    args = ap.parse_args(argv)

    nsps, key_files, dumps, nups = collect_inputs(args.inputs)
    if not (nsps or dumps or nups):
        if key_files:
            try:
                resolve_keys(key_files, save=not args.no_save_keys)
            except ConvertError as e:
                log(f"ERROR: {e}")
                return 1
            log("Keys are set. Now drop your .nsp file(s) onto nsp2nup.")
            return 0
        ap.print_help()
        return 1
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
    if not have_zstd():
        log("! zstandard not found - the .nup will be uncompressed")

    made: list = []
    failed = 0
    if nsps:
        try:
            m, f = convert_nsps(nsps, key_files, args)
            made += m
            failed += f
        except ConvertError as e:
            log(f"ERROR: {e}")
            failed += 1
    for d in dumps:
        try:
            made.append((pack_dump(d, args.out_dir, args.level), []))
        except ConvertError as e:
            log(f"ERROR: {e}")
            failed += 1
    for n in nups:
        try:
            fixed = repair_nup(n, args.out_dir, args.level, args.keep_work)
            if fixed:
                made.append((fixed, []))
        except (ConvertError, F.NupError, OSError) as e:
            log(f"ERROR: {n}: {e}")
            failed += 1

    log("")
    for out, skipped in made:
        log(f"Done: {out}")
        if skipped:
            log(f"  WARNING: packed WITHOUT {', '.join(skipped)} (see errors above)")
    if failed:
        log(f"{failed} item(s) failed - see messages above.")
    partial = any(s for _, s in made)
    return 0 if (made or nups) and not failed and not partial else 1


if __name__ == "__main__":
    code = main()
    if FROZEN and os.name == "nt":  # keep the window open after a drag-and-drop
        input("\nPress Enter to close...")
    sys.exit(code)
