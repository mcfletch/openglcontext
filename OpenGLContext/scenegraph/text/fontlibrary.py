"""X3D's FontLibrary: font files a document's FontStyles may name

A `FontLibrary` (ISO/IEC 19775-1, 15.4.1) reads the first of its `url`s that
is a TrueType or OpenType font, on the loader pool, under the document's url
policy (:meth:`OpenGLContext.loaders.loader.Loader.resolve`: beside the
document, or from its own origin). The font is then a family of the
document's :class:`DocumentFonts` by its `family` alias and by the family
name the file gives itself, so a `FontStyle` in that document whose `family`
names either is drawn with it (:func:`OpenGLContext.scenegraph.text.pillowtext.face`,
:meth:`~OpenGLContext.scenegraph.text.fontprovider.TTFFontProvider.matchFile`).
Several libraries naming one family give it several faces, and the style's
weight and slant choose among them.

`FontStyle.family` keeps its order of preference: a name earlier in the list
that the system's fonts carry is chosen before a library's later one. X3D's
`load` false reads nothing; setting `url`, `family` or `load` reads again.
"""
from __future__ import annotations

import io
import logging
import weakref
from collections.abc import Sequence
from typing import Any, NamedTuple, Optional

from fontTools.ttLib import TTFont, TTLibError
from ttfquery import describe
from vrml import field, fieldtypes, node, protofunctions
from vrml.x3d import loadsensor
from vrml.x3d import nodes as x3d

from OpenGLContext import context
from OpenGLContext.loaders import background, resolver

__all__ = ['DocumentFonts', 'FontFace', 'FontLibrary', 'document_fonts', 'faces_for',
           'key', 'nearest', 'read_face']

log = logging.getLogger(__name__)

#: The weight a face that does not say has.
NORMAL_WEIGHT = 400


class FontFace(NamedTuple):
    """A font file, its family name and its style"""

    path: str
    family: str
    weight: int
    italic: bool


def read_face(path: str) -> FontFace:
    """The family, weight and slant of the font file at `path`; ValueError where it is no font"""
    data = resolver.read_contained(resolver.contained_source(path))
    try:
        with TTFont(io.BytesIO(data), lazy=True) as font:
            _name, family = describe.shortName(font)
            try:
                weight, italic = describe.modifiers(font)
            except (KeyError, AttributeError):
                weight, italic = NORMAL_WEIGHT, 0
    except (TTLibError, KeyError, AssertionError, ValueError, OSError) as err:
        raise ValueError('%s is not a font: %s' % (path, err)) from err
    return FontFace(str(path), str(family), int(weight or NORMAL_WEIGHT), bool(italic))


def nearest(faces: Sequence[FontFace], weight: int, italic: bool) -> FontFace:
    """The face with the slant asked and the weight nearest it; else the nearest weight"""
    return min(faces, key=lambda face: (face.italic != bool(italic), abs(face.weight - weight)))


class DocumentFonts(node.Node):
    """The font families one document's FontLibraries add, by name

    `generation` changes whenever a library's fonts change, so a cache made
    from a family can depend on it.
    """

    PROTO = 'DocumentFonts'
    generation = field.newField('generation', 'SFInt32', 1, 0)

    def __init__(self, **named: Any) -> None:
        super().__init__(**named)
        self.__dict__['_libraries'] = {}

    def place(self, library: Any, names: Sequence[str], faces: Sequence[FontFace]) -> None:
        """`library`'s fonts are `faces`, under each of `names`; none where both are empty"""
        held = self.__dict__['_libraries']
        if names and faces:
            held[library] = (tuple(name.lower() for name in names), tuple(faces))
        else:
            held.pop(library, None)
        self.generation = int(self.generation) + 1

    def members(self, name: str) -> list[FontFace]:
        """The faces the family `name` has, in the order their libraries were read"""
        wanted = str(name).lower()
        return [face for names, faces in self.__dict__['_libraries'].values()
                if wanted in names for face in faces]


_DOCUMENTS: "weakref.WeakKeyDictionary[Any, DocumentFonts]" = weakref.WeakKeyDictionary()


