#! /usr/bin/env python
"""``oglc-character-sheet`` -- every clip a character model plays, as one picture.

A rigged character is a lot of things to look at: a dozen or more clips, each of
which reads differently from the front, from three-quarters, from the side and
from behind, and each of which is wrong in a way that only shows up at one
moment of the cycle. Opening a viewer and scrubbing finds one of those at a
time. A contact sheet puts all of them on the page at once, which is what makes
a bad silhouette, a foot through the floor or an arm through the ribs obvious.

One sheet per clip: a row for each view, a column for each moment of the clip::

    oglc-character-sheet marine.glb --out sheets/
    oglc-character-sheet marine.glb --out sheets/ --clips walk,run --phases 8
    oglc-character-sheet marine.glb --out sheets/ --hold grip=handgun.glb

``--hold`` puts a model on one of the character's attachment points, named as
the model names it, so a firing animation can be reviewed with the weapon in it
rather than with an empty hand.

An ``overview`` sheet comes with them: one row per clip, one column per view,
sampled a third of the way in, for the pass that asks "which of these is
wrong?" before the pass that asks "what is wrong with it?". An ``index.html``
comes with those, so the whole set can be read down one page instead of opened
one file at a time.

Everything is drawn through the ordinary PBR pass into a hidden window, so what
lands on the sheet is what a game gets.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.viewer.environment import apply_render_env, viewer_defaults

viewer_defaults()   # before anything that renders is imported

from OpenGLContext.capture import ensure_pillow, read_back_buffer  # noqa: E402
from OpenGLContext.character import CharacterModel  # noqa: E402
from OpenGLContext.viewer.options import ViewerOptions  # noqa: E402
from OpenGLContext.viewer.sceneviewer import ViewerContext  # noqa: E402

__all__ = ['VIEWS', 'CharacterSheet', 'main']

#: The four ways round a figure worth looking at, as a yaw in degrees and the
#: name of what it shows. Front is the way the model faces.
VIEWS: Tuple[Tuple[str, float], ...] = (
    ('front', 0.0),
    ('three-quarter', 40.0),
    ('side', 90.0),
    ('back', 180.0),
)

#: How big one cell is, and how much room the labels get.
CELL = (240, 340)
LABEL = 18
MARGIN = 8

#: What the figure stands against. A flat mid-dark ground rather than the sky
#: gradient, so a cell reads the same wherever the figure is in the frame.
BACKDROP = '0.15,0.16,0.19'


def _yaw(degrees: float) -> Tuple[float, float, float, float]:
    """A rotation about the vertical, as VRML97 states one."""
    return (0.0, 1.0, 0.0, np.radians(degrees))


class CharacterSheet:
    """What to draw: one model, its clips, its views and where they go."""

    def __init__(self, source: str, out: str, clips: Optional[Sequence[str]] = None,
                 phases: int = 6, views: Sequence[Tuple[str, float]] = VIEWS,
                 hold: Optional[Dict[str, str]] = None) -> None:
        self.source = source
        self.out = out
        self.wanted = list(clips) if clips else None
        self.phases = max(1, int(phases))
        self.views = list(views)
        self.hold = dict(hold or {})

    def phase(self, index: int) -> float:
        """Where in a clip the ``index``-th column is sampled, from 0 to 1.

        The last column is the clip's **end**, not the moment before it: what a
        one-shot has to be judged on is where it leaves the figure, and on a
        cycle the last column repeating the first is how a loop that does not
        close is spotted.
        """
        return index / max(self.phases - 1, 1)

    def clips_of(self, model: CharacterModel) -> List[str]:
        """The clips to draw, in the order asked for or the order they are in."""
        available = list(model.clips)
        if self.wanted is None:
            return available
        missing = [name for name in self.wanted if name not in available]
        if missing:
            raise SystemExit('%s has no clip named %s (it has: %s)'
                             % (os.path.basename(self.source), ', '.join(missing),
                                ', '.join(available) or 'none'))
        return list(self.wanted)

    def plan(self, model: CharacterModel) -> List[Tuple[str, float, float]]:
        """Every cell to draw, in the order they are drawn and tiled.

        The per-clip sheets first, then the overview's one row per clip, so the
        frames come back in the order the sheets want to read them.
        """
        clips = self.clips_of(model)
        cells = [(clip, self.phase(index), yaw)
                 for clip in clips
                 for _, yaw in self.views
                 for index in range(self.phases)]
        cells.extend((clip, 0.35, yaw) for clip in clips for _, yaw in self.views)
        return cells


class SheetContext(ViewerContext):
    """Draws each cell of the sheets in turn and writes them out.

    Built on the viewing component rather than beside it: the scene the sheet
    shows has to be lit, framed and shaded exactly as the viewer shows it, or
    the sheet is a picture of the tool instead of a picture of the model. What
    it adds is the pose and the turn per cell, and the tiling afterwards.

    One GL context and one loaded model for the whole run: a sheet is hundreds
    of frames, and reloading the character for each of them would be the whole
    cost of the tool.
    """

    #: Filled in by :func:`main` before the context is created.
    sheet: Any = None

    #: Frames drawn and thrown away before the first cell is kept. The adaptive
    #: analytic-sky lighting converges over several, and a sheet whose first
    #: cell is lit differently from the rest cannot be compared across.
    WARMUP = 8

    def OnInit(self) -> None:
        super(SheetContext, self).OnInit()
        self.model: Optional[CharacterModel] = None
        #: One entry per cell to draw: the clip, where in it, and the turn.
        self.plan: List[Tuple[str, float, float]] = []
        self.taken: List[np.ndarray] = []
        self.warmed = 0
        self.written: List[str] = []
        # A sheet is a picture of the model, so the viewer's own caption stays
        # off it.
        self.showCaption(False)

    def buildScenegraph(self, scene: Any) -> None:
        """Take the loaded scene as a character, then let the viewer frame it."""
        super(SheetContext, self).buildScenegraph(scene)
        self.model = CharacterModel.from_scene(scene)
        for point, path in self.sheet.hold.items():
            self._hold(point, path)
        self.plan = self.sheet.plan(self.model)

    def _hold(self, point: str, path: str) -> None:
        """Put a model on one of the character's attachment points."""
        from OpenGLContext.character.attachment import mounted
        from OpenGLContext.loaders.gltf import load_gltf
        # Through `mounted`, so a model that says where it is held is taken at
        # its word rather than hung on the rig by its own origin.
        held = mounted(load_gltf(path), point)
        if self.model is not None and self.model.attach(point, held) is None:
            sys.stderr.write('%s has no attachment point %r; %s is not shown\n'
                             % (os.path.basename(self.sheet.source), point,
                                os.path.basename(path)))

    # -- drawing ----------------------------------------------------------
    #
    # One cell per pass of the main loop, rather than a loop of its own calling
    # OnDraw: the frame a sheet shows has to be drawn the way every other frame
    # is drawn, through the pass the loop runs, or the sheet is a picture of
    # some other rendering path than the one a game uses.
    def pose(self, model: CharacterModel, clip: str, phase: float,
             yaw: float) -> None:
        """Put the model where the next cell wants it."""
        track = model.play(clip, loop=False, restart=True)
        track.time = phase * (track.duration or 0.0)
        model.mixer.apply()
        if self.modelTransform is not None:
            self.modelTransform.rotation = _yaw(yaw)

    def OnIdle(self, *arguments: Any) -> int:
        """Set up the next cell and ask for the frame that shows it."""
        result: int = super(SheetContext, self).OnIdle(*arguments)
        if self.model is None or self.written:
            return result
        if self.warmed >= self.WARMUP and len(self.taken) < len(self.plan):
            self.pose(self.model, *self.plan[len(self.taken)])
        self.triggerRedraw(1)
        return 1

    def SwapBuffers(self) -> Any:
        """Keep the frame just drawn, before it is swapped away."""
        if self.model is not None and not self.written:
            if self.warmed < self.WARMUP:
                self.warmed += 1
            elif len(self.taken) < len(self.plan):
                self.taken.append(read_back_buffer(0)[0])
                if len(self.taken) == len(self.plan):
                    try:
                        self.write()
                    finally:
                        self.OnQuit()
        return super(SheetContext, self).SwapBuffers()

    def write(self) -> None:
        """Tile everything drawn into the sheets and write them out."""
        sheet = self.sheet
        os.makedirs(sheet.out, exist_ok=True)
        base = os.path.splitext(os.path.basename(sheet.source))[0]
        cells = iter(self.taken)
        for clip in sheet.clips_of(self.model):
            rows = [(name, [next(cells) for _ in range(sheet.phases)])
                    for name, _ in sheet.views]
            path = os.path.join(sheet.out, '%s-%s.png' % (base, clip))
            _write(path, '%s -- %s' % (base, clip), rows,
                   ['%d%%' % round(100 * sheet.phase(index))
                    for index in range(sheet.phases)])
            self.written.append(path)
            sys.stdout.write('wrote %s\n' % path)
        overview = [(clip, [next(cells) for _ in sheet.views])
                    for clip in sheet.clips_of(self.model)]
        path = os.path.join(sheet.out, '%s-overview.png' % base)
        _write(path, '%s -- every clip, a third of the way in' % base, overview,
               [name for name, _ in sheet.views])
        self.written.insert(0, path)
        sys.stdout.write('wrote %s\n' % path)
        page = _index(sheet.out, base)
        sys.stdout.write('wrote %s\n' % page)


