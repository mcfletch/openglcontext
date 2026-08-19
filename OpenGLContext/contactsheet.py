"""Tiling captured frames into a labelled sheet, and a page that shows them.

What a contact sheet is *for* is seeing a lot of frames at once: a dozen clips
from four sides, or one clip second by second. Whether the frames came from a
character's animation, a shader's parameter sweep or a level's cameras is not
this module's business -- it takes rows of images with names on them and lays
them out.

Two things come out of it: :func:`tile` writes one sheet, and :func:`index`
writes an ``index.html`` covering every sheet in a directory. The page is
deliberately one file with no assets of its own, because it is opened from a
filesystem, mailed to somebody or looked at over a share, and a review page
that needs a web server to work is a review page nobody opens.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from OpenGLContext.capture import ensure_pillow

__all__ = ['LABEL', 'MARGIN', 'GUTTER', 'tile', 'index']

#: How much room a row or column label gets, and the space between cells.
LABEL = 18
MARGIN = 8
#: How wide the left-hand column of row labels is.
GUTTER = 64

#: The page the sheets are read from.
PAGE = """<!doctype html>
<meta charset="utf-8">
<title>%(title)s</title>
<style>
 body { background:#17181b; color:#e6e7ea; margin:0 auto; padding:2rem;
        max-width:1500px; font:16px/1.5 system-ui, sans-serif; }
 h1 { font-size:1.4rem; font-weight:600; margin:2.5rem 0 .4rem; }
 p  { color:#a0a2aa; margin:0 0 2rem; }
 h2 { font-size:1.05rem; font-weight:600; margin:2.5rem 0 .6rem;
      color:#c9cbd2; border-bottom:1px solid #2c2e34; padding-bottom:.4rem; }
 img { width:100%%; height:auto; display:block; border-radius:4px; }
 nav { position:sticky; top:0; background:#17181b; padding:.6rem 0 1rem;
       border-bottom:1px solid #2c2e34; margin-bottom:1rem; }
 nav a { color:#8fb8ff; text-decoration:none; margin-right:1rem;
         font-size:.9rem; white-space:nowrap; }
 nav a:hover { text-decoration:underline; }
</style>
<p>%(caption)s</p>
<nav>%(links)s</nav>
%(sheets)s
"""


def tile(path: str, title: str,
         rows: Sequence[Tuple[str, Sequence[Any]]],
         columns: Sequence[str]) -> str:
    """Lay ``rows`` of captured frames out into one labelled sheet.

    Each row is ``(label, frames)`` and every frame is an ``(h, w, 3)`` array
    of bytes, as :func:`OpenGLContext.capture.read_back_buffer` answers.
    ``columns`` labels them along the top. Returns the path written.
    """
    image_module = ensure_pillow()
    if image_module is None:
        raise SystemExit('a contact sheet needs Pillow: pip install pillow')
    from PIL import ImageDraw, ImageFont
    font = ImageFont.load_default(size=13)
    cells = [cell for _, frames in rows for cell in frames]
    if not cells:
        raise SystemExit('nothing to draw')
    height, width = cells[0].shape[:2]
    sheet = image_module.new(
        'RGB',
        (GUTTER + len(columns) * (width + MARGIN) + MARGIN,
         LABEL * 2 + len(rows) * (height + LABEL + MARGIN) + MARGIN),
        (24, 25, 28))
    draw = ImageDraw.Draw(sheet)
    draw.text((MARGIN, MARGIN), title, fill=(235, 235, 240), font=font)
    for column, label in enumerate(columns):
        draw.text((GUTTER + column * (width + MARGIN), LABEL + MARGIN),
                  str(label), fill=(150, 152, 160), font=font)
    top = LABEL * 2 + MARGIN
    for name, frames in rows:
        draw.text((MARGIN, top + height // 2), str(name), fill=(200, 202, 210),
                  font=font)
        for column, cell in enumerate(frames):
            sheet.paste(image_module.fromarray(cell, 'RGB'),
                        (GUTTER + column * (width + MARGIN), top))
        top += height + LABEL + MARGIN
    sheet.save(path)
    return path


def index(out: str, caption: str = '', title: Optional[str] = None,
          order: Sequence[str] = ()) -> str:
    """Write the page showing every sheet in ``out``, and return its path.

    Every sheet in the directory, not only the ones a run just wrote: a review
    usually wants two models beside each other, and each run rewrites the page
    so it covers whatever is there by the time the last one finishes.

    Sheets are grouped by the part of their name before the first ``-``.
    ``order`` names the ones that come first within a group, which is how a
    run puts its overview at the top.
    """
    groups: Dict[str, List[str]] = {}
    for name in sorted(os.listdir(out)):
        if name.endswith('.png'):
            groups.setdefault(name.split('-', 1)[0], []).append(name)
    ranked = {name: position for position, name in enumerate(order)}
    body, links = [], []
    for group in sorted(groups):
        names = sorted(groups[group], key=lambda name: (
            ranked.get(os.path.splitext(name)[0][len(group) + 1:], len(ranked)),
            name))
        links.append('<b>%s</b>' % group.replace('_', ' '))
        body.append('<h1>%s</h1>' % group.replace('_', ' '))
        for name in names:
            label = os.path.splitext(name)[0][len(group) + 1:]
            anchor = '%s-%s' % (group, label)
            links.append('<a href="#%s">%s</a>' % (anchor, label))
            body.append('<h2 id="%s">%s</h2>\n<img src="%s" alt="%s">'
                        % (anchor, label, name, label))
    path = os.path.join(out, 'index.html')
    with open(path, 'w') as page:
        page.write(PAGE % {
            'title': title or os.path.basename(os.path.abspath(out)),
            'caption': caption,
            'links': ' '.join(links),
            'sheets': '\n'.join(body),
        })
    return path