def document_fonts(member: Any) -> Optional[DocumentFonts]:
    """The font families of the document `member` is in; None for a node in none"""
    root = protofunctions.root(member) if member is not None else None
    if not root:
        return None
    found = _DOCUMENTS.get(root)
    if found is None:
        found = _DOCUMENTS[root] = DocumentFonts()
    return found


def faces_for(fontStyle: Any, specifier: str) -> list[FontFace]:
    """The faces `fontStyle`'s document has for the family `specifier`"""
    fonts = document_fonts(fontStyle)
    return fonts.members(specifier) if fonts is not None else []


def key(fontStyle: Any) -> tuple[str, ...]:
    """The library files `fontStyle`'s families name, for a font cache's key"""
    fonts = document_fonts(fontStyle) if fontStyle else None
    if fonts is None:
        return ()
    return tuple(face.path for specifier in (getattr(fontStyle, 'family', None) or ())
                 for face in fonts.members(specifier))


class _Reading:
    """A field whose change has the library read its fonts again"""

    def fset(self, client: Any, value: Any, notify: int = 1) -> Any:
        value = super().fset(client, value, notify)  # type: ignore[misc]  # mixed into a field class
        client.reload()
        return value


class _ReadingStrings(_Reading, fieldtypes.MFString):
    fieldType = 'MFString'


class _ReadingString(_Reading, fieldtypes.SFString):
    fieldType = 'SFString'


class _ReadingBool(_Reading, fieldtypes.SFBool):
    fieldType = 'SFBool'


class FontLibrary(x3d.FontLibrary):
    """X3D's FontLibrary: the first font file of `url`, a family of its document

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/text.html#FontLibrary
    """

    url = _ReadingStrings('url', 1, list)
    family = _ReadingString('family', 1, '')
    load = _ReadingBool('load', 1, True)

    def reload(self) -> None:
        """Take this library's font from its document and, where `load` allows, read `url` again"""
        generation = self.__dict__['_generation'] = self.__dict__.get('_generation', 0) + 1
        fonts = document_fonts(self)
        if fonts is not None and self in fonts.__dict__['_libraries']:
            fonts.place(self, (), ())
        url = list(self.__dict__.get('url', ()))
        if not url or not self.__dict__.get('load', True):
            return
        root = protofunctions.root(self)
        base = getattr(root, 'baseURI', None) if root else None
        loadsensor.set_load_state(self, loadsensor.LOADING)
        background.load_in_background(' '.join(url), self.loadBackground, url, base,
                                      context.Context.allContexts, generation)

    def loadBackground(self, url: Sequence[str], base: Optional[str],
                       contexts: Sequence[Any] = (), generation: Any = None) -> None:
        """Read the first of `url` that is a font; runs on the loader pool"""
        found = None
        for name in url:
            try:
                found = read_face(_local_file(name, base))
            except (OSError, ValueError) as err:
                log.info('FontLibrary url %s did not read: %s', name, err)
                continue
            break
        if found is None:
            log.warning('FontLibrary %s: no font read from %s', self.DEF or '', ' '.join(url))
        for reference in contexts:
            opened = reference()
            if opened is not None:
                opened.renderQueue.call(self._place, found, generation, contexts)
                return
        self._place(found, generation, contexts)

    def _place(self, found: Optional[FontFace], generation: Any,
               contexts: Sequence[Any] = ()) -> None:
        """`found` as this library's font, unless a read since has superseded it"""
        if generation is not None and generation != self.__dict__.get('_generation'):
            return
        fonts = document_fonts(self)
        if found is not None and fonts is not None:
            names = [name for name in (str(self.family or ''), found.family) if name]
            fonts.place(self, names, [found])
        loadsensor.set_load_state(self, loadsensor.LOADED if found is not None
                                  else loadsensor.FAILED)
        for reference in contexts:
            opened = reference()
            if opened is not None:
                opened.triggerRedraw(1)


def _local_file(name: str, base: Optional[str]) -> str:
    """The local file `name` reads from: beside the document `base`, or fetched to the cache"""
    if base:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 the loader imports the scenegraph
        target = Loader.resolve(name, base)
        located: resolver.Located = resolver.checked_source(target)
    else:
        located = resolver.checked_source(name)
    if isinstance(located, resolver.CheckedURL):
        return str(resolver.fetch_to_cache(located))
    return str(located)
