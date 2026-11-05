import sys
from docx import Document

path = sys.argv[1]
out = sys.argv[2]
d = Document(path)

lines = []
def walk_body(container, depth=0):
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.oxml.ns import qn
    for child in container.element.body.iterchildren() if hasattr(container, 'element') and hasattr(container.element, 'body') else container._tc.iterchildren():
        pass

# simpler: iterate blocks
from docx.table import Table
from docx.text.paragraph import Paragraph
def iter_block_items(parent):
    from docx.document import Document as _Doc
    if isinstance(parent, _Doc):
        parent_elm = parent.element.body
    else:
        parent_elm = parent._tc
    for child in parent_elm.iterchildren():
        if child.tag.endswith('}p'):
            yield Paragraph(child, parent)
        elif child.tag.endswith('}tbl'):
            yield Table(child, parent)

for block in iter_block_items(d):
    if isinstance(block, Paragraph):
        t = block.text.rstrip()
        style = block.style.name if block.style is not None else ''
        if t:
            lines.append(f"[{style}] {t}")
    else:
        lines.append("<<TABLE>>")
        for row in block.rows:
            cells = [c.text.replace("\n", " / ").strip() for c in row.cells]
            lines.append(" | ".join(cells))
        lines.append("<<END TABLE>>")

with open(out, 'w', encoding='utf-8') as f:
    f.write("\n".join(lines))
print(f"paragraphs+blocks: {len(lines)}")
