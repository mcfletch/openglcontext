"""ImageTexture and MMImageTexture nodes using PIL"""

import contextlib
from typing import TYPE_CHECKING, Any, Optional, Sequence

from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.error import GLError
from OpenGLContext import texture, context
from OpenGLContext.loaders import background

from PIL import Image

# from vrml import cache
from vrml.vrml97 import basenodes, nodetypes
from vrml import node, field, protofunctions, fieldtypes
from io import BytesIO
import logging

log = logging.getLogger(__name__)


class _Texture(nodetypes.Texture, node.Node):
    """Mix-in for rendering static image textures"""

    minFilter = field.newField(" minFilter", "SFInt32", 0, GL_NEAREST)
    magFilter = field.newField(" magFilter", "SFInt32", 0, GL_NEAREST)
    components = field.newField(" components", "SFInt32", 1, 0)

    if TYPE_CHECKING:
        # What this mix-in needs of the node it is mixed into, declared for a
        # checker and nothing else: the image and the two repeat flags are
        # VRML97 fields of the concrete texture nodes, and declaring them here
        # as anything but a hint would register a second copy of each field.
        image: Any
        repeatS: Any
        repeatT: Any

    def compile(self, mode: Any = None) -> Any:
        """Compile (store our image in an OpenGL texture)"""
        tex = self.createTexture(self.image, mode=mode)
        # cache this for later use...
        holder = mode.cache.holder(self, tex)
        holder.depend(self, "image")
        if tex is not None:
            self.components = tex.components
        else:
            self.components = 0
        return tex

    def createTexture(self, image: Any, mode: Any = None) -> Any:
        """Create a new texture-holding object

        Uses the TextureCache to try to minimise the
        number of textures created
        """
        return mode.context.textureCache.getTexture(
            image,
            texture.Texture,
            mode=mode,
            repeating=(self.repeatS or self.repeatT),
            atlasable=not getattr(mode, "shader_mode", False),
        )

    def render(
        self,
        visible: int = 1,
        lit: int = 1,
        mode: Any = None,  # the renderpass object for which we compile
    ) -> Optional[int]:
        """Called by Shape before rendering associated geometry

        visible -- whether a visible rendering pass,
            if not, no normals, colours, or textures
        lit -- whether lighting is enabled, if not, no normals

        returns whether this is a transparent texture
            0 if non-transparent, but a valid texture
            1 if transparent
            None if not yet a valid texture
        """
        if not visible:
            return None
        tex = self.cached(mode)
        if tex:
            if mode.transparent:
                # there is an alpha component...
                glEnable(GL_BLEND)
                glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            elif self.transparent(mode):
                return 1
            shader_mode = getattr(mode, "shader_mode", False)
            if shader_mode:
                tex.bind()
            else:
                tex()
            # now the stuff not related to the texture in particular
            # i.e. the "image" half of the image texture
            clamp = GL_CLAMP_TO_EDGE if shader_mode else GL_CLAMP
            glTexParameteri(
                GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT if self.repeatS else clamp
            )
            glTexParameteri(
                GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT if self.repeatT else clamp
            )
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, self.magFilter)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, self.minFilter)
            ### XXX something get's messed up heavily if we actually report the alpha channel's existence :(
            return 0
        return 0

    def renderPost(self, mode: Any = None) -> None:
        """Called after rendering geometry to disable the texture

        Note: this does *not* disable the blend mode we established, it
        is left to the mode's post-rendering code to do this!  As a result,
        if you use this code outside of a scenegraph you will need to add
        a call to reestablish the blending parameters you desire.

        Under a shader there is nothing to undo: the fixed-function texture
        unit and the texture matrix stack that this resets are what a core
        profile leaves out, and a sampler reads from whatever the next shape
        binds.
        """
        if getattr(mode, "shader_mode", False):
            return
        try:
            glDisable(GL_TEXTURE_2D)
            glMatrixMode(GL_TEXTURE)
            try:
                glLoadIdentity()
            finally:
                glMatrixMode(GL_MODELVIEW)
        except GLError:
            if glGetBooleanv(GL_TEXTURE_2D):
                log.error("""Unable to disable GL_TEXTURE_2D for node %s""", self)

    def cached(self, mode: Any = None) -> Any:
        """Retrieve cached texture for this mode"""
        try:
            if not self.image:
                return None
        except ValueError:
            if not len(self.image):
                return None
        tex = mode.cache.getData(self)
        if not tex:
            tex = self.compile(mode=mode)
        return tex

    def transparent(self, mode: Any = None) -> int:
        """Does this texture have an alpha component?"""
        tex = self.cached(mode)
        if tex:
            return tex.components in (2, 4)
        return 0

    @classmethod
    def forTexture(cls, tex: Any, mode: Any) -> "_Texture":
        """Create a fake image texture node for the given on-card texture object"""
        instance = cls(
            image=Image.new(
                texture.NumpyAdapter.shapeToMode(tex.components), (1, 1), "#ff00ff"
            )
        )
        mode.cache.holder(instance, tex)
        return instance


class PILImage(field.Field):
    """Simple field-type for holding PIL image objects"""

    @classmethod
    def defaultDefault(cls) -> Any:
        """Get a default PIL image object"""
        return Image.new("RGB", (1, 1), (255, 0, 0))


def prepare_image_loading() -> None:
    """Make a background image load's imports, here on the calling thread.

    The fetch and the decode run on a loader thread, and a first-use import
    taken there is one nothing can interrupt -- see
    :mod:`OpenGLContext.loaders.background`.  PIL imports a module per image
    format the first time it opens or saves anything, and the fetch itself
    needs the loader, so both are made here.
    """
    import OpenGLContext.loaders.loader
    Image.init()


