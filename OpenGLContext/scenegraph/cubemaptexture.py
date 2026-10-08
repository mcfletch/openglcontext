"""X3D's CubeMapTexturing: six images on the faces of a cube, read by direction

A cube map texture is drawn through an appearance's ``texture`` field or a
``MultiTexture`` layer (:mod:`OpenGLContext.scenegraph.texturelayers`), where
the surface reads it along the world-space reflection of the view, and is an
``EnvironmentLight``'s ``diffuseTexture`` or ``specularTexture``
(:mod:`OpenGLContext.scenegraph.environmentlight`).

The faces are GL's: +X, -X, +Y, -Y, +Z, -Z. X3D names them front (+Z), back
(-Z), left (-X), right (+X), top (+Y) and bottom (-Y), and each image lies on
its face as a GL cube map face does: upright on the four sides seen from
outside the cube, the top's upper edge toward the back and the bottom's
toward the front.

- ``ComposedCubeMapTexture``: six 2D texture nodes, one a face. Faces of
  different sizes are resampled to the largest; the cube is made once all
  six have images.
- ``ImageCubeMapTexture``: the first of its ``url`` entries that reads as a
  cube map: a DDS or KTX cube map, or one picture of the six faces as a
  cross, a strip or 3x2 (:mod:`OpenGLContext.loaders.textureimages`).
- ``GeneratedCubeMapTexture``: the scene drawn from the shape wearing it
  (:mod:`OpenGLContext.passes.generatedtextures`).

:meth:`CubeMapTexture.faceImages` gives the six faces as arrays, which is
what an ``EnvironmentLight`` reads; :meth:`CubeMapTexture.cached` the GL cube
map, made the first time a frame draws it and kept in the context's cache
until a face or the sampler changes.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
from vrml import cache, field, node
from vrml.x3d import loadsensor
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph.imagetexture import ImageURLField, load_first
from OpenGLContext.scenegraph.texture3d import image_array, with_channels

__all__ = ['FACE_FIELDS', 'FACES_KEY', 'ComposedCubeMapTexture', 'CubeMapTexture',
           'FacesField', 'GeneratedCubeMapTexture', 'ImageCubeMapTexture', 'cube_faces']

log = logging.getLogger(__name__)

#: ComposedCubeMapTexture's field for each face, in GL's order.
FACE_FIELDS = ('rightTexture', 'leftTexture', 'topTexture', 'bottomTexture',
               'frontTexture', 'backTexture')
#: The names :class:`~OpenGLContext.texture.CubeTexture` gives the faces, in GL's order.
_GL_NAMES = ('+x', '-x', '+y', '-y', '+z', '-z')
#: The key a node's faces are kept under in vrml's cache.
FACES_KEY = 'cube-map-faces'


class FacesField(field.Field):
    """A field holding six decoded faces, or None"""

    fieldType = 'CubeFaces'

    @classmethod
    def defaultDefault(cls) -> Any:
        return None


def cube_faces(faces: list[np.ndarray]) -> list[np.ndarray]:
    """Six faces made square, one size and one channel count

    Each is resampled to the largest side among them; all have alpha where
    any has, and colour otherwise.
    """
    from PIL import Image  # noqa: PLC0415 only a cube of mixed faces needs it
    side = max(max(face.shape[:2]) for face in faces)
    alpha = any(face.shape[-1] in (2, 4) for face in faces)
    channels = 4 if alpha else 3
    found = []
    for face in faces:
        face = with_channels(face, channels)
        if face.shape[:2] != (side, side):
            face = np.asarray(Image.fromarray(np.ascontiguousarray(face)).resize(
                (side, side), Image.Resampling.BICUBIC))
        found.append(np.ascontiguousarray(face))
    return found


class CubeMapTexture(node.Node):
    """What the cube map nodes share: six faces, uploaded when drawn"""

    #: The node's fields its faces are made from, watched by the cache.
    FACE_SOURCES: tuple[str, ...] = ()

    def buildFaces(self) -> Optional[list[np.ndarray]]:
        """The six faces, worked out from the node's fields as they stand"""
        raise NotImplementedError

    def dependFaces(self, holder: Any) -> None:
        """Make ``holder`` clear when anything the faces are made from changes"""
        for name in self.FACE_SOURCES:
            holder.depend(self, name)

    def faceImages(self) -> Optional[list[np.ndarray]]:
        """The six ``(n, n, c)`` uint8 faces, top row first, in GL's order, or None

        Kept in vrml's cache until a field the faces are made from is set.
        """
        held = cache.CACHE.getData(self, FACES_KEY)
        if held is None:
            built = self.buildFaces()
            held = (None if built is None else cube_faces(built),)
            self.dependFaces(cache.CACHE.holder(self, held, FACES_KEY))
        found: Optional[list[np.ndarray]] = held[0]
        return found

    def hasAlpha(self) -> bool:
        """Whether the faces have an alpha channel"""
        faces = self.faceImages()
        return bool(faces) and faces[0].shape[-1] == 4

    def cached(self, mode: Any = None) -> Any:
        """The cube map in ``mode``'s context, or None before it has six faces"""
        tex = mode.cache.getData(self)
        if tex is not None:
            return tex
        faces = self.faceImages()
        if faces is None:
            return None
        from OpenGLContext.scenegraph.sampler import apply_sampler, sampler_of  # noqa: PLC0415 GL
        from OpenGLContext.texture import CubeTexture  # noqa: PLC0415 GL only when drawn
        tex = CubeTexture(dict(zip(_GL_NAMES, faces, strict=True)))
        apply_sampler(tex, sampler_of(self, faces[0].shape[:2]))
        holder = mode.cache.holder(self, tex)
        self.dependFaces(holder)
        holder.depend(self, 'textureProperties')
        return tex


