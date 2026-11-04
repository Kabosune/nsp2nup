#!/usr/bin/env python3
"""Fake hactool: --opt=val style, single --titlekey. Missing key -> WARN + garbage + exit 0 (like real hactool)."""
import base64, json, os, sys
args = sys.argv[1:]; opts = {}; pos = []; i = 0
while i < len(args):
    a = args[i]
    if a in ("-x", "-i"):
        opts[a] = True; i += 1; continue
    if a in ("-k", "-t"):
        opts[a] = args[i + 1]; i += 2; continue
    if a.startswith("--"):
        k, _, v = a.partition("="); opts[k] = v
    else:
        pos.append(a)
    i += 1
log = os.environ.get("MOCK_LOG")
if log:
    open(log, "a").write(json.dumps(args) + "\n")
assert opts.get("-t") == "nca" and "--disablekeywarns" in opts and "--titlekeys" not in opts, opts
if "header_key" not in open(opts["-k"]).read():
    print("Invalid NCA header! Are keys correct?"); sys.exit(0)
if os.environ.get("MOCK_CRASH") and "-x" not in opts:
    print("        Signature Key:              0"); sys.exit(5)  # crashes only while printing info
nca = json.loads(open(pos[0], "rb").read()[8:])
garbage = False
if nca.get("rights_id") and opts.get("--titlekey") != nca["title_key"]:
    print("[WARN] Unable to match rights id to titlekey. Update title.keys?"); garbage = True
def write(d, files):
    if not os.path.isdir(os.path.dirname(os.path.normpath(d))):
        for rel in files: print(f"Failed to open {os.path.join(d, rel)}!")
        return
    os.makedirs(d, exist_ok=True)  # real hactool: creates only the last level
    for rel, b in files.items():
        p = os.path.join(d, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(os.urandom(16) if garbage else base64.b64decode(b))
if nca.get("patch"):
    if not opts.get("--basenca"):
        print("Error: no base"); sys.exit(1)
    base = json.loads(open(opts["--basenca"], "rb").read()[8:])
    romfs = dict(base["romfs"]); romfs.update(nca["romfs"])
else:
    romfs = nca.get("romfs", {})
for flag, files in (("--exefsdir", nca.get("exefs", {})), ("--romfsdir", romfs), ("--section0dir", nca.get("section0", {}))):
    if opts.get(flag) and files:
        write(opts[flag], files)
