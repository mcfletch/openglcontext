"""The commentary format the tutorial scripts are written in.

A tutorial script is ordinary Python with its commentary in ``'''`` strings
between the statements, written in a small wiki-like notation:

.. code-block:: text

    =A title=
    _A section heading_

    A paragraph.  A link is [https://example.org/ written like this], a bare
    URL is a link too, and [shader_1.py-screen-0001.png a picture] is one when
    the target is an image.

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
import re
import textwrap
from typing import Iterator

__all__ = ['Block', 'commentary', 'inline', 'escape', 'wrap']

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

#: Text that names the kind of thing a picture is rather than saying anything
#: about this one, and so is the alt text without also being the caption.
_UNCAPTIONED = frozenset({'screenshot', 'screen shot', 'image', 'picture'})

#: ``term -- definition``, which is a definition list.
_DEFINITION = re.compile(r"""[ \t]*(?P<term>\w+)\W*--\W*(?P<definition>.*)""")

#: Inline markup that starts a word has to be escaped where it is meant
#: literally; a trailing underscore is a reference unless it is escaped.
_ESCAPE = re.compile(r'([\\*`|])')
_TRAILING = re.compile(r'(?<=\w)_(?=\s|$|[.,;:!?)\]])')

_BLANK_LINE = re.compile(r'\n[ \t]*\n')


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
    and ``__init__`` is a name, so neither starts anything.
    """
    return _TRAILING.sub(r'\\_', _ESCAPE.sub(r'\\\1', text))


def inline(text: str) -> str:
    """One run of commentary text, as reST, with its links resolved."""
    out: list[str] = []
    position = 0
    for match in _LINK.finditer(text):
        out.append(escape(text[position : match.start()]))
        if match.group('bald'):
            out.append(match.group('bald'))
        else:
            out.append(
                '`%s <%s>`__' % (collapse(match.group('text')), match.group('url'))
            )
        position = match.end()
    out.append(escape(text[position:]))
    return collapse(''.join(out)).strip()


def collapse(text: str) -> str:
    return re.sub(r'[ \t\n]+', ' ', text)


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
        if line.lstrip().startswith(('*', '-')) and not line.lstrip().startswith('--'):
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
        if stripped.lstrip().startswith(('*', '-')):
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
