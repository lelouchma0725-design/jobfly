import json, os, sys
from PIL import Image

# redact.py: mosaic all PII boxes listed in spec.json -> redacted/<same name>.png
spec = json.load(open("spec.json"))
os.makedirs("redacted", exist_ok=True)
for name, boxes in spec.items():
    im = Image.open(os.path.join("extracted/word/media", name)).convert("RGB")
    for (x, y, w, h) in boxes:
        x, y, w, h = int(x), int(y), int(w), int(h)
        if w <= 0 or h <= 0:
            continue
        box = (x, y, x + w, y + h)
        reg = im.crop(box)
        b = max(10, int(h * 0.75))
        sw = max(1, reg.width // b)
        sh = max(1, reg.height // b)
        blk = reg.resize((sw, sh), Image.BOX).resize((reg.width, reg.height), Image.NEAREST)
        blk = Image.blend(blk, Image.new("RGB", blk.size, (120, 120, 120)), 0.25)
        im.paste(blk, box)
    im.save(os.path.join("redacted", name))
    print("redacted", name, len(boxes), "boxes")
