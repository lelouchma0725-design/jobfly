import subprocess, sys, os, shutil, json, glob

# search_pii.py: find precise boxes of search terms across tiles of one image
img_path = sys.argv[1]
terms = json.loads(sys.argv[2])
tile_h, step = 850, 700

tmpdir = "/tmp/pii_" + os.path.basename(img_path).split(".")[0]
shutil.rmtree(tmpdir, ignore_errors=True)
os.makedirs(tmpdir, exist_ok=True)

from PIL import Image
im = Image.open(img_path).convert("RGB")
W, H = im.size

boxes = []  # (x,y,w,h,term,conf,ctx)
ys = list(range(0, max(1, H - 1), step))
for y in ys:
    h = min(tile_h, H - y)
    t = im.crop((0, y, W, y + h))
    p = f"{tmpdir}/t_{y}.png"
    t.save(p)
    for term in terms:
        r = subprocess.run(["./ocrbin", p, "zh-Hans,en-US", "--search", term],
                           capture_output=True, text=True)
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 6:
                continue
            x, yy, w, hh = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            conf = parts[4]
            ctx = parts[6] if len(parts) > 6 else ""
            boxes.append((x, y + yy, w, hh, term, conf, ctx))

# dedupe by overlap
def inter(a, b):
    ax, ay, aw, ah = a[:4]
    bx, by, bw, bh = b[:4]
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    i = (x2 - x1) * (y2 - y1)
    return i / float(min(aw * ah, bw * bh))

merged = []
for b in boxes:
    dup = False
    for i, m in enumerate(merged):
        if inter(b, m) > 0.5:
            # keep larger extent
            x = min(b[0], m[0]); y = min(b[1], m[1])
            w = max(b[0] + b[2], m[0] + m[2]) - x
            h = max(b[1] + b[3], m[1] + m[3]) - y
            merged[i] = (x, y, w, h, m[4], max(float(b[5]), float(m[5])), m[6])
            dup = True
            break
    if not dup:
        merged.append(b)

for b in sorted(merged, key=lambda t: (t[1], t[0])):
    print(f"{b[0]}\t{b[1]}\t{b[2]}\t{b[3]}\t{b[4]}\t{b[5]}\t{b[6]}")