def _write(path: str, title: str, rows: Sequence[Tuple[str, Sequence[np.ndarray]]],
           columns: Sequence[str]) -> None:
    """Tile the cells into one labelled sheet."""
    image_module = ensure_pillow()
    if image_module is None:
        raise SystemExit('a contact sheet needs Pillow: pip install pillow')
    from PIL import ImageDraw, ImageFont
    font = ImageFont.load_default(size=13)
    cells: List[np.ndarray] = [cell for _, cells in rows for cell in cells]
    if not cells:
        raise SystemExit('nothing to draw')
    height, width = cells[0].shape[:2]
    gutter = 64
    sheet = image_module.new(
        'RGB',
        (gutter + len(columns) * (width + MARGIN) + MARGIN,
         LABEL * 2 + len(rows) * (height + LABEL + MARGIN) + MARGIN),
        (24, 25, 28))
    draw = ImageDraw.Draw(sheet)
    draw.text((MARGIN, MARGIN), title, fill=(235, 235, 240), font=font)
    for column, label in enumerate(columns):
        draw.text((gutter + column * (width + MARGIN), LABEL + MARGIN),
                  str(label), fill=(150, 152, 160), font=font)
    top = LABEL * 2 + MARGIN
    for name, row in rows:
        draw.text((MARGIN, top + height // 2), str(name), fill=(200, 202, 210),
                  font=font)
        for column, cell in enumerate(row):
            sheet.paste(image_module.fromarray(cell, 'RGB'),
                        (gutter + column * (width + MARGIN), top))
        top += height + LABEL + MARGIN
    sheet.save(path)


#: The page the sheets are read from. Deliberately one file with no assets of
#: its own: it is opened from a filesystem, mailed to somebody, or looked at
#: over a share, and a review page that needs a web server to work is a review
#: page nobody opens.
_INDEX = """<!doctype html>
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
<p>Each sheet is one clip: a row per view, a column per moment, the last column
   the clip's end.</p>
<nav>%(links)s</nav>
%(sheets)s
"""


def _index(out: str, base: str) -> str:
    """Write the page that shows every sheet in ``out``, and return its path.

    Every sheet in the directory, not only the run's own: a review usually
    wants both figures beside each other, and each run rewrites the page so it
    covers whatever is there by the time the last one finishes.
    """
    sheets: Dict[str, List[str]] = {}
    for name in sorted(os.listdir(out)):
        if name.endswith('.png'):
            sheets.setdefault(name.split('-', 1)[0], []).append(name)
    body, links = [], []
    for model in sorted(sheets):
        names = sorted(sheets[model],
                       key=lambda name: (not name.endswith('-overview.png'), name))
        links.append('<b>%s</b>' % model.replace('_', ' '))
        body.append('<h1>%s</h1>' % model.replace('_', ' '))
        for name in names:
            title = os.path.splitext(name)[0][len(model) + 1:]
            anchor = '%s-%s' % (model, title)
            links.append('<a href="#%s">%s</a>' % (anchor, title))
            body.append('<h2 id="%s">%s</h2>\n<img src="%s" alt="%s">'
                        % (anchor, title, name, title))
    path = os.path.join(out, 'index.html')
    with open(path, 'w') as page:
        page.write(_INDEX % {
            'title': '%s -- character sheets' % os.path.basename(
                os.path.abspath(out)),
            'links': ' '.join(links),
            'sheets': '\n'.join(body),
        })
    return path


def build_parser(prog: str = 'oglc-character-sheet') -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=__doc__.splitlines()[0])
    parser.add_argument('source', help='the character model (.glb / .gltf)')
    parser.add_argument('--out', default='character-sheets', metavar='DIR',
                        help='where the sheets go (default: character-sheets)')
    parser.add_argument('--clips', metavar='A,B',
                        help='only these clips, comma separated (default: all)')
    parser.add_argument('--phases', type=int, default=6, metavar='N',
                        help='moments sampled from each clip (default 6)')
    parser.add_argument('--size', default='%dx%d' % CELL, metavar='WxH',
                        help='one cell, in pixels (default %dx%d)' % CELL)
    parser.add_argument('--margin', type=float, default=0.78, metavar='FACTOR',
                        help='framing tightness; below 1 pulls the camera in')
    parser.add_argument('--background', default=BACKDROP, metavar='SPEC',
                        help='backdrop: sky, none, or an R,G,B triple')
    parser.add_argument('--hold', action='append', metavar='POINT=MODEL',
                        default=None,
                        help='mount a model on an attachment point (repeatable)')
    return parser


