"""The code-walkthrough tutorials, written from the scripts in ``tests/``.

Each tutorial is a runnable script whose commentary sits in ``'''`` strings
between the statements, so the page and the program that page describes are
the same file and cannot drift apart.  This reads those scripts, turns each
into a page of commentary and code, and writes an index of the paths through
them.

    python -m docbuild.tutorials --output docs/tutorials

The paths -- which scripts, in which order, under which heading -- are
:data:`PATHS`.  A script not named there is not a tutorial, whatever it holds.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import re
import sys
from typing import Iterable

from docbuild import markup

__all__ = ['Tutorial', 'TutorialPath', 'PATHS', 'parse', 'render', 'write']

log = logging.getLogger('tutorials')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Where the scripts are.
TESTS = os.path.join(HERE, 'tests')

#: Where the pages go.
OUTPUT = os.path.join(HERE, 'docs', 'tutorials')

#: A ``'''`` string on lines of its own is commentary.  A ``\"\"\"`` string is
#: the docstring of whatever the tutorial is building and is left in the code.
COMMENTARY = re.compile(
    r"""^[ \t]*?(''')(?P<commentary>.*?)(''')[ \t]*?$""",
    re.MULTILINE | re.DOTALL,
)

#: The first line of a code piece, marking it as boilerplate the reader can
#: skip: it is written into the page with a scrollbar rather than in full.
COLLAPSE = '#collapse'

UNDERLINES = '=-~^"'


@dataclasses.dataclass
class Piece:
    """One piece of a tutorial: commentary, or the code it describes."""

    kind: str  # 'commentary' | 'code' | 'collapsed'
    text: str


@dataclasses.dataclass
class Tutorial:
    """One script, as the page it becomes."""

    name: str
    source: str
    pieces: list[Piece]

    @property
    def title(self) -> str:
        for piece in self.pieces:
            if piece.kind != 'commentary':
                continue
            for block in markup.commentary(piece.text):
                if block.kind == 'title':
                    return block.text
        return self.name


@dataclasses.dataclass
class TutorialPath:
    """Tutorials on one subject, ordered from the least assumed."""

    title: str
    description: str
    scripts: list[str]
    #: Pages of ``docs/tutorials`` written by hand rather than from a script,
    #: listed at the head of this path.
    pages: list[str] = dataclasses.field(default_factory=list)


PATHS = [
    TutorialPath(
        'Using the Engine',
        """How to get something on screen and make it move: loading a model in
        each of the three formats, animating it, playing the clips a rigged
        model was authored with, and walking a character along a route.""",
        [
            'using_gltf_model',
            'using_vrml97',
            'using_obj',
            'using_animation',
            'using_clips',
            'crowd_demo',
            'using_npc',
            'navmesh_demo',
        ],
    ),
    TutorialPath(
        'Physics',
        """Rigid bodies, the materials they are made of, the joints that hold
        them together, and what a game does with what the solver reports.""",
        pages=['physics_getting_started'],
        scripts=[
            'physics_room_drop',
            'physics_bounce',
            'physics_friction',
            'using_collisions',
            'physics_triggers',
            'physics_events',
            'physics_joints',
            'physics_gravity_zones',
            'physics_cook_view',
            'physics_navigate',
            'physics_stress',
        ],
    ),
    TutorialPath(
        'Interface and Tools',
        """What the player reads and what an author edits: panels and screen
        furniture over the frame, a settings page, a console, choosing a level
        by its picture, picking something in the world to drag, and an
        editor's four views of a model.""",
        [
            'using_ui',
            'hud_demo',
            'using_settings',
            'using_console',
            'using_level_select',
            'using_selection',
            'editing_demo',
            'multiview_quad',
        ],
    ),
    TutorialPath(
        'Building a World',
        """The scenery nodes and the tools around them: water, roads, audio,
        particles, instanced batching, writing a scene out as glTF, and
        recording a session or a video of one.""",
        [
            'water_demo',
            'roads_demo',
            'particles_effects',
            'audio_spatial',
            'instancing_batched',
            'bake_demo',
            'recording_demo',
            'telemetry_demo',
        ],
    ),
    TutorialPath(
        'Swept Geometry and Tessellation',
        """Geometry generated from an outline: tubes and lathes swept along a
        curve, the joins and normals that decide how they look, turning a
        polygon into the triangles that draw it, and the glyphs of a font as
        solid text.""",
        [
            'solid_font',
            'extrusions_shapes',
            'extrusions_curves',
            'extrusions_joins',
            'extrusions_normals',
            'extrusions_gallery',
            'extrusions_tessellation',
            'extrusions_preprocessing',
            'extrusions_vrml97',
            'glelathe',
        ],
    ),
    TutorialPath(
        'Introduction to Shaders (Lighting)',
        """A low-level introductory path, for a reader who has either never
        done 3D graphics with OpenGL or has only done fixed-function
        rendering.  It works through Blinn-Phong rendering of directional,
        point and spot lights, and the basics of geometric rendering with
        vertex buffer objects.""",
        [
            'shader_intro',
            'shader_1',
            'shader_2',
            'shader_3',
            'shader_4',
            'shader_5',
            'shader_6',
            'shader_7',
            'shader_8',
            'shader_9',
            'shader_10',
            'shader_11',
            'shader_12',
            'shader_instanced',
        ],
    ),
    TutorialPath(
        'Transformations and Matrices',
        """The matrices that map geometry into the cube the hardware draws,
        how to calculate them on the CPU, and how to hand them to a shader.""",
        ['transforms_1'],
    ),
    TutorialPath(
        'Scenegraph Nodes',
        """A high-level path, introducing the OpenGLContext/VRML97 scenegraph.
        It covers more involved rendering tasks in less detail than the shader
        path: what to build rather than how the effect is achieved.""",
        [
            'lightobject',
            'molehill',
            'molehill_edit',
            'nurbsobject',
            'particles_simple',
        ],
    ),
    TutorialPath(
        'Depth-map Shadows',
        """Setting up shadow-map-based shadow casting.  These assume a reader
        comfortable with OpenGL; the last builds the same scene out of
        scenegraph nodes and lets OpenGLContext's own shadow pass light it.""",
        ['shadow_1', 'shadow_2', 'shadow_3'],
    ),
    TutorialPath(
        'NeHe Translations',
        """Translations of the NeHe series of tutorials.  These are low-level
        introductory tutorials using the legacy OpenGL API; the originals they
        are translated from are gentle and thorough.""",
        [
            'nehe1',
            'nehe2',
            'nehe3',
            'nehe4',
            'nehe5',
            'nehe6',
            'nehe7',
            'nehe8',
            'nehe6_timer',
            'nehe6_multi',
            'nehe6_compressed',
            'glprint',
        ],
    ),
]

