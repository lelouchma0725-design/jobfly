import zipfile, shutil, os, sys

src = "source.docx"
out = sys.argv[1] if len(sys.argv) > 1 else "out.docx"
redir = "extracted/word/media"

with zipfile.ZipFile(src) as zin:
    names = zin.namelist()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            data = zin.read(n)
            if n.startswith("word/media/") and os.path.exists(os.path.join(redir, os.path.basename(n))):
                data = open(os.path.join(redir, os.path.basename(n)), "rb").read()
            zi = zipfile.ZipInfo(n, date_time=zin.getinfo(n).date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = zin.getinfo(n).external_attr
            zout.writestr(zi, data)
print("wrote", out, os.path.getsize(out), "bytes")
