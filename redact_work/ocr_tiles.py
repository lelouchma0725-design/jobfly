import subprocess, sys, os
from PIL import Image

# usage: ocr_tiles.py <image> <tile_h> <out.tsv> [scale]
img_path = sys.argv[1]
tile_h = int(sys.argv[2])
out = sys.argv[3]
scale = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0

im = Image.open(img_path).convert("RGB")
W, H = im.size
tmpdir = "/tmp/ocrtiles_" + os.path.basename(img_path).split(".")[0]
import shutil
shutil.rmtree(tmpdir, ignore_errors=True)
os.makedirs(tmpdir, exist_ok=True)
rows = []
y = 0
while y < H:
    h = min(tile_h, H - y)
    t = im.crop((0, y, W, y + h))
    if scale != 1.0:
        t = t.resize((int(W * scale), int(h * scale)), Image.LANCZOS)
    p = f"{tmpdir}/tile_{y}.png"
    t.save(p)
    r = subprocess.run(["./ocrbin", p], capture_output=True, text=True)
    inv = 1.0 / scale
    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        x, yy, w, hh, conf, text = parts[0], parts[1], parts[2], parts[3], parts[4], "\t".join(parts[5:])
        X = int(int(x) * inv)
        Y = int(y + int(yy) * inv)
        Wd = int(int(w) * inv)
        Hd = int(int(hh) * inv)
        rows.append(f"{X}\t{Y}\t{Wd}\t{Hd}\t{conf}\t{text}")
    y += tile_h

with open(out, "w") as f:
    f.write("\n".join(rows))
print(out, len(rows), "lines")