def main(argv: Optional[list] = None, prog: str = 'oglc-character-sheet') -> Any:
    options = build_parser(prog).parse_args(argv)
    width, _, height = options.size.partition('x')
    size = (int(width), int(height or width))
    hold = dict(item.split('=', 1) for item in (options.hold or []))
    SheetContext.sheet = CharacterSheet(
        options.source, options.out,
        clips=options.clips.split(',') if options.clips else None,
        phases=options.phases, hold=hold)
    viewing = ViewerOptions(
        source=options.source, size=size, background=options.background,
        margin=options.margin, yaw=0.0, no_cameras=True, no_rotate=True,
        # The mixer poses the model; the viewer's own single-clip player would
        # be a second thing writing the same joints.
        animate=False, physics=False, shadows=False)
    # Nobody watches a sheet being drawn, and a mapped surface is what makes a
    # read-back hang: a compositor throttles the swap to a frame callback that
    # a window nothing is showing never gets.
    os.environ.setdefault('OPENGLCONTEXT_HIDDEN', '1')
    os.environ.setdefault('OPENGLCONTEXT_NO_VSYNC', '1')
    os.environ.setdefault('OPENGLCONTEXT_DISABLE_FPS_DISPLAY', '1')
    # Several of the options above are read once by the passes at start-up
    # rather than per frame, and this is what puts them where those can see
    # them. Without it the sheet is drawn by a differently-configured renderer
    # from the viewer's.
    apply_render_env(viewing)
    SheetContext.options = viewing
    return SheetContext.ContextMainLoop(size=size)


if __name__ == '__main__':  # pragma: no cover - CLI entry point
    main()