#: Pages in ``docs/tutorials`` that are written by hand rather than from a
#: script, and so are listed in the index without being generated.
HAND_WRITTEN = [('physics_getting_started', 'Adding physics to a scene')]


# --------------------------------------------------------------------------- #
# Reading a script
# --------------------------------------------------------------------------- #
def parse(path: str) -> Tutorial:
    """One script, split into its commentary and the code between it."""
    with open(path, encoding='utf8') as handle:
        text = handle.read().replace('\r\n', '\n')
    pieces: list[Piece] = []
    position = 0
    for match in COMMENTARY.finditer(text):
        _code(pieces, text[position : match.start()])
        if match.group('commentary').strip():
            pieces.append(Piece('commentary', match.group('commentary')))
        position = match.end()
    _code(pieces, text[position:])
    return Tutorial(
        name=os.path.splitext(os.path.basename(path))[0], source=path, pieces=pieces
    )


def _code(pieces: list[Piece], text: str) -> None:
    if not text.strip():
        return
    lines = text.strip('\n').splitlines()
    if lines[0].lstrip().startswith(COLLAPSE):
        pieces.append(Piece('collapsed', '\n'.join(lines[1:])))
    else:
        pieces.append(Piece('code', '\n'.join(lines)))


# --------------------------------------------------------------------------- #
# Writing a page
# --------------------------------------------------------------------------- #
def heading(text: str, level: int) -> str:
    return '%s\n%s' % (text, UNDERLINES[level] * max(len(text), 3))


def indent(text: str, prefix: str = '   ') -> str:
    return '\n'.join(prefix + line if line.strip() else '' for line in text.split('\n'))


