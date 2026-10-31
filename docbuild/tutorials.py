"""The code-walkthrough tutorials, written from the scripts in ``tests/tutorials``.

Each tutorial is a runnable script whose commentary sits in ``'''`` strings
between the statements, so the page and the program that page describes are
the same file and cannot drift apart.  This reads those scripts, turns each
into a page of commentary and code, and writes a page for each path through
them and an index of the paths.

    python -m docbuild.tutorials --output docs/tutorials

The paths -- which scripts, in which order, under which heading -- are
:data:`PATHS`.  Each path is a directory: its scripts, and the files they
open, are in ``tests/tutorials/<directory>``, and its pages are written to
``docs/tutorials/<directory>`` beside the screenshots they show.

A path can open with background of its own: ``tests/tutorials/<directory>/index.rst``
is that path's page in place of the generated one, so a reader meets the
ideas before the first script.  It is written like the commentary -- a
``:doc:`` target naming a tutorial finds it wherever its path puts it -- and
the list of the path's tutorials follows it unless it makes a ``toctree`` of
its own.
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import logging
import os
import posixpath
import re
import sys
import tokenize
from collections.abc import Iterable, Mapping

from docbuild import markup

__all__ = [
    'Tutorial',
    'TutorialPath',
    'PATHS',
    'hand_written',
    'parse',
    'render',
    'render_index',
    'render_path',
    'write',
]

log = logging.getLogger('tutorials')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Where the scripts are: a directory for each path.
SOURCE = os.path.join(HERE, 'tests', 'tutorials')

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

#: A path's introduction, written by hand, in its directory under
#: ``tests/tutorials``.  It is the path's ``index`` page.
INTRODUCTION = 'index.rst'

#: A ``toctree`` directive at the start of a line.
TOCTREE = re.compile(r'^[ \t]*\.\. toctree::', re.MULTILINE)


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
    #: Where the script is under ``tests/``, without ``.py``, for the page to
    #: say (``tutorials/shaders/shader_1``).
    script: str = ''

    def __post_init__(self) -> None:
        self.script = self.script or self.name

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
    #: The directory, under ``tests/tutorials`` and ``docs/tutorials``, the
    #: scripts and the pages are in.
    directory: str
    #: The scripts, by file name without ``.py``.
    scripts: list[str]
    #: Pages in the directory under ``docs/tutorials`` written by hand rather
    #: than from a script, listed at the head of this path.
    pages: list[str] = dataclasses.field(default_factory=list)

    def sources(self, source: str = SOURCE) -> list[str]:
        """The file each script is read from, in order."""
        return [
            os.path.join(source, self.directory, '%s.py' % (name,))
            for name in self.scripts
        ]


PATHS = [
    TutorialPath(
        'Using the Engine',
        """How to get something on screen and make it move: loading a model in
        each of the three formats, playing the clips a rigged
        model was authored with, and walking a character along a route.""",
        'core_context',
        [
            'getting_a_context',
            'loading_gltf_model',
            'keyboardevents',
            'using_clips',
            'crowd_demo',
            'using_npc',
            'navmesh_demo',
            'using_vrml97',
            'using_obj',
        ],
    ),
    TutorialPath(
        'Physics',
        """Using the OpenGLContext physics engine to simulate a world.""",
        'physics',
        pages=['physics_getting_started'],
        scripts=[
            'physics_stairs',
            'physics_stairs_colour',
            'physics_stairs_thread',
            'physics_stairs_shapes',
            'physics_stairs_material',
            'physics_stairs_gravity',
            'physics_stairs_sound',
            'physics_stairs_surface_sound',
            'physics_stairs_tuning',
            'using_physics',
            'physics_events',
            'physics_triggers',
            'physics_bounce',
            'physics_cook_view',
            'physics_room_drop',
            'physics_friction',
            'using_collisions',
            'physics_joints',
            'physics_gravity_zones',
            'physics_navigate',
            'physics_stress',
        ],
    ),
    TutorialPath(
        'Characters on Land',
        """A rigged character that runs across a landscape: ground it collides
        with, clips that play for what the body is doing, another model's
        clips, a camera that follows it and stays out of walls, the sounds of
        its landings, footsteps that follow the surface, and running along a
        trail.""",
        'character',
        [
            'character_run',
            'character_animations',
            'character_jump',
            'character_footsteps',
            'character_camera',
            'character_trail',
        ],
    ),
    TutorialPath(
        'Interface and Tools',
        """What the player reads and what an author edits: panels and screen
        furniture over the frame, a settings page, a console, choosing a level
        by its picture, picking something in the world to drag, and an
        editor's four views of a model.""",
        'interface',
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
        """The scenery nodes and the tools around them: rooms lit as rooms,
        mirrors, water, ground cover, levels of detail, roads, audio,
        particles, instanced batching, writing a scene out as glTF, reading
        one from X3D, and recording a session or a video of one.""",
        'world',
        [
            'x3d_demo',
            'x3d_shaders',
            'x3d_geospatial',
            'x3d_layering',
            'x3d_splats',
            'x3d_materials',
            'x3d_volume',
            'x3d_sound',
            'x3d_movie',
            'zones_demo',
            'mirrors_room',
            'water_demo',
            'cover_meadow',
            'lod_hall',
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
        'extrusions',
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
        'shaders',
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
        'transforms',
        ['transforms_1'],
    ),
    TutorialPath(
        'Scenegraph Nodes',
        """A high-level path, introducing the OpenGLContext/VRML97 scenegraph.
        It covers more involved rendering tasks in less detail than the shader
        path: what to build rather than how the effect is achieved.""",
        'scenegraph',
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
        'shadows',
        ['shadow_1', 'shadow_2', 'shadow_3'],
    ),
    TutorialPath(
        'NeHe Translations',
        """Translations of the NeHe series of tutorials.  These are low-level
        introductory tutorials using the legacy OpenGL API; the originals they
        are translated from are gentle and thorough.""",
        'nehe',
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



def hand_written(paths: Iterable[TutorialPath] = PATHS) -> list[str]:
    """Each page the paths name that is written by hand, as its file under
    ``docs/tutorials`` (``physics/physics_getting_started.rst``)."""
    return [
        '%s/%s.rst' % (path.directory, page) for path in paths for page in path.pages
    ]


# --------------------------------------------------------------------------- #
# Reading a script
# --------------------------------------------------------------------------- #
def parse(path: str, script: str = '') -> Tutorial:
    """One script, split into its commentary and the code between it.

    ``script`` is where it is under ``tests/``, for the page to say; the
    file's name by default.

    Raises :class:`ValueError` for a ``'''`` block that Python reads as part of
    another string, such as commentary written inside a class's docstring.
    """
    with open(path, encoding='utf8') as handle:
        text = handle.read().replace('\r\n', '\n')
    strings = _string_starts(text)
    pieces: list[Piece] = []
    position = 0
    for match in COMMENTARY.finditer(text):
        if match.start(1) not in strings:
            raise ValueError(
                "%s:%d: the ''' commentary is inside another string; close "
                'that string before the commentary starts'
                % (path, text.count('\n', 0, match.start(1)) + 1)
            )
        _code(pieces, text[position : match.start()])
        if match.group('commentary').strip():
            pieces.append(Piece('commentary', match.group('commentary')))
        position = match.end()
    _code(pieces, text[position:])
    return Tutorial(
        name=os.path.splitext(os.path.basename(path))[0],
        source=path,
        pieces=pieces,
        script=script,
    )


def _string_starts(text: str) -> set[int]:
    """The offset in ``text`` of each string literal Python reads in it."""
    lines = [0]
    for line in text.split('\n'):
        lines.append(lines[-1] + len(line) + 1)
    return {
        lines[token.start[0] - 1] + token.start[1]
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.STRING
    }


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


#: A ``:doc:`` role: its target alone, or its text and the target in ``<>``.
DOC_ROLE = re.compile(r':doc:`(?P<text>[^`<]*<)?(?P<target>[^`<>]+)>?`')


def resolve_links(text: str, pages: Mapping[str, str]) -> str:
    """``text`` with each relative ``:doc:`` target made absolute.

    Commentary is written as though every page were in ``docs/tutorials``: a
    target naming a tutorial in ``pages`` (page name to document name) is that
    tutorial wherever its path puts it, and any other relative target is read
    from ``docs/tutorials``, so ``../shadows`` is ``/shadows``.
    """

    def resolve(match: re.Match[str]) -> str:
        target = match.group('target')
        if not target.startswith('/'):
            target = '/' + pages.get(
                target, posixpath.normpath(posixpath.join('tutorials', target))
            )
        if match.group('text') is None:
            return ':doc:`%s`' % (target,)
        return ':doc:`%s%s>`' % (match.group('text'), target)

    return DOC_ROLE.sub(resolve, text)


def render(tutorial: Tutorial, pages: Mapping[str, str] | None = None) -> str:
    """The page for one tutorial.

    ``pages`` maps each tutorial's page name to its document name
    (``tutorials/shaders/shader_1``), for the links between them.
    """
    pages = pages or {}
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
                    out.append(resolve_links(block.text, pages))
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
        'source, which runs as it stands.' % (tutorial.script,)
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


def _listed(path: TutorialPath, written: Iterable[str]) -> list[str]:
    """The pages of ``path`` there are to list, in order, by name."""
    written = set(written)
    return list(path.pages) + [
        name for name in path.scripts if '%s/%s' % (path.directory, name) in written
    ]


def _toctree(path: TutorialPath, written: Iterable[str]) -> str:
    return '.. toctree::\n   :maxdepth: 1\n\n%s' % (
        '\n'.join('   %s' % (name,) for name in _listed(path, written)),
    )


def render_path(
    path: TutorialPath,
    written: Iterable[str],
    introduction: str | None = None,
    pages: Mapping[str, str] | None = None,
) -> str:
    """The page of one path: what it covers, and the toctree of its tutorials.

    ``written`` names the pages written from scripts, as ``directory/name``.
    ``introduction`` is the text of the path's hand-written ``index.rst``,
    which is the page in place of the description; the toctree follows it
    unless it holds one.  ``pages`` is as for :func:`render`.
    """
    label = '.. _tutorials-%s:' % (path.directory,)
    if introduction is None:
        return '\n\n'.join(
            [
                label,
                heading(markup.escape(path.title), 0),
                markup.wrap(' '.join(path.description.split())),
                _toctree(path, written),
            ]
        ) + '\n'
    text = resolve_links(introduction.replace('\r\n', '\n'), pages or {}).strip('\n')
    out = [] if label in text else [label]
    out.append(text)
    if not TOCTREE.search(text):
        out.append(_toctree(path, written))
    return '\n\n'.join(out) + '\n'


def render_index(paths: Iterable[TutorialPath], written: Iterable[str]) -> str:
    """The page listing the paths, each with a page of its own.

    The toctree carrying the paths' pages is hidden, since the list after it
    links each one with its description.
    """
    written = set(written)
    listed = [path for path in paths if _listed(path, written)]
    out = [
        heading('OpenGLContext Tutorials', 0),
        markup.wrap(
            'Each of these is a runnable script in the OpenGLContext source, '
            'with the commentary written into the script beside the code it '
            'describes.  They are grouped by subject into paths; a path can '
            'be read straight through, or a page taken out of it on its own.'
        ),
        '.. toctree::\n   :hidden:\n\n%s'
        % ('\n'.join('   %s/index' % (path.directory,) for path in listed),),
    ]
    out.extend(
        ':doc:`%s <%s/index>`\n%s'
        % (
            markup.escape(path.title),
            path.directory,
            indent(markup.wrap(' '.join(path.description.split()))),
        )
        for path in listed
    )
    return '\n\n'.join(out).rstrip() + '\n'


# --------------------------------------------------------------------------- #
# Driving it
# --------------------------------------------------------------------------- #
def write(
    output: str = OUTPUT, source: str = SOURCE, paths: Iterable[TutorialPath] = PATHS
) -> list[str]:
    """Write a page for every tutorial, a page for each path and the index.

    Returns the pages written from scripts, as ``directory/name``.  Each page
    carries a label named for its script, so two scripts of one name are
    refused, and so is a script named ``index``, whose page would be its
    path's.  A path whose directory under ``source`` holds an ``index.rst``
    has that for its page.
    """
    paths = list(paths)
    pages: dict[str, str] = {}
    for path in paths:
        for name in path.scripts:
            if name == 'index':
                raise ValueError(
                    'tutorial script %s/index would be written over the page of '
                    'its path' % (path.directory,)
                )
            page = 'tutorials/%s/%s' % (path.directory, name)
            other = pages.setdefault(name, page)
            if other != page:
                raise ValueError(
                    'tutorial scripts %s and %s would both be labelled tutorial-%s'
                    % (other, page, name)
                )
    written: list[str] = []
    for path in paths:
        directory = os.path.join(output, path.directory)
        os.makedirs(directory, exist_ok=True)
        for name, script in zip(path.scripts, path.sources(source)):
            if not os.path.isfile(script):
                log.warning('no such tutorial script: %s', script)
                continue
            tutorial = parse(script, 'tutorials/%s/%s' % (path.directory, name))
            _replace(
                os.path.join(directory, '%s.rst' % (name,)), render(tutorial, pages)
            )
            written.append('%s/%s' % (path.directory, name))
        _replace(
            os.path.join(directory, 'index.rst'),
            render_path(path, written, _introduction(path, source), pages),
        )
    _replace(os.path.join(output, 'index.rst'), render_index(paths, written))
    return written


def _introduction(path: TutorialPath, source: str) -> str | None:
    """The text of the path's hand-written ``index.rst``, or None where it has none."""
    where = os.path.join(source, path.directory, INTRODUCTION)
    if not os.path.isfile(where):
        return None
    with open(where, encoding='utf8') as handle:
        return handle.read()


def _replace(path: str, text: str) -> None:
    """Replace the file at ``path`` with ``text``, renamed into place once written."""
    with open(path + '.partial', 'w', encoding='utf8') as handle:
        handle.write(text)
    os.replace(path + '.partial', path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument(
        '--output', default=OUTPUT, help='where to write the pages (default: %(default)s)'
    )
    parser.add_argument(
        '--source', default=SOURCE, help='where the scripts are (default: %(default)s)'
    )
    options = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    written = write(options.output, options.source)
    log.info('%d tutorials written to %s', len(written), options.output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
