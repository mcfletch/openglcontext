"""Panoramic image-cube Background node
"""
import os
from typing import Any, Optional

from numpy import array, concatenate, cross, dot
from OpenGL.arrays import vbo
from OpenGL.GL import *
from OpenGL.GL import shaders
from OpenGL.GL import glBindVertexArray, glGenVertexArrays
from vrml import field, fieldtypes, node
from vrml.vrml97 import nodetypes
from vrml.x3d import binding

from OpenGLContext import contextresources, texture
from OpenGLContext.passes import glstate
from OpenGLContext.scenegraph import bindable, imagetexture
from OpenGLContext.scenegraph.vertexsemantics import LOC_POSITION, LOC_TEXCOORD


#: ``vbo.VBO`` types as ``None``: PyOpenGL binds the name late, to whichever of
#: the accelerated and the pure-Python class it loaded.
VBO: Any = vbo.VBO

#: Where the faces' buffers and textures are kept in the pass's cache: a key of
#: its own, as `Background` mixes this class with the sky sphere's.
CACHE_KEY = 'cube_faces'


class URLField( fieldtypes.MFString ):
    """Cube-background URL field which forwards to the corresponding ImageTexture node's url
    """
    fieldType = "MFString"
    def fset( self, client: Any, value: Any, notify: int = 1 ) -> Any:
        value = super( URLField, self).fset( client, value, notify )
        imageObject = getattr(client, self.name[:-3])
        imageObject.url = value
        return value
    def fdel( self, client: Any, notify: int = 1 ) -> Any:
        value = super( URLField, self).fdel( client, notify )
        imageObject = getattr(client, self.name[:-3])
        delattr( imageObject, 'url')
        delattr( imageObject, 'components' )
        return value

#: Each side: the direction it is looked at along from the origin, and the view
#: up with which X3D shows its image upright (19775-1, Background).
FACES: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    'front': ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    'back': ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    'left': ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    'right': ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    'top': ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    'bottom': ((0.0, -1.0, 0.0), (0.0, 0.0, -1.0)),
}
#: The corners of a side, as texture coordinates of its image.
CORNERS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
#: The layouts a side's image may be in: X3D's, or a GL cube map face's, which
#: seen from inside the cube is X3D's mirrored left to right on the four sides
#: and top to bottom on the top and bottom.
LAYOUTS = ('X3D', 'CUBEMAP')
SHADER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'shaders')

#: The faces' program, per GL context that compiled one.
_programs: dict[Optional[contextresources.ContextKey], Any] = {}
#: The six faces' vertex buffer and vertex array, per GL context and face layout.
_quads: dict[tuple[Optional[contextresources.ContextKey], str], tuple[Any, int]] = {}


@contextresources.on_context_lost
def _drop_context_resources() -> None:
    """Forget the program and the faces of the context now being destroyed"""
    key = contextresources.context_key()
    _programs.pop(key, None)
    for found in [found for found in _quads if found[0] == key]:
        del _quads[found]


def _faces(layout: str) -> tuple[Any, int]:
    """The vertex buffer and vertex array of the six faces in `layout`, for the
    current context"""
    key = (contextresources.context_key(), layout)
    found = _quads.get(key)
    if found is None:
        quads = [concatenate(face_quad(side, layout), axis=1) for side in FACES]
        found = _quads[key] = (VBO(concatenate(quads).astype('f')), glGenVertexArrays(1))
    return found


def face_quad(side: str, layout: str = 'X3D') -> tuple[Any, Any]:
    """(positions, texcoords) of a side's four corners, on the cube of half-size 1,
    for an image in `layout` (:data:`LAYOUTS`)"""
    looking, up = (array(axis, 'f') for axis in FACES[side])
    right = cross(looking, up)
    positions = array([looking + (2 * u - 1) * right + (2 * v - 1) * up
                       for u, v in CORNERS], 'f')
    texcoords = array(CORNERS, 'f')
    if layout == 'CUBEMAP':
        mirrored = 1 if side in ('top', 'bottom') else 0
        texcoords[:, mirrored] = 1.0 - texcoords[:, mirrored]
    elif layout != 'X3D':
        raise ValueError('A face layout is one of %s, not %r' % (LAYOUTS, layout))
    return positions, texcoords


def has_image(side: Any) -> bool:
    """Whether a side has an image loaded to draw"""
    return bool(side is not None and getattr(side, 'components', 0)
                and getattr(side, 'image', None) is not None)


def _program() -> tuple[Any, int, int]:
    """The faces' program and its two uniforms, for the current context"""
    key = contextresources.context_key()
    found: Optional[tuple[Any, int, int]] = _programs.get(key)
    if found is None:
        sources = []
        for name in ('background_faces.vert', 'background_faces.frag'):
            with open(os.path.join(SHADER_DIR, name)) as stream:
                sources.append(stream.read())
        program = shaders.compileProgram(
            shaders.compileShader(sources[0], GL_VERTEX_SHADER),
            shaders.compileShader(sources[1], GL_FRAGMENT_SHADER))
        found = (program, glGetUniformLocation(program, 'mvpMatrix'),
                 glGetUniformLocation(program, 'faceImage'))
        _programs[key] = found
    return found


