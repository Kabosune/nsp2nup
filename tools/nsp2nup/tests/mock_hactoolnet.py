#!/usr/bin/env python3
"""Fake hactoolnet: 'NCA' files are MOCKNCA + JSON. Checks keys/titlekeys/basenca usage."""
import base64, json, os, sys

args = sys.argv[1:]
opts, pos = {}, []
i = 0
while i < len(args):
    a = args[i]
    if a.startswith("-"):
        opts[a] = args[i + 1]; i += 2
    else:
        pos.append(a); i += 1
log = os.environ.get("MOCK_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps(args) + "\n")

assert opts.get("-t") == "nca", opts
keys = open(opts["-k"]).read()
if "header_key" not in keys:
    print("Missing header_key"); sys.exit(1)
nca = json.loads(open(pos[0], "rb").read()[8:])
if nca.get("rights_id"):
    tk = {}
    for ln in open(opts["--titlekeys"]):
        if "=" in ln:
            k, v = ln.split("=")
            tk[k.strip().lower()] = v.strip().lower()
    if tk.get(nca["rights_id"]) != nca["title_key"]:
        print(f"Missing title key for rights ID {nca['rights_id']}"); sys.exit(1)

def write(d, files):
    for rel, b64 in files.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(base64.b64decode(b64))

if nca.get("patch"):
    if "--basenca" not in opts:
        print("Patch NCA needs --basenca"); sys.exit(1)
    base = json.loads(open(opts["--basenca"], "rb").read()[8:])
    romfs = dict(base["romfs"]); romfs.update(nca["romfs"])
else:
    romfs = nca.get("romfs", {})
for flag, files in (("--exefsdir", nca.get("exefs", {})), ("--romfsdir", romfs),
                    ("--section0dir", nca.get("section0", {}))):
    if flag in opts and files:
        write(opts[flag], files)
print("ok")
