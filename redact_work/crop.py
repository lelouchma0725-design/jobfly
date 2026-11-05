import sys, os
from PIL import Image, ImageDraw

# usage: crop.py <img> <x> <y> <w> <h> <out> [scale] [grid]
img_path, x, y, w, h, out = sys.argv[1:7]
x, y, w, h = int(x), int(y), int(w), int(h)
scale = float(sys.argv[7]) if len(sys.argv) > 7 else 1.0
grid = int(sys.argv[8]) if len(sys.argv) > 8 else 0

im = Image.open(img_path).convert("RGB")
W, H = im.size
box = (max(0, x), max(0, y), min(W, x + w), min(H, y + h))
c = im.crop(box)
if scale != 1.0:
    c = c.resize((int(c.width * scale), int(c.height * scale)), Image.LANCZOS)
if grid:
    d = ImageDraw.Draw(c)
    for gx in range(0, c.width, grid):
        col = (255, 0, 0, 100) if (gx // grid) % 5 == 0 else (0, 160, 255)
        d.line([(gx, 0), (gx, c.height)], fill=col, width=1)
        if (gx // grid) % 5 == 0:
            d.text((gx + 2, 2), str(int(box[0] + gx / scale)), fill=(255, 0, 0))
    for gy in range(0, c.height, grid):
        col = (255, 0, 0) if (gy // grid) % 5 == 0 else (0, 160, 255)
        d.line([(0, gy), (c.width, gy)], fill=col, width=1)
        if (gy // grid) % 5 == 0:
            d.text((2, gy + 1), str(int(box[1] + gy / scale)), fill=(255, 0, 0))
c.save(out)
print(out, c.size, "src box", box)