class _CubeBackground( object ):
    """Six images on a cube around the viewer, each side drawn once it has one

    Each side's image is turned as X3D says (:data:`FACES`); a transparent
    part of one, or a side with none, shows what was drawn before it.
    """
    right = field.newField('right', 'SFNode', default=imagetexture.ImageTexture)
    top = field.newField('top', 'SFNode', default=imagetexture.ImageTexture)
    back = field.newField('back', 'SFNode', default=imagetexture.ImageTexture)
    left = field.newField('left', 'SFNode', default=imagetexture.ImageTexture)
    front = field.newField('front', 'SFNode', default=imagetexture.ImageTexture)
    bottom = field.newField('bottom', 'SFNode', default=imagetexture.ImageTexture)
    bound = bindable.bound_field()

    rightUrl = URLField( 'rightUrl')
    topUrl = URLField( 'topUrl')
    backUrl = URLField( 'backUrl')
    leftUrl = URLField( 'leftUrl')
    frontUrl = URLField( 'frontUrl')
    bottomUrl = URLField( 'bottomUrl')

    def hasImages( self ) -> bool:
        """Whether any side has an image to draw"""
        return any(has_image(getattr(self, side)) for side in FACES)

    def Render( self, mode: Any, clear: int = 1 ) -> int:
        """Draw the sides that have images; 1 where one was drawn, else 0

        `clear` clears the buffers first. The depth buffer is neither read
        nor written, so the scene is drawn over the sides.
        """
        if mode.passCount != 0:
            return 0
        render_data = mode.cache.getData(self, CACHE_KEY)
        if render_data is None:
            render_data = self.compile(mode)
        if clear:
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)
        textures, layout = render_data
        if not textures:
            return 0
        vertices, vao = _faces(layout)
        program, mvp_location, image_location = _program()
        matrix = dot(mode.matrix, mode.projection).astype('f')
        blending = (int(glGetIntegerv(GL_BLEND_SRC_RGB)), int(glGetIntegerv(GL_BLEND_DST_RGB)),
                    int(glGetIntegerv(GL_BLEND_SRC_ALPHA)), int(glGetIntegerv(GL_BLEND_DST_ALPHA)))
        glActiveTexture(GL_TEXTURE0)
        with glstate.program(program), glstate.disabled(GL_DEPTH_TEST, GL_CULL_FACE), \
                glstate.enabled(GL_BLEND):
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glDepthMask(GL_FALSE)
            glUniformMatrix4fv(mvp_location, 1, GL_FALSE, matrix)
            glUniform1i(image_location, 0)
            glBindVertexArray(vao)
            try:
                with vertices:
                    glEnableVertexAttribArray(LOC_POSITION)
                    glEnableVertexAttribArray(LOC_TEXCOORD)
                    glVertexAttribPointer(LOC_POSITION, 3, GL_FLOAT, GL_FALSE, 20, vertices)
                    glVertexAttribPointer(LOC_TEXCOORD, 2, GL_FLOAT, GL_FALSE, 20, vertices + 12)
                    for index, tex in textures:
                        glBindTexture(GL_TEXTURE_2D, tex.texture)
                        glDrawArrays(GL_TRIANGLE_FAN, index * 4, 4)
            finally:
                glBindTexture(GL_TEXTURE_2D, 0)
                glBindVertexArray(0)
                glDepthMask(GL_TRUE)
                glBlendFuncSeparate(*blending)
        return 1

    def compile( self, mode: Any ) -> Any:
        """(textures, face layout): a texture for each side with an image, by its
        place among the faces, kept until a side changes"""
        textures = []
        layout = str(getattr(self, 'faceLayout', 'X3D'))
        for index, side in enumerate(FACES):
            source = getattr(self, side)
            if has_image(source):
                tex = texture.Texture(source.image)
                glBindTexture(GL_TEXTURE_2D, tex.texture)
                # Mipmapped: a side is seen at every scale as the view turns
                glGenerateMipmap(GL_TEXTURE_2D)
                for parameter, value in ((GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
                                         (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE),
                                         (GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR),
                                         (GL_TEXTURE_MAG_FILTER, GL_LINEAR)):
                    glTexParameteri(GL_TEXTURE_2D, parameter, value)
                glBindTexture(GL_TEXTURE_2D, 0)
                textures.append((index, tex))
        render_data = (textures, layout)
        holder = mode.cache.holder(self, render_data, CACHE_KEY)
        for node_, name in self.sideDependencies():
            holder.depend(node_, name)
        return render_data

    def sideDependencies( self ) -> list[tuple[Any, str]]:
        """(node, field name) for each field the drawn sides are read from"""
        found: list[tuple[Any, str]] = []
        if hasattr(type(self), 'faceLayout'):
            found.append((self, 'faceLayout'))
        for side in FACES:
            found.append((self, side + 'Url'))
            if isinstance(getattr(type(self), side, None), field.Field):
                found.append((self, side))
            source = getattr(self, side)
            if source is not None and hasattr(type(source), 'image'):
                found.append((source, 'image'))
        return found

class CubeBackground( _CubeBackground, binding.Bindable, nodetypes.Background, nodetypes.Children, node.Node  ):
    """Image-cube Background node

    The CubeBackground node implements 1/2 of the VRML97
    background node, particularly the image-cube
    functionality represented by the rightUrl, topUrl,
    backUrl, leftUrl, frontUrl, and bottomUrl fields.

    Fields of note within the CubeBackground object:

        back, front, left, right, top, bottom -- texture
            objects applied to the geometry of the cube.
            Any node which supports the texture API
            should work for these attributes
            
        backUrl, frontUrl, leftUrl, rightUrl, topUrl,
        bottomUrl -- texture urls (MFStrings) used to
            load the images above

        faceLayout -- ``"X3D"``, each image turned as X3D's
            Background turns it, or ``"CUBEMAP"``, each laid out as
            a GL cube map face (an IBL environment's, a glTF sky's)
    """
    PROTO = 'CubeBackground'
    faceLayout = field.newField('faceLayout', 'SFString', 1, 'X3D')
    