def render(tutorial: Tutorial) -> str:
    """The page for one tutorial."""
    out: list[str] = [
        '.. _tutorial-%s:' % (tutorial.name,),
        heading(markup.escape(tutorial.title), 0),
    ]
    titled = False
    started = False
    for piece in tutorial.pieces:
        if piece.kind == 'commentary':
            for block in markup.commentary(piece.text):
                if block.kind == 'title' and not titled:
                    titled = True
                    continue
                if block.kind in ('title', 'subtitle'):
                    out.append(heading(markup.escape(block.text), 1))
                else:
                    out.append(block.text)
                started = True
            continue
        depth, code = _dedent(piece.text)
        if not started and _only_comments(code):
            # The shebang and the licence header at the top of the script are
            # not part of what the tutorial is teaching.
            continue
        started = True
        options = ''
        if piece.kind == 'collapsed':
            options += '   :class: collapsed-code\n'
        if depth:
            options += '   :indent: %d\n' % (depth,)
        out.append('.. tutorial-code:: python\n%s\n%s' % (options, indent(code)))
    out.append(
        '.. rst-class:: source-reference\n\n'
        'This walkthrough is written from ``tests/%s.py`` in the OpenGLContext '
        'source, which runs as it stands.' % (tutorial.name,)
    )
    return '\n\n'.join(block for block in out if block.strip()).rstrip() + '\n'


def _only_comments(text: str) -> bool:
    """Whether a piece of code is nothing but comments and blank lines."""
    return all(
        not line.strip() or line.lstrip().startswith('#') for line in text.splitlines()
    )


def _dedent(text: str) -> tuple[int, str]:
    """The indent common to a code piece, in columns, and the piece without it.

    A piece cut from inside a class body carries that body's indent.  reST
    takes the indent common to a directive's content off in any case, so the
    page states it as the ``tutorial-code`` directive's ``:indent:`` option,
    which puts it back (``docs/_ext/oglc_tutorials.py``).
    """
    lines = [_expand_indent(line) for line in text.strip('\n').split('\n')]
    depth = min(
        (len(line) - len(line.lstrip(' ')) for line in lines if line.strip()),
        default=0,
    )
    return depth, '\n'.join(line[depth:].rstrip() for line in lines)


def _expand_indent(line: str) -> str:
    """``line`` with the tabs in its indent as the columns Python reads them as."""
    body = line.lstrip()
    return line[: len(line) - len(body)].expandtabs(8) + body


def render_index(paths: Iterable[TutorialPath], written: Iterable[str]) -> str:
    """The page listing the paths, and the toctree that carries them."""
    written = set(written)
    out = [
        heading('OpenGLContext Tutorials', 0),
        markup.wrap(
            'Each of these is a runnable script in the OpenGLContext source, '
            'with the commentary written into the script beside the code it '
            'describes.  The headings below group them by subject; a group '
            'can be read straight through, or a page taken out of it on its '
            'own.'
        ),
    ]
    listed = set()
    for path in paths:
        names = list(path.pages) + [name for name in path.scripts if name in written]
        if not names:
            continue
        listed.update(names)
        out.append(heading(path.title, 1))
        out.append(markup.wrap(' '.join(path.description.split())))
        out.append(
            '.. toctree::\n   :maxdepth: 1\n\n%s'
            % ('\n'.join('   %s' % (name,) for name in names),)
        )
    others = [name for name, _ in HAND_WRITTEN if name not in listed]
    if others:
        out.append(heading('Other tutorials', 1))
        out.append(
            '.. toctree::\n   :maxdepth: 1\n\n%s'
            % ('\n'.join('   %s' % (name,) for name in others),)
        )
    return '\n\n'.join(out).rstrip() + '\n'


# --------------------------------------------------------------------------- #
# Driving it
# --------------------------------------------------------------------------- #
def write(
    output: str = OUTPUT, tests: str = TESTS, paths: Iterable[TutorialPath] = PATHS
) -> list[str]:
    """Write a page for every tutorial, and the index; returns what was written."""
    paths = list(paths)
    os.makedirs(output, exist_ok=True)
    written: list[str] = []
    for path in paths:
        for name in path.scripts:
            source = os.path.join(tests, '%s.py' % (name,))
            if not os.path.isfile(source):
                log.warning('no such tutorial script: %s', source)
                continue
            tutorial = parse(source)
            with open(
                os.path.join(output, '%s.rst' % (name,)), 'w', encoding='utf8'
            ) as handle:
                handle.write(render(tutorial))
            written.append(name)
    with open(os.path.join(output, 'index.rst'), 'w', encoding='utf8') as handle:
        handle.write(render_index(paths, written))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument(
        '--output', default=OUTPUT, help='where to write the pages (default: %(default)s)'
    )
    parser.add_argument(
        '--tests', default=TESTS, help='where the scripts are (default: %(default)s)'
    )
    options = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    written = write(options.output, options.tests)
    log.info('%d tutorials written to %s', len(written), options.output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
