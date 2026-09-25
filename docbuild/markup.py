"""The commentary format the tutorial scripts are written in.

A tutorial script is ordinary Python with its commentary in ``'''`` strings
between the statements, written in a small wiki-like notation:

.. code-block:: text

    =A title=
    _A section heading_

    A paragraph.  A link is [https://example.org/ written like this], a bare
    URL is a link too, and [shader_1.py-screen-0001.png a picture] is one when
    the target is an image.  A link to [molehill.html another page] of this
    documentation becomes a reference the build checks.

    reST written into the commentary is kept as markup: ``a literal``,
    `a name`, :doc:`a role <index>`, *emphasis* and **strong**.  A star with
    nothing to close it is an asterisk.

    * a bullet
    * another, whose continuation lines are indented

    term -- what the term means

        A block whose own lines are indented under something keeps its
        spacing: a table, a column of names, a shell session.

:func:`commentary` turns one such string into :class:`Block` values, which
:mod:`docbuild.tutorials` writes into the page.  ``'''`` rather than ``\"\"\"``
marks commentary, which is what separates it from the docstrings of the
classes and functions the tutorial is building.
"""

from __future__ import annotations

import dataclasses
import functools
import importlib
import re
import textwrap
from collections.abc import Iterator

__all__ = [
    'Block', 'commentary', 'inline', 'escape', 'wrap', 'entry_points',
    'pictures',
]

#: ``[target text]``, where the target looks like a location -- a scheme, a
#: path, an anchor or a file name.  Ordinary bracketed prose is left alone
#: rather than becoming an invented link.
#: An optional ``class=name`` in front of the target is how the scripts
#: arranged one picture against the next; the arrangement is the stylesheet's
#: now, so the name is read and dropped.
_LINK = re.compile(
    r"""\[(?:class=[\w-]+[ ]+)?"""
    r"""(?P<url>(?:\w+://|[./#])[^ \]]*|[^ \]]+\.\w{2,4})[ ]+"""
    r"""(?P<text>[^\]]+)\]"""
    r"""|(?P<bald>https?://[^ \t\n]+)"""
)

#: A picture rather than a page.
_IMAGES = ('.png', '.jpg', '.bmp', '.tif')

#: A page of this documentation: a ``.html`` name with no host in front of it,
#: and no anchor, which is what the scripts link to each other by.
_PAGE = re.compile(r'(?P<path>/?[\w./-]*[\w-])\.html$')

#: Text that names the kind of thing a picture is rather than saying anything
#: about this one, and so is the alt text without also being the caption.
_UNCAPTIONED = frozenset({'screenshot', 'screen shot', 'image', 'picture'})

#: A bullet: a star or a dash, and then a space.  The space is what tells a
#: marker from a word in emphasis at the head of a paragraph, and from the
#: ``--`` of a definition line.
_BULLET = re.compile(r'[*-][ \t]')

#: ``term -- definition``, which is a definition list.
_DEFINITION = re.compile(r"""[ \t]*(?P<term>\w+)\W*--\W*(?P<definition>.*)""")

#: Inline markup that starts a word has to be escaped where it is meant
#: literally; a trailing underscore is a reference unless it is escaped.
_ESCAPE = re.compile(r'([\\*`|])')
_TRAILING = re.compile(r'(?<=\w)_(?=\s|$|[.,;:!?)\]])')

#: What a span may hold: anything but its own marker, over as many lines as
#: the docstring happened to wrap it across.  A block is split on blank lines
#: before any of this runs, so a marker with no partner runs to the end of its
#: paragraph at worst.
_SPAN = r'(?:[^%s\n]|\n(?![ \t]*\n))'

#: reST inline markup a script wrote on purpose: a literal, a role, a
#: reference, interpreted text under the default role, or emphasis.  The
#: scripts document themselves in reST and mean these as markup, so they are
#: carried through rather than escaped.  A star with a word tight against it
#: on the outside is arithmetic or an argument list rather than emphasis, and
#: one that opens nothing is an asterisk.
_RST_INLINE = re.compile(
    r'(?::[\w.+:-]+:)?``%(tick)s+``'    # a literal, with or without a role
    r'|:[\w.+:-]+:`%(tick)s+`'          # a role
    r'|`%(tick)s+`__?'                  # a reference
    r'|`%(tick)s+`'                     # interpreted text, under the default role
    r'|(?<![\w*])\*\*[^\s*]%(star)s*\*\*(?![\w*])'    # strong
    r'|(?<![\w*])\*[^\s*]%(star)s*\*(?![\w*])'        # emphasis
    % {'tick': _SPAN % ('`',), 'star': _SPAN % ('*',)}
)

