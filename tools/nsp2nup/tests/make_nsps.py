#!/usr/bin/env python3
"""Build synthetic base/update/DLC NSPs with real PFS0, ticket, CNMT and NACP layouts."""
import base64, hashlib, json, os, struct, sys

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
APP = 0x0100ABCD00010000
UPD = APP | 0x800
DLC = 0x0100ABCD00011001

b64 = lambda b: base64.b64encode(b).decode()

def pfs0(files):
    names = b""; offs = []; data = b""; ents = b""
    for name, blob in files:
        offs.append((len(data), len(blob), len(names)))
        names += name.encode() + b"\0"; data += blob
    names += b"\0" * ((-len(names)) % 0x20)
    for (o, s, n) in offs:
        ents += struct.pack("<QQII", o, s, n, 0)
    return b"PFS0" + struct.pack("<III", len(files), len(names), 0) + ents + names + data

def nca(d):
    return b"MOCKNCA\n" + json.dumps(d).encode()

def nid(tag):
    return hashlib.md5(tag.encode()).hexdigest()

def ticket(rights, key):
    t = bytearray(0x2C0)
    struct.pack_into("<I", t, 0, 0x010004)
    body = 0x140
    t[body + 0x40: body + 0x50] = bytes.fromhex(key)
    t[body + 0x141] = 0
    t[body + 0x160: body + 0x170] = bytes.fromhex(rights)
    return bytes(t)

def cnmt(tid, ver, mtype, app_id, contents):
    ext = struct.pack("<QI4x", app_id, 0) if mtype != 0x80 else struct.pack("<QI4x", tid | 0x800, 0)
    h = struct.pack("<QIBBHHH", tid, ver, mtype, 0, len(ext), len(contents), 0) + b"\0" * 0xC
    assert len(h) == 0x20
    body = b""
    for cid, ctype, idoff in contents:
        body += b"\0" * 0x20 + bytes.fromhex(cid) + (1234).to_bytes(6, "little") + bytes([ctype, idoff])
    return h + ext + body

def nacp(name, pub, disp, ja=None):
    n = bytearray(0x4000)
    for i in range(16):
        nm = (ja if (i == 2 and ja) else name).encode()
        n[i * 0x300: i * 0x300 + len(nm)] = nm
        n[i * 0x300 + 0x200: i * 0x300 + 0x200 + len(pub)] = pub.encode()
    n[0x3060:0x3060 + len(disp)] = disp.encode()
    return bytes(n)

npdm = b"META" + b"\0" * 0x6C + b"ACI0" + b"\0" * 0xC + struct.pack("<Q", APP) + b"\0" * 0x40
main_nso = b"NSO0" + b"\0" * 0x3C + bytes(range(32)) + b"\0" * 0x40
icon_en = b"\xff\xd8" + b"EN-ICON" * 50
icon_ja = b"\xff\xd8" + b"JA-ICON" * 50

def build(nspname, tid, ver, mtype, app_id, parts, rights=None, key=None):
    files, contents = [], []
    for ctype, payload in parts:
        cid = nid(f"{tid}-{ctype}-{ver}")
        if rights:
            payload = dict(payload, rights_id=rights, title_key=key)
        files.append((cid + ".nca", nca(payload)))
        contents.append((cid, ctype, 0))
    meta_id = nid(f"{tid}-meta-{ver}")
    cn = cnmt(tid, ver, mtype, app_id, contents + [(meta_id, 0, 0)])
    kind = {0x80: "Application", 0x81: "Patch", 0x82: "AddOnContent"}[mtype]
    files.append((meta_id + ".cnmt.nca",
                  nca({"section0": {f"{kind}_{tid:016x}.cnmt": b64(cn)}})))
    if rights:
        files.append((rights + ".tik", ticket(rights, key)))
        files.append((rights + ".cert", b"\0" * 0x700))
    open(os.path.join(out, nspname), "wb").write(pfs0(files))

build("Mock Game [base].nsp", APP, 0, 0x80, APP, [
    (1, {"exefs": {"main.npdm": b64(npdm), "main": b64(main_nso), "rtld": b64(b"rtld")},
         "romfs": {"data/a.bin": b64(b"A" * 5000), "data/b.bin": b64(b"base-b"), "x.txt": b64(b"hi")}}),
    (3, {"romfs": {"control.nacp": b64(nacp("Mock Game", "Mock Co", "1.0.0", ja="モックゲーム")),
                   "icon_AmericanEnglish.dat": b64(icon_en), "icon_BritishEnglish.dat": b64(icon_en),
                   "icon_Japanese.dat": b64(icon_ja)}}),
], rights="0100abcd000100000000000000000005", key="11" * 16)

build("Mock Game [upd v65536].nsp", UPD, 65536, 0x81, APP, [
    (1, {"patch": True, "exefs": {"main.npdm": b64(npdm), "main": b64(main_nso[:0x40] + bytes(32) + b"\0" * 0x40)},
         "romfs": {"data/b.bin": b64(b"patched-b"), "data/new.bin": b64(b"new")}}),
    (3, {"romfs": {"control.nacp": b64(nacp("Mock Game", "Mock Co", "1.1.0"))}}),
], rights="0100abcd000108000000000000000005", key="22" * 16)

build("Mock Game [dlc].nsp", DLC, 0, 0x82, APP, [
    (2, {"romfs": {"dlc/stage.bin": b64(b"D" * 3000)}}),
], rights="0100abcd000110010000000000000005", key="33" * 16)
print("made", os.listdir(out))
