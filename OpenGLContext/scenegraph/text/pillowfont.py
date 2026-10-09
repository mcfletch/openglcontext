"""The ``texture`` font: Text drawn by Pillow from an atlas of drawn lines

Each line of a Text node is drawn by Pillow (:mod:`pillowtext`) at a pixel em
chosen from the text's size on screen, and kept in an atlas of such lines
(:mod:`snippetatlas`), one per GL context. A Text node draws a quad over each
line's ink, one draw for each atlas page its lines are on. A page is one byte
a texel, read as white with that byte as alpha, and is bound as the base
colour map: the shape's material colours and lights the text, and the shape
is blended with the transparent shapes. Text casts no shadow.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Optional

import numpy as np
from OpenGL.arrays import vbo
from OpenGL.GL import (
    GL_CLAMP_TO_EDGE, GL_COMBINE, GL_COMBINE_ALPHA, GL_COMBINE_RGB, GL_LINEAR,
    GL_MODELVIEW_MATRIX, GL_MODULATE, GL_ONE, GL_PREVIOUS, GL_PRIMARY_COLOR,
    GL_PROJECTION_MATRIX, GL_QUADS, GL_R8, GL_RED, GL_REPLACE, GL_SRC0_ALPHA,
    GL_SRC0_RGB, GL_SRC1_ALPHA, GL_SRC1_RGB, GL_TEXTURE, GL_TEXTURE_2D,
    GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_SWIZZLE_RGBA, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_UNPACK_ALIGNMENT,
    GL_UNSIGNED_BYTE, GL_VIEWPORT, glBegin, glBindTexture, glDeleteTextures, glDisable,
    glEnable, glEnd, glGenTextures, glGetDoublev, glGetIntegerv, glNormal3f,
    glPixelStorei, glTexCoord2f, glTexEnvi, glTexImage2D, glTexParameteri,
    glTexParameteriv, glTexSubImage2D, glVertex3f,
)

from OpenGLContext import contextresources
from OpenGLContext.scenegraph.text import font, fontprovider, pillowtext
from OpenGLContext.scenegraph.text.snippetatlas import Placement, SnippetAtlas

__all__ = ['PillowTextFont', 'PillowTextProvider', 'TextAtlas']

VBO: Any = vbo.VBO

#: The texels along a side of an atlas page.
PAGE_SIZE = 2048

#: How many drawn layouts each context keeps vertex buffers for.
KEPT_LAYOUTS = 512

#: The fixed-function texture environment drawing a page: the lit colour,
#: its alpha times the coverage. GL_MODULATE would keep the fragment's alpha,
#: since the environment's table goes by the page's base format (red).
COVERAGE_ENVIRONMENT = (
    (GL_TEXTURE_ENV_MODE, GL_COMBINE),
    (GL_COMBINE_RGB, GL_REPLACE), (GL_SRC0_RGB, GL_PRIMARY_COLOR),
    (GL_COMBINE_ALPHA, GL_MODULATE), (GL_SRC0_ALPHA, GL_PRIMARY_COLOR),
    (GL_SRC1_ALPHA, GL_TEXTURE),
)

#: The texture environment's initial values, put back after a page is drawn.
INITIAL_ENVIRONMENT = (
    (GL_TEXTURE_ENV_MODE, GL_MODULATE),
    (GL_COMBINE_RGB, GL_MODULATE), (GL_SRC0_RGB, GL_TEXTURE), (GL_SRC1_RGB, GL_PREVIOUS),
    (GL_COMBINE_ALPHA, GL_MODULATE), (GL_SRC0_ALPHA, GL_TEXTURE),
    (GL_SRC1_ALPHA, GL_PREVIOUS),
)


class _Drawn:
    """The quads of a layout's lines on one atlas page: the page, the vertex
    count and the position, normal and texture coordinate buffers. The vertex
    array drawing them is kept on it."""

    def __init__(self, page: int, count: int, buffers: tuple[Any, Any, Any]) -> None:
        self.page = page
        self.count = count
        self.buffers = buffers


class TextAtlas:
    """One GL context's atlas of drawn lines: where each is, and the page textures"""

    def __init__(self, page_size: int = PAGE_SIZE) -> None:
        self.packing = SnippetAtlas(page_size)
        self.page_size = page_size
        self.textures: list[int] = []
        self.layouts: OrderedDict[tuple[Any, ...], list[_Drawn]] = OrderedDict()
        self._frame: Optional[int] = None

    def begin(self, frame: Optional[int]) -> None:
        """Mark what is asked for from now on as used in `frame`"""
        if frame is not None and frame != self._frame:
            self._frame = frame
            self.packing.tick()

    def snippet(self, face: pillowtext.Face, text: str, em: float
                ) -> Optional[tuple[Placement, Any]]:
        """Where `text`, drawn from `face` at an `em` pixel em, is, and its ink
        box in ems; None for text with no ink"""
        key = (face, em, text)
        found = self.packing.find(key)
        if found is not None:
            return found, self.packing.payload(key)
        line = pillowtext.draw_line(face, text, size=1.0, pixels_per_unit=em)
        if line.image is None:
            return None
        width, height = line.image.size
        if width > self.page_size or height > self.page_size:
            return None
        box = (line.left, line.right, line.bottom, line.top)
        placed = self.packing.place(key, width, height, box)
        self._upload(placed, line.image)
        return placed, box

    def texture(self, page: int) -> int:
        """The GL texture of `page`, made the first time it is asked for"""
        while len(self.textures) <= page:
            name = int(glGenTextures(1))
            glBindTexture(GL_TEXTURE_2D, name)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, self.page_size, self.page_size, 0,
                         GL_RED, GL_UNSIGNED_BYTE, None)
            for parameter, value in ((GL_TEXTURE_MIN_FILTER, GL_LINEAR),
                                     (GL_TEXTURE_MAG_FILTER, GL_LINEAR),
                                     (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
                                     (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
                glTexParameteri(GL_TEXTURE_2D, parameter, value)
            # White, with the coverage as alpha
            glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_SWIZZLE_RGBA,
                             np.array((GL_ONE, GL_ONE, GL_ONE, GL_RED), 'i'))
            self.textures.append(name)
        return self.textures[page]

    def _upload(self, placed: Placement, image: Any) -> None:
        # Bottom row first, so (u0, v0) is the image's lower left
        coverage = np.ascontiguousarray(np.asarray(image.getchannel('A'))[::-1])
        glBindTexture(GL_TEXTURE_2D, self.texture(placed.page))
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexSubImage2D(GL_TEXTURE_2D, 0, placed.x, placed.y, placed.width, placed.height,
                        GL_RED, GL_UNSIGNED_BYTE, coverage)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 4)

    def release(self) -> None:
        """Delete the page textures, in the context that made them"""
        if self.textures:
            glDeleteTextures(self.textures)
        self.textures = []


#: Each GL context's atlas.
_ATLASES: dict[Optional[contextresources.ContextKey], TextAtlas] = {}


@contextresources.on_context_lost
def _drop_context_atlas() -> None:
    """Forget the atlas of the context now being destroyed"""
    atlas = _ATLASES.pop(contextresources.context_key(), None)
    if atlas is not None:
        atlas.release()


def text_atlas() -> TextAtlas:
    """The current GL context's atlas"""
    key = contextresources.context_key()
    found = _ATLASES.get(key)
    if found is None:
        found = _ATLASES[key] = TextAtlas()
    return found


class PillowLine:
    """A line of text: its characters, how far it advances and its height"""

    def __init__(self, base: str, width: float, height: float) -> None:
        self.base = base
        self.width = width
        self.height = height


class PillowTextFont(font.Font):
    """Text drawn by Pillow from the face a FontStyle names, through the atlas"""

    format = 'texture'
    shader_compatible = True

    def __init__(self, fontStyle: Any, face: pillowtext.Face) -> None:
        self.fontStyle = fontStyle
        self.face = face
        self.size = float(getattr(fontStyle, 'size', 1.0) or 1.0)

    def lineHeight(self, mode: Any = None) -> float:
        """The distance between baselines before spacing: the fontStyle's size"""
        return self.size

    def toLines(self, value: bytes | str, mode: Any = None) -> list[Any]:
        """The lines of `value`, each measured with the face's kerning"""
        text = self.normalise(value)
        return [PillowLine(line, pillowtext.advance(self.face, line, self.size), self.size)
                for line in (part.expandtabs(4) for part in text.split('\n'))]

    def render(self, lines: Any, fontStyle: Any = None, mode: Any = None) -> Any:
        """Draw `lines` laid out by `fontStyle` in the pass `mode`"""
        if isinstance(lines, (bytes, str)):
            lines = self.toLines(lines, mode=mode)
        if fontStyle is None:
            fontStyle = self.fontStyle
        if mode is None or getattr(mode, 'shadow_pass', False):
            return 1
        shader = getattr(mode, 'shader_program', None)
        if not getattr(mode, 'shader_mode', False):
            shader = None
        elif shader is None or not getattr(shader, 'program', None):
            return 1
        atlas = text_atlas()
        frame = getattr(getattr(mode, 'frameState', None), 'number', None)
        atlas.begin(frame)
        em = pillowtext.em_pixels(self._on_screen(mode) * self.size)
        placed = []
        for line, x, y in self.layout(lines, fontStyle, mode=mode):
            found = atlas.snippet(self.face, line.base, em)
            if found is not None:
                placed.append((found[0], found[1], x, y))
        if not placed:
            return 1
        visible = getattr(mode, 'visible', True)
        if shader is None:
            self._draw_fixed(atlas, placed, visible)
            return 1
        for drawn in self._buffers(atlas, placed):
            if visible:
                shader.bind_coverage(atlas.texture(drawn.page))
            self._draw(mode, drawn)
        if visible:
            shader.release_coverage()
        return 1

    def _draw_fixed(self, atlas: TextAtlas, placed: list[tuple[Placement, Any, float, float]],
                    visible: bool) -> None:
        """Draw `placed` lines through the fixed-function pipeline, the
        page's coverage as the lit colour's alpha"""
        if visible:
            glEnable(GL_TEXTURE_2D)
            for name, value in COVERAGE_ENVIRONMENT:
                glTexEnvi(GL_TEXTURE_ENV, name, value)
        try:
            glNormal3f(0.0, 0.0, 1.0)
            for where, (left, right, bottom, top), x, y in placed:
                if visible:
                    glBindTexture(GL_TEXTURE_2D, atlas.texture(where.page))
                u0, v0, u1, v1 = where.texcoords(atlas.page_size)
                glBegin(GL_QUADS)
                for cx, cy, u, v in ((left, bottom, u0, v0), (right, bottom, u1, v0),
                                     (right, top, u1, v1), (left, top, u0, v1)):
                    glTexCoord2f(u, v)
                    glVertex3f(x + cx * self.size, y + cy * self.size, 0.0)
                glEnd()
        finally:
            if visible:
                for name, value in INITIAL_ENVIRONMENT:
                    glTexEnvi(GL_TEXTURE_ENV, name, value)
                glBindTexture(GL_TEXTURE_2D, 0)
                glDisable(GL_TEXTURE_2D)

    def _on_screen(self, mode: Any) -> float:
        """Pixels per unit of the node's coordinates at its origin"""
        viewport = getattr(mode, 'getViewport', None)
        height = float(viewport()[3]) if callable(viewport) else float(glGetIntegerv(GL_VIEWPORT)[3])
        if getattr(mode, 'shader_mode', False):
            return pillowtext.pixels_per_unit(mode.matrix, mode.getProjection(), height)
        # The fixed-function stacks; read back column by column, which is
        # the engine's row-vector order
        return pillowtext.pixels_per_unit(glGetDoublev(GL_MODELVIEW_MATRIX),
                                          glGetDoublev(GL_PROJECTION_MATRIX), height)

    def _buffers(self, atlas: TextAtlas, placed: list[tuple[Placement, Any, float, float]]
                 ) -> list[_Drawn]:
        """For each page `placed` lines are on, its vertex count and buffers,
        kept while the lines and their places are the same"""
        key = (self.size,) + tuple((p, x, y) for p, _box, x, y in placed)
        found = atlas.layouts.get(key)
        if found is not None:
            atlas.layouts.move_to_end(key)
            return found
        by_page: dict[int, list[tuple[Placement, Any, float, float]]] = {}
        for each in placed:
            by_page.setdefault(each[0].page, []).append(each)
        made = []
        for page, quads in by_page.items():
            positions, texcoords = [], []
            for where, (left, right, bottom, top), x, y in quads:
                u0, v0, u1, v1 = where.texcoords(atlas.page_size)
                corners = [(left, bottom, u0, v0), (right, bottom, u1, v0),
                           (right, top, u1, v1), (left, top, u0, v1)]
                for index in (0, 1, 2, 0, 2, 3):
                    cx, cy, u, v = corners[index]
                    positions.append((x + cx * self.size, y + cy * self.size, 0.0))
                    texcoords.append((u, v))
            count = len(positions)
            buffers = (VBO(np.array(positions, 'f')),
                       VBO(np.tile(np.array((0.0, 0.0, 1.0), 'f'), (count, 1))),
                       VBO(np.array(texcoords, 'f')))
            made.append(_Drawn(page, count, buffers))
        atlas.layouts[key] = made
        while len(atlas.layouts) > KEPT_LAYOUTS:
            atlas.layouts.popitem(last=False)
        return made

    @staticmethod
    def _draw(mode: Any, drawn: _Drawn) -> None:
        from OpenGLContext.scenegraph.geometryarrays import (  # noqa: PLC0415 imports GL state helpers
            GeometryArrays, render_geometry,
        )
        positions, normals, texcoords = drawn.buffers
        render_geometry(mode, GeometryArrays.separate(
            count=drawn.count, positions=positions, normals=normals, texcoords=texcoords,
        ), owner=drawn, where='PillowTextFont', solid=False)


class _PillowTextProvider(fontprovider.TTFFontProvider):
    """Makes a PillowTextFont for each FontStyle's face and size"""

    format = 'texture'
    shader_compatible = True

    def key(self, fontStyle: Any = None) -> Any:
        """The face and size a FontStyle names, and the FontLibrary files its families are"""
        if not fontStyle:
            return None
        from OpenGLContext.scenegraph.text import fontlibrary  # noqa: PLC0415 fontlibrary imports the context
        return (tuple(getattr(fontStyle, 'family', ()) or ()),
                str(getattr(fontStyle, 'style', '') or ''),
                float(getattr(fontStyle, 'size', 1.0) or 1.0),
                fontlibrary.key(fontStyle))

    def create(self, fontStyle: Any, mode: Any = None) -> Any:
        """A new font for `fontStyle`"""
        made = PillowTextFont(fontStyle, pillowtext.face(fontStyle, mode))
        self.addFont(fontStyle, made)
        return made


PillowTextProvider = _PillowTextProvider()
PillowTextProvider.registerProvider(PillowTextProvider)