_BLANK_LINE = re.compile(r'\n[ \t]*\n')

#: A GL call, as the commentary writes one: ``gl``, ``glu``, ``glut`` or
#: ``gle`` and a capital after it.  Whether it is really an entry point is a
#: question for :func:`entry_points`, which is what keeps ``glTF`` out.
_CALL = re.compile(r'\b(gl(?:u|ut|e)?[A-Z]\w*)\b')

#: A name PyOpenGL's own set declares: a dotted one, which is a module or
#: something a module holds, or a bare call.  One pattern and one pass, so
#: that a name written into the text as a reference is not read again as a
#: call -- ``OpenGL.GL.glBegin`` is the dotted one and nothing else.
_NAMES = re.compile(r'\bOpenGL(?:\.\w+)+\b|' + _CALL.pattern)

#: reStructuredText reads a reference as a reference only where it starts
#: after whitespace or one of these and ends before whitespace or one of the
#: closers.  ``glGetUniformLocation( shader )`` is what needs saying: an
#: opening bracket is in neither set.
_OPENERS = set(' \t\n-:/\'"<([{')
_CLOSERS = set(' \t\n-.,:;!?\\/\'")]}>')

#: The packages a bare entry point could have come from, in the order a name
#: is claimed.  ``gluPerspective`` is GLU's and ``glutInit`` is GLUT's, and
#: neither is in ``OpenGL.GL``, so the order only settles a name in two -- of
#: which there are none today.
CALL_PACKAGES = ('OpenGL.GL', 'OpenGL.GLU', 'OpenGL.GLUT', 'OpenGL.GLE')


@functools.lru_cache(maxsize=None)
def entry_points() -> dict[str, str]:
    """Every entry point PyOpenGL exports, and the package it is exported from.

    Read from the installed packages rather than from a list: the point of the
    lookup is that a name the commentary writes is linked where PyOpenGL has
    it and left as text where it does not, and PyOpenGL is what knows.  A
    package that will not import -- GLUT with no library on the machine --
    contributes nothing and the rest still answer.
    """
    found: dict[str, str] = {}
    for package in CALL_PACKAGES:
        try:
            module = importlib.import_module(package)
        except (ImportError, OSError):
            continue
        for name in dir(module):
            if _CALL.fullmatch(name) and callable(getattr(module, name, None)):
                found.setdefault(name, package)
    return found


def link_calls(text: str) -> str:
    """The GL names in a run of prose, as references into PyOpenGL's own set.

    ``glBegin`` becomes a link to the reference page for it, through
    ``intersphinx``: PyOpenGL declares every entry point under its own package
    name, so the target is ``OpenGL.GL.glBegin`` and the ``~`` is what shows
    the reader the name they wrote.  Where that set is not reachable the name
    renders as itself.

    A name already inside reST markup is left alone: what a writer wrote as a
    literal or a reference is the reference they meant.
    """
    if _RST_INLINE.search(text):
        return ''.join(
            piece if _RST_INLINE.fullmatch(piece) else link_calls(piece)
            for piece in _split_rst(text)
        )
    known = entry_points()

    def reference(match: re.Match) -> str:
        call = match.group(1)
        if call is None:
            role = ':py:obj:`%s`' % (match.group(0),)
        elif call in known:
            role = ':py:func:`~%s.%s`' % (known[call], call)
        else:
            return str(match.group(0))
        before = text[match.start() - 1] if match.start() else ' '
        after = text[match.end()] if match.end() < len(text) else ' '
        return '%s%s%s' % (
            '' if before in _OPENERS else '\\ ',
            role,
            '' if after in _CLOSERS else '\\ ',
        )

    return _NAMES.sub(reference, text)


@dataclasses.dataclass
class Block:
    """One piece of commentary.

    ``kind`` is ``title`` or ``subtitle``, where ``text`` is the heading; or
    ``rst``, where ``text`` is the reStructuredText to write as it stands.
    """

    kind: str
    text: str