class ComposedCubeMapTexture(CubeMapTexture, x3d.ComposedCubeMapTexture):
    """X3D's ComposedCubeMapTexture: a 2D texture node on each face"""

    FACE_SOURCES = FACE_FIELDS

    def dependFaces(self, holder: Any) -> None:
        super().dependFaces(holder)
        for name in FACE_FIELDS:
            child = getattr(self, name)
            if child and isinstance(getattr(type(child), 'image', None), field.Field):
                holder.depend(child, 'image')

    def buildFaces(self) -> Optional[list[np.ndarray]]:
        faces = []
        for name in FACE_FIELDS:
            pixels = image_array(getattr(self, name)) if getattr(self, name) else None
            if pixels is None:
                return None
            # image_array answers the bottom row first; a face's top row is first.
            faces.append(np.ascontiguousarray(pixels[::-1]))
        return faces


class ImageCubeMapTexture(CubeMapTexture, x3d.ImageCubeMapTexture):
    """X3D's ImageCubeMapTexture: a cube map read from one file"""

    FACE_SOURCES = ('faces',)
    faces = FacesField(' faces', 1, None)
    url = ImageURLField('url', 1, list)

    def buildFaces(self) -> Optional[list[np.ndarray]]:
        found: Optional[list[np.ndarray]] = self.faces
        return found

    def loadBackground(self, url: Any, contexts: Any = ()) -> Optional[list[np.ndarray]]:
        """Read the first of ``url`` that holds a cube map; its faces, or None

        Asks each of ``contexts`` (weak references) for a redraw once it has.
        """
        from OpenGLContext.loaders import textureimages  # noqa: PLC0415 only a load reads files
        found = load_first(self, url, lambda file, base: textureimages.read_cube(file.read()))
        if found is None:
            loadsensor.set_load_state(self, loadsensor.FAILED)
            log.warning('Unable to load a cube map from the url %s for %s', url, self)
            return None
        self.faces = found[0]
        loadsensor.set_load_state(self, loadsensor.LOADED)
        for reference in contexts:
            context = reference()
            if context:
                context.triggerRedraw(1)
        faces: list[np.ndarray] = found[0]
        return faces

    def _deleteFaces(self) -> None:
        self.faces = None

    #: What deleting ``url`` deletes (:class:`ImageURLField`): the faces.
    image = property(lambda self: self.faces, doc='The faces read from the url',
                     fdel=_deleteFaces)


class GeneratedCubeMapTexture(CubeMapTexture, x3d.GeneratedCubeMapTexture):
    """X3D's GeneratedCubeMapTexture: the scene drawn around the shape wearing it

    ``update`` is ``NONE`` (drawn once, the first time it is needed),
    ``NEXT_FRAME_ONLY`` (drawn once more, then ``NONE``) or ``ALWAYS``
    (drawn every frame); ``size`` is the width of a face in pixels. The
    render pass draws it (:mod:`OpenGLContext.passes.generatedtextures`).
    """

    def buildFaces(self) -> Optional[list[np.ndarray]]:
        return None

    def cached(self, mode: Any = None) -> Any:
        """The cube the pass draws the scene into, or None before its first drawing

        Asking is what tells the pass the texture is wanted, and where from.
        """
        generated = getattr(mode, 'generatedTexture', None)
        return generated(self) if generated is not None else None

    def hasAlpha(self) -> bool:
        return False