class ImageURLField(fieldtypes.MFString):
    """Field for managing interactions with an Image's URL value"""

    fieldType = "MFString"

    def __set__(self, client: Any, value: Any, notify: bool = True) -> Any:
        """Set the client's URL, then try to load the image"""
        value = super(ImageURLField, self).fset(client, value, notify=True)
        background.load_in_background(
            value,
            client.loadBackground,
            value,
            context.Context.allContexts,
            prepare=prepare_image_loading,
        )
        return value

    fset = __set__

    def fdel(self, client: Any, notify: int = 1) -> Any:
        """Delete the client's URL, which should delete the image as well"""
        value = super(ImageURLField, self).fdel(client, notify)
        del client.image
        return value

    __delete__ = fdel


class ImageTexture(_Texture, basenodes.ImageTexture):
    """A texture loaded from an image file"""

    image = PILImage(" image", 1, None)
    url = ImageURLField("url", 1, list)

    def loadBackground(self, url: Any, contexts: Sequence[Any] = ()) -> Any:
        """Load an image from the given url in the background

        url -- SF or MFString URL to load relative to the
            node's root's baseURL

        On success:
            Sets the resulting PIL image to the
            client's image property (triggering an un-caching
            and re-compile if there was a previous image).

            if contexts, iterate through the list calling
            context.triggerRedraw(1)
        """
        from OpenGLContext.loaders.loader import Loader

        baseNode = protofunctions.root(self)
        baseURI = baseNode.baseURI if baseNode else None
        for single in ([url] if isinstance(url, (bytes, str)) else list(url)):
            try:
                result = Loader(single, baseURL=baseURI)
            except IOError as err:
                log.warning("Unable to fetch the image at %s: %s", single, err)
                continue
            if not result:
                continue
            baseURL, filename, file, headers = result
            try:
                with contextlib.closing(file):
                    image = Image.open(file)
                    # Decoded here rather than by whoever first looks at the
                    # pixels: PIL reads lazily, so an image left undecoded
                    # holds the file it came from open -- six of them for a
                    # cubemap -- and does its reading on the thread that draws.
                    image.load()
            except Exception as err:
                # Whatever a decoder makes of bytes that are not the image they
                # claim to be: truncated, another format, or a few dozen bytes
                # declaring a billion pixels, which Pillow refuses outright. One
                # unreadable texture costs the texture, and the world it is in
                # goes on being drawn -- so the next url in the list is tried,
                # a file that does not decode having not succeeded.
                log.warning("Unable to decode the image at %s: %s", single, err)
                continue
            image.info["url"] = baseURL
            image.info["filename"] = filename
            return self.setImage(image, contexts)

        # should set client.image to something here to indicate
        # failure to the user.
        log.warning(
            """Unable to load any image from the url %s for the node %s""",
            url,
            str(self),
        )
        return None

    def setImage(self, image: Any, contexts: Sequence[Any] = ()) -> None:
        """Set PIL image as our new image

        image -- open( ) PIL file with info['url'] and info['filename'] defined
        """
        self.image = image
        self.components = -1
        for c_reference in contexts:
            c = c_reference()
            if c:
                c.triggerRedraw(1)
        return

    def loadFromData(self, data: bytes, url: Any = None) -> Any:
        """Load (synchronously) from given data"""
        fh = BytesIO(data)
        if url is None:
            url = "memory:%s" % (hash(data),)
        try:
            image = Image.open(fh)
            image.load()
        except Exception as err:
            # As in loadBackground: bytes that are not the image they claim to
            # be are a warning and no texture, whatever the decoder made of them.
            log.warning("Unable to decode the image from %s: %s", url, err)
            return None
        self.image = image
        self.image.info["url"] = str(url)
        self.image.info["file"] = "memory"
        self.components = -1
        return self.image


class MMImageTexture(ImageTexture):
    """Mip-mapped version of ImageTexture

    Only significant differences are the use of
    the MMTexture class instead of Texture and the
    default for minFilter being GL_LINEAR_MIPMAP_NEAREST
    (which allows you to actually see the effects of
    mip-mapping).
    """

    PROTO = "MMImageTexture"
    minFilter = field.newField(
        "minFilter",
        "SFInt32",
        0,
        GL_LINEAR_MIPMAP_NEAREST,
    )

    def createTexture(self, image: Any, mode: Any = None) -> Any:
        """Create a new texture-holding object"""
        if image:
            return mode.context.textureCache.getTexture(image, texture.MMTexture)
        else:
            return None


class PixelTexture(_Texture, basenodes.PixelTexture):
    """PixelTexture, in-file node for small textures"""

    def createTexture(self, image: Any, mode: Any = None) -> Any:
        """Create a new texture-holding object

        Uses the TextureCache to try to minimise the
        number of textures created
        """
        # basically just the interpretation of an SFImage
        # field as a texture...
        if len(image) < 4:
            # don't have any components...
            return None
        width, height, componentCount = [int(x) for x in image[:3]]
        if not componentCount:
            log.warning("bad component count in pixeltexture %s", self)
            return None
        if (not width) or (not height):
            log.warning("0-size dimension in pixeltexture %s", self)
            return None
        if len(image) != width * height + 3:
            log.warning(
                "PixelTexture has incorrect image size, expected %s items (%s*%s)+3, got %s",
                width * height + 3,
                width,
                height,
                len(image),
            )
            return None
        import struct

        imageBody = image[3:]
        data = b"".join(
            [struct.pack(b">L", item)[-componentCount:] for item in imageBody]
        )
        tex = texture.Texture()
        tex.store(
            componentCount,
            [0, GL_LUMINANCE, GL_LUMINANCE_ALPHA, GL_RGB, GL_RGBA][componentCount],
            width,
            height,
            data,
        )
        return tex