def escape(text: str) -> str:
    """``text`` as reST that renders as itself.

    The commentary is prose rather than markup: a ``*`` in it is an asterisk
    and ``__init__`` is a name, so neither starts anything.  A span of reST --
    a literal, a role, a reference -- is markup the script wrote on purpose
    and is left as it stands.
    """
    return ''.join(
        piece if _RST_INLINE.fullmatch(piece)
        else _TRAILING.sub(r'\\_', _ESCAPE.sub(r'\\\1', piece))
        for piece in _split_rst(text)
    )


def _split_rst(text: str) -> Iterator[str]:
    """``text`` as its reST spans and the prose between them."""
    position = 0
    for match in _RST_INLINE.finditer(text):
        yield text[position : match.start()]
        yield match.group(0)
        position = match.end()
    yield text[position:]


def inline(text: str) -> str:
    """One run of commentary text, as reST, with its links resolved."""
    out: list[str] = []
    position = 0
    for match in _LINK.finditer(text):
        out.append(link_calls(escape(text[position : match.start()])))
        if match.group('bald'):
            out.append(match.group('bald'))
        else:
            out.append(reference(match.group('url'), collapse(match.group('text'))))
        position = match.end()
    out.append(link_calls(escape(text[position:])))
    return collapse(''.join(out)).strip()


def reference(url: str, text: str) -> str:
    """One link, as the reST for it.

    A ``.html`` target with no host is another page of this documentation --
    ``molehill.html`` is the tutorial beside this one, ``/structure.html`` a
    page at the top -- and a ``:doc:`` reference to it is checked when the
    site is built, where a bare address is not.  Anything else is a link.
    """
    page = _PAGE.match(url)
    if page:
        return ':doc:`%s <%s>`' % (text, page.group('path'))
    return '`%s <%s>`__' % (text, url)


def collapse(text: str) -> str:
    return re.sub(r'[ \t\n]+', ' ', text)


def pictures(text: str) -> list[str]:
    """The names of the pictures ``text`` shows, in the order it shows them."""
    return [
        match.group('url')
        for match in _LINK.finditer(text)
        if (match.group('url') or '').lower().endswith(_IMAGES)
    ]


def images(block: str) -> str:
    """The pictures a block is made of, or nothing where it is prose.

    Several pictures in one block are a row of them -- the screenshots a
    tutorial shows two at a time -- and go in a container the stylesheet lays
    out; one is a picture on its own.
    """
    found = []
    for match in _LINK.finditer(block):
        url = match.group('url') or ''
        if not url.lower().endswith(_IMAGES):
            return ''
        text = collapse(match.group('text')).strip()
        # The text is the alt text; where it says something about this picture
        # rather than naming the kind of thing it is, it is also the caption.
        if text.lower() in _UNCAPTIONED:
            found.append('.. image:: %s\n   :alt: %s' % (url, text))
        else:
            found.append(
                '.. figure:: %s\n   :alt: %s\n\n%s'
                % (url, text, _indent(wrap(inline(text)), '   '))
            )
    if not found or _LINK.sub('', block).strip():
        return ''
    if len(found) == 1:
        return found[0]
    return '.. container:: shot-row\n\n%s' % (
        _indent('\n\n'.join(found), '   '),
    )


def _leads_a_block(block: str) -> tuple[str, str] | None:
    """A line introducing an indented block under it, as the two of them.

    ``Keys:`` and a column of keys against what each does is the common one.
    The lines under it are laid out by hand, so they keep their spacing, while
    the line that introduces them is a sentence and is wrapped like one.
    """
    lines = [line for line in block.splitlines() if line.strip()]
    if len(lines) < 2 or not lines[0].rstrip().endswith(':'):
        return None
    head = indent_level(lines[0])
    if any(indent_level(line) <= head for line in lines[1:]):
        return None
    body = textwrap.dedent('\n'.join(lines[1:]).replace('\t', ' ' * 8))
    return lines[0].strip(), body


def indent_level(line: str) -> int:
    expanded = line.replace('\t', ' ' * 8)
    return len(expanded) - len(expanded.lstrip(' '))


