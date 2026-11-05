import json, os, sys

# build_spec.py: combine auto OCR boxes with manual boxes into spec.json
auto_dir = "pii"
media = "extracted/word/media"

MANUAL = {
    # avatar circles + name (the "马" avatar card at top-left)
    "image5.png": [[45, 143, 52, 48]],
    "image6.png": [[45, 143, 52, 48], [594, 6196, 26, 26], [594, 1950, 30, 24], [299, 1240, 88, 26]],
    "image7.png": [[45, 143, 52, 48]],
    "image8.png": [[45, 143, 52, 48]],
    "image9.png": [[45, 143, 52, 48]],
    "image10.png": [[45, 143, 52, 48]],
    "image11.png": [[45, 143, 52, 48]],
    "image12.png": [[45, 143, 52, 48]],
    "image13.png": [[45, 143, 52, 48]],
    "image14.png": [[45, 143, 52, 48]],
}

MANUAL_ONLY = {"image13.png": [[1241, 42, 55, 33], [45, 143, 103, 48], [826, 833, 190, 60], [826, 1556, 190, 60]]}
PAD_X, PAD_Y = 5, 3

spec = {}
for i in range(1, 18):
    name = f"image{i}.png"
    boxes = []
    p = os.path.join(auto_dir, f"i{i}.tsv")
    if os.path.exists(p):
        for line in open(p):
            f = line.rstrip("\n").split("\t")
            if len(f) < 6:
                continue
            x, y, w, h = map(int, f[:4])
            term = f[4]
            boxes.append([max(0, x - PAD_X), max(0, y - PAD_Y), w + 2 * PAD_X, h + 2 * PAD_Y])
    for m in MANUAL.get(name, []):
        boxes.append(m)
    if name in MANUAL_ONLY:
        boxes = [list(b) for b in MANUAL_ONLY[name]]
    # merge overlapping/adjacent boxes
    changed = True
    while changed:
        changed = False
        out = []
        for b in boxes:
            placed = False
            for i2, o in enumerate(out):
                ax, ay, aw, ah = b
                bx, by, bw, bh = o
                if ax < bx + bw - 1 and bx < ax + aw - 1 and ay < by + bh - 1 and by < ay + ah - 1:
                    nx, ny = min(ax, bx), min(ay, by)
                    out[i2] = [nx, ny, max(ax + aw, bx + bw) - nx, max(ay + ah, by + bh) - ny]
                    placed = True
                    changed = True
                    break
            if not placed:
                out.append(b)
        boxes = out
    if boxes:
        spec[name] = sorted(boxes, key=lambda b: (b[1], b[0]))

json.dump(spec, open("spec.json", "w"), indent=1)
for k, v in spec.items():
    print(k, len(v), v[:4])
