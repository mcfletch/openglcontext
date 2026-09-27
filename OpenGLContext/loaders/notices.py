"""The copyright and licence notices a loaded file carries.

A model or a world often states who made it and on what terms: a glTF in its
asset's ``copyright``, in exporter extras and in ``KHR_xmp_json_ld`` packets, a
VRML97 world in its ``WorldInfo``.  Each loader turns what its format says into
:class:`Notice` records, one for the file as a whole and one for each part that
states terms of its own, and :func:`notices_text` sets them out for a reader.
The viewer shows that text on the ``i`` key.

A file's part made by somebody else -- a scanned statue placed in a temple --
may carry terms the rest of the file does not, which is why a notice says what
it ``covers``.
"""
from collections.abc import Sequence
from dataclasses import dataclass, fields
from gettext import gettext as _

__all__ = ['Notice', 'notices_text', 'NONE', 'WHOLE_FILE']

#: What a scene with no notices says, rather than an empty page.
NONE = _('This file carries no copyright or licence notice.')

#: The heading for the notice that covers the whole file.
WHOLE_FILE = _('This file')

_INDENT = '    '


@dataclass(frozen=True)
class Notice:
    """Who made something, and on what terms.

    ``covers`` names the parts of the file the notice is about, or is empty
    when it is about the whole file.  The rest is the notice itself, each as
    the file wrote it: ``copyright`` is the statement a file makes about
    itself, and ``title``, ``creator``, ``licence`` and ``source`` are the
    pieces a format gives separately.  A field the file does not state is
    empty.
    """

    covers: str = ''
    title: str = ''
    creator: str = ''
    copyright: str = ''
    licence: str = ''
    source: str = ''

    def __bool__(self) -> bool:
        """Whether the notice says anything, apart from what it covers."""
        return any(getattr(self, field.name) for field in fields(self)
                   if field.name != 'covers')

    def lines(self) -> list[str]:
        """The notice as lines of text, headed by what it covers."""
        body = [self.title,
                _('By %s') % self.creator if self.creator else '',
                self.copyright,
                _('Licence: %s') % self.licence if self.licence else '',
                _('Source: %s') % self.source if self.source else '']
        return [self.covers or WHOLE_FILE] + [
            _INDENT + line for text in body if text for line in text.splitlines()]


def notices_text(notices: Sequence[Notice]) -> str:
    """``notices`` as one text, a blank line between them, or :data:`NONE`."""
    said = [notice for notice in notices if notice]
    if not said:
        return NONE
    return '\n\n'.join('\n'.join(notice.lines()) for notice in said)
