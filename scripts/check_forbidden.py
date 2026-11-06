"""Fail if any forbidden name (from the git-ignored .forbidden_names.txt) appears in
tracked/untracked files, inside Office/zip payloads, or in the commit log."""
import io
import pathlib
import re
import subprocess
import sys
import zipfile

root = pathlib.Path(__file__).resolve().parents[1]
lst = root / ".forbidden_names.txt"
if not lst.exists():
    print("forbidden-name list missing; skipping")
    sys.exit(0)
names = [n.strip() for n in lst.read_text(encoding="utf-8").splitlines() if n.strip()]
pat = re.compile("|".join(r"\b" + re.escape(n) + r"\b" for n in names), re.I)
files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=root,
                       capture_output=True, text=True).stdout.split("\n")
hits = []
for f in filter(None, files):
    p = root / f
    if not p.is_file() or p.name == ".forbidden_names.txt":
        continue
    if p.suffix in {".png", ".jpg", ".pdf", ".ico"}:
        continue  # compressed binary payloads; random byte runs can spell a short token by chance
    data = p.read_bytes()
    if p.suffix in {".pptx", ".xlsx"}:
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
    print("FORBIDDEN NAMES FOUND:")
    print("\n".join(hits[:50]))
    sys.exit(1)
print(f"forbidden-name check passed ({len([f for f in files if f])} files + commit log)")
