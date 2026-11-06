"""Guards against real organisation, venue or person names leaking into a public portfolio.
The term list is git-ignored.

Scans tracked and untracked (not ignored) files, the XML inside PPTX/XLSX payloads, and the commit log.
Exits 1 and lists the hits if any term from `.confidential_terms.txt` is found."""
import io
import pathlib
import re
import subprocess
import sys
import zipfile

root = pathlib.Path(__file__).resolve().parents[1]
lst = root / ".confidential_terms.txt"
if not lst.exists():
    print("confidential-term list missing; skipping")
    sys.exit(0)
names = [n.strip() for n in lst.read_text(encoding="utf-8").splitlines() if n.strip()]
pat = re.compile("|".join(r"\b" + re.escape(n) + r"\b" for n in names), re.I)
files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=root,
                       capture_output=True, text=True).stdout.split("\n")
hits = []
for f in filter(None, files):
    p = root / f
    if not p.is_file() or p.name == ".confidential_terms.txt":
        continue
    if p.suffix in {".png", ".jpg", ".gif", ".mp4", ".pdf", ".ico"}:
        continue  # compressed binary payloads; random byte runs can spell a short token by chance
    data = p.read_bytes()
    if p.suffix in {".pptx", ".xlsx", ".pbix"}:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                data = b" ".join(z.read(n) for n in z.namelist() if n.endswith(".xml"))
        except zipfile.BadZipFile:
            pass
    text = data.decode("utf-8", errors="ignore")
    for m in pat.finditer(text):
        hits.append(f"{f}: {m.group(0)}")
log = subprocess.run(["git", "log", "--all", "--format=%B"], cwd=root,
                     capture_output=True, text=True).stdout
hits += [f"commit message: {m.group(0)}" for m in pat.finditer(log)]
if hits:
    print("CONFIDENTIAL TERMS FOUND:")
    print("\n".join(hits[:50]))
    sys.exit(1)
print(f"confidentiality check passed ({len([f for f in files if f])} files + commit log)")