def is_aligned(block: str) -> bool:
    """Whether a block's own spacing carries meaning.

    A table, a column of names against descriptions, a fragment of a shell
    session: each lines its continuation lines up under something, and each
    reads as nonsense once the runs of spaces that did the lining up are
    collapsed.  Detected by a line indented relative to the block once the
    block's common indent is removed.

    The first line of a block cut from a ``'''`` string begins right after the
    quotes, so it carries none of the indent its continuation lines do and
    cannot be part of the common prefix; the prefix is taken from the rest.
    """
    lines = [line for line in block.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    common = min(indent_level(line) for line in lines[1:])
    return any(line[common:][:1].isspace() for line in lines[1:])


def _heading(block: str, marker: str) -> str | None:
    """The heading ``block`` is, where it is one wrapped in ``marker``."""
    text = block.strip()
    if len(text.splitlines()) != 1:
        return None
    if len(text) > 2 and text.startswith(marker) and text.endswith(marker):
        return text.strip(marker).strip()
    return None


def _bullets(block: str) -> str:
    """A bulleted list; a line that is not a bullet continues the one above."""
    items: list[list[str]] = []
    for line in block.splitlines():
        if _BULLET.match(line.lstrip()):
            items.append([line.lstrip()[1:].strip()])
        elif items and line.strip():
            items[-1].append(line.strip())
    return '\n\n'.join(
        wrap(inline(' '.join(item)), bullet='- ') for item in items if item
    )


def _definitions(block: str) -> str:
    """A definition list: ``term -- what it means``."""
    out: list[str] = []
    for line in block.splitlines():
        match = _DEFINITION.match(line)
        if match:
            out.append(escape(match.group('term')))
            out.append(_indent(wrap(inline(match.group('definition'))), '   '))
        elif line.strip() and out:
            out[-1] = out[-1] + ' ' + inline(line)
    return '\n'.join(out)


def wrap(text: str, bullet: str = '') -> str:
    lines = textwrap.wrap(
        text,
        width=78 - len(bullet),
        break_long_words=False,
        break_on_hyphens=False,
    )
    if not lines:
        return ''
    if not bullet:
        return '\n'.join(lines)
    return '\n'.join(
        [bullet + lines[0]] + [' ' * len(bullet) + line for line in lines[1:]]
    )


def _indent(text: str, prefix: str) -> str:
    return '\n'.join(prefix + line if line.strip() else '' for line in text.split('\n'))


def _blocks(text: str) -> Iterator[str]:
    for block in _BLANK_LINE.split(text.replace('\r\n', '\n')):
        if block.strip():
            yield block


def commentary(text: str) -> list[Block]:
    """One ``'''`` string of commentary, as blocks to write into the page."""
    out: list[Block] = []
    for block in _blocks(text):
        title = _heading(block, '=')
        if title:
            out.append(Block('title', title))
            continue
        subtitle = _heading(block, '_')
        if subtitle:
            out.append(Block('subtitle', subtitle))
            continue
        pictures = images(block)
        if pictures:
            out.append(Block('rst', pictures))
            continue
        stripped = textwrap.dedent(block)
        lead = _leads_a_block(block)
        if out and out[-1].text.rstrip().endswith('::'):
            # reST's own announcement: the paragraph before it said that what
            # comes next is laid out by hand.
            out.append(Block('rst', _indent(_dedent_all(block), '   ')))
        elif lead:
            head, body = lead
            out.append(Block('rst', wrap(inline(head))))
            out.append(Block('rst', '::\n\n%s' % (_indent(body, '   '),)))
        elif _BULLET.match(stripped.lstrip()):
            out.append(Block('rst', _bullets(stripped)))
        elif _DEFINITION.match(stripped):
            out.append(Block('rst', _definitions(stripped)))
        elif is_aligned(block):
            out.append(
                Block('rst', '::\n\n%s' % (_indent(_dedent_all(block), '   '),))
            )
        else:
            out.append(Block('rst', wrap(inline(stripped))))
    return [block for block in out if block.text.strip()]


def _dedent_all(block: str) -> str:
    """``block`` with its common indent removed, first line included.

    The first line of a block cut from a ``'''`` string has no indent of its
    own, so :func:`textwrap.dedent` would find nothing in common; the indent
    comes from the rest of the lines and is taken off those.
    """
    lines = block.replace('\t', ' ' * 8).splitlines()
    rest = [line for line in lines[1:] if line.strip()]
    if not rest:
        return block.strip()
    common = min(indent_level(line) for line in rest)
    return '\n'.join(
        [lines[0].strip()] + [line[common:].rstrip() for line in lines[1:]]
    ).strip('\n')
