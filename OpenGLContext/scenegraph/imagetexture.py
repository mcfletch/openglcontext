"""ImageTexture and MMImageTexture nodes using PIL"""

import contextlib
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.error import GLError
from OpenGLContext import texture, context
from OpenGLContext.scenegraph.sampler import apply_sampler, sampler_of
from OpenGLContext.loaders import background, basisu

from PIL import Image

# from vrml import cache
from vrml.vrml97 import basenodes, nodetypes
from vrml.x3d import loadsensor
from vrml import node, field, protofunctions, fieldtypes
from io import BytesIO
import logging

log = logging.getLogger(__name__)


class _Texture(nodetypes.Texture, node.Node):
    """Mix-in for rendering static image textures"""

    #: Whether texture coordinate (0, 0) is the image's upper left, as in glTF,
    #: rather than its lower left, as in VRML97 and X3D.
    TOP_FIRST: ClassVar[bool] = False

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
        """Compile (store our image in an OpenGL texture)

        Under a shader the texture's wrap modes and filters are set here, from
        `repeatS`/`repeatT` or the node's `TextureProperties`: the PBR pass
        binds the texture object and does not call :meth:`render`.
        """
        tex = self.createTexture(self.image, mode=mode)
        # cache this for later use...
        holder = mode.cache.holder(self, tex)
        holder.depend(self, "image")
        for name in ("repeatS", "repeatT", "textureProperties"):
            if isinstance(getattr(type(self), name, None), field.Field):
                holder.depend(self, name)
        if tex is not None:
            self.components = tex.components
            if getattr(mode, "shader_mode", False):
                apply_sampler(tex, sampler_of(self, self.imageSize()))
        else:
            self.components = 0
        return tex

    def imageSize(self) -> Optional[tuple[int, int]]:
        """The image's (width, height) in texels; None where there is no image"""
        size = getattr(self.image, 'size', None)
        return (int(size[0]), int(size[1])) if size else None

    def createTexture(self, image: Any, mode: Any = None) -> Any:
        """Create a new texture-holding object

        Uses the TextureCache to try to minimise the
        number of textures created. A Basis Universal image is a
        :class:`~OpenGLContext.texture.BasisTexture` of its own.
        """
        if isinstance(image, basisu.BasisImage):
            return mode.context.textureCache.getTexture(
                image,
                texture.BasisTexture,
                mode=mode,
                repeating=(self.repeatS or self.repeatT),
                atlasable=False,
                topFirst=self.TOP_FIRST,
            )
        return mode.context.textureCache.getTexture(
            image,
            texture.Texture,
            mode=mode,
            repeating=(self.repeatS or self.repeatT),
            atlasable=not getattr(mode, "shader_mode", False),
            topFirst=self.TOP_FIRST,
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

    def hasAlpha(self) -> bool:
        """Whether the image this node holds has an alpha channel, read without GL

        A PIL image with an alpha band or a transparent palette entry, a Basis
        Universal file storing alpha, or an SFImage of two or four components.
        False until an image is loaded.
        """
        image = self.image
        if isinstance(image, basisu.BasisImage):
            return image.has_alpha
        if isinstance(image, Image.Image):
            return 'A' in image.getbands() or 'transparency' in image.info
        try:
            return len(image) > 2 and int(image[2]) in (2, 4)
        except TypeError:
            return False

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


def decode_picture(file: Any, baseURL: str) -> Any:
    """The picture in `file`, decoded now

    Decoded here rather than by whoever first looks at the pixels: PIL reads
    lazily, so an image left undecoded holds the file it came from open --
    six of them for a cubemap -- and does its reading on the thread that
    draws. A Basis Universal file (KTX 2 or ``.basis``) is a
    :class:`~OpenGLContext.loaders.basisu.BasisImage`, which raises the
    extra to install where opengl_basisu is not.
    """
    return decode_image_bytes(file.read())


def decode_image_bytes(data: bytes) -> Any:
    """A PIL image, or a Basis Universal image, of a picture file's bytes"""
    if basisu.is_basis(data):
        return basisu.open_image(data)
    image = Image.open(BytesIO(data))
    image.load()
    return image


#: How much of a URL a log line carries: a ``data:`` URL holds its whole image.
URL_LOG_LENGTH = 96


def brief(url: Any) -> str:
    """A URL, or each of several, cut to :data:`URL_LOG_LENGTH` for a log line"""
    if not isinstance(url, (bytes, str)):
        return '[%s]' % ', '.join(brief(entry) for entry in url)
    text = url.decode('utf-8', 'replace') if isinstance(url, bytes) else url
    return text if len(text) <= URL_LOG_LENGTH else text[:URL_LOG_LENGTH] + '...'


def _is_data_url(url: Any) -> bool:
    text = url.decode('utf-8', 'replace') if isinstance(url, bytes) else str(url)
    return text[:5].lower() == 'data:'


def _open(single: Any, baseURI: Any) -> Optional[tuple[str, str, Any]]:
    """(URL, file name, open file) for one entry of a url; None for one that names nothing

    A ``data:`` URL holds its own bytes, so it reads no file and asks no
    host, wherever its document came from. Its size is held to the
    resolver's limit before it is decoded.
    """
    from OpenGLContext.loaders import resolver
    from OpenGLContext.loaders.loader import Loader

    if _is_data_url(single):
        text = single.decode('utf-8', 'replace') if isinstance(single, bytes) else str(single)
        try:
            data = resolver.decode_data_uri(text, resolver.DEFAULT_MAX_RESOURCE_BYTES)
        except ValueError as err:
            raise IOError(str(err)) from err
        return 'data:', '', BytesIO(data)
    result = Loader(single, baseURL=baseURI)
    if not result:
        return None
    baseURL, filename, file, _headers = result
    return baseURL, filename, file


def load_first(node: Any, url: Any, decode: Callable[[Any, str], Any]) -> Optional[tuple[Any, str, str]]:
    """The first entry of `url` that fetches and decodes: (decoded, its URL, its file name)

    Each entry is read relative to `node`'s root's base URL, or from the
    entry itself where it is a ``data:`` URL, and handed, as an open file, to
    ``decode(file, url)``. An entry that cannot be fetched, or whose bytes
    `decode` raises on -- truncated, another format, or a few dozen bytes
    declaring a billion pixels -- is reported and the next is tried. None
    where none is read.
    """
    baseNode = protofunctions.root(node)
    baseURI = baseNode.baseURI if baseNode else None
    for single in ([url] if isinstance(url, (bytes, str)) else list(url)):
        try:
            opened = _open(single, baseURI)
        except IOError as err:
            log.warning("Unable to fetch the image at %s: %s", brief(single), brief(str(err)))
            continue
        if opened is None:
            continue
        baseURL, filename, file = opened
        try:
            with contextlib.closing(file):
                decoded = decode(file, baseURL)
        except Exception as err:
            log.warning("Unable to decode the image at %s: %s", brief(single), err)
            continue
        return decoded, baseURL, filename
    return None


class URLRead:
    """A texture node whose ``url`` (an :class:`ImageURLField`) is read in the background

    The node gives ``loadBackground(url, contexts)``, which reads the first
    entry that decodes, and names in :attr:`READ_FIELD` the field that read
    fills, so a copy made before it was filled reads the url itself.
    """

    #: The field the read fills.
    READ_FIELD = ' image'
    #: The read's imports, made on the thread that asks for it.
    prepareRead: Callable[[], None] = staticmethod(prepare_image_loading)

    def requestImage(self) -> None:
        """Read what `url` names, in the background"""
        node: Any = self
        loadsensor.set_load_state(node, loadsensor.LOADING)
        background.load_in_background(
            node.url,
            node.loadBackground,
            node.url,
            context.Context.allContexts,
            prepare=self.prepareRead,
        )

    def copy(self, copier: Any = None) -> Any:
        """A copy reading its own url: each instance of a prototype is a
        copy of its body, made before the body's read has finished"""
        made = super().copy(copier)  # type: ignore[misc]  # a node class follows this one
        if made is not self and made.url and made.__dict__.get(self.READ_FIELD) is None:
            made.requestImage()
        return made


class ImageURLField(fieldtypes.MFString):
    """Field for managing interactions with an Image's URL value

    Its node is a :class:`URLRead`.
    """

    fieldType = "MFString"

    def __set__(self, client: Any, value: Any, notify: bool = True) -> Any:
        """Set the client's URL, then try to load the image"""
        value = super(ImageURLField, self).fset(client, value, notify=True)
        client.requestImage()
        return value

    fset = __set__

    def fdel(self, client: Any, notify: int = 1) -> Any:
        """Delete the client's URL, which should delete the image as well"""
        value = super(ImageURLField, self).fdel(client, notify)
        del client.image
        return value

    __delete__ = fdel


class ImageTexture(URLRead, _Texture, basenodes.ImageTexture):
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
        found = load_first(self, url, decode_picture)
        if found is None:
            loadsensor.set_load_state(self, loadsensor.FAILED)
            log.warning(
                """Unable to load any image from the url %s for the node %s""",
                brief(url),
                str(self),
            )
            return None
        image, baseURL, filename = found
        image.info["url"] = baseURL
        image.info["filename"] = filename
        return self.setImage(image, contexts)

    def setImage(self, image: Any, contexts: Sequence[Any] = ()) -> None:
        """Set PIL image as our new image

        image -- open( ) PIL file with info['url'] and info['filename'] defined
        """
        self.image = image
        self.components = -1
        loadsensor.set_load_state(self, loadsensor.LOADED)
        for c_reference in contexts:
            c = c_reference()
            if c:
                c.triggerRedraw(1)
        return

    def loadFromData(self, data: bytes, url: Any = None) -> Any:
        """Load (synchronously) from given data"""
        if url is None:
            url = "memory:%s" % (hash(data),)
        try:
            image = decode_image_bytes(data)
        except Exception as err:
            # As in loadBackground: bytes that are not the image they claim to
            # be are a warning and no texture, whatever the decoder made of them.
            log.warning("Unable to decode the image from %s: %s", url, err)
            return None
        self.image = image
        self.image.info["url"] = str(url)
        self.image.info["file"] = "memory"
        self.components = -1
        loadsensor.set_load_state(self, loadsensor.LOADED)
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


def sfimage_pixels(image: Any, owner: Any = None) -> Optional[tuple[int, int, int, bytes]]:
    """(components, width, height, bytes) of an SFImage, bottom row first; None where it is not one

    `owner` is named in the warning a malformed image logs.
    """
    if len(image) < 4:
        return None
    width, height, componentCount = [int(x) for x in image[:3]]
    if not componentCount:
        log.warning("bad component count in pixeltexture %s", owner)
        return None
    if (not width) or (not height):
        log.warning("0-size dimension in pixeltexture %s", owner)
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
    data = b"".join(
        [struct.pack(b">L", int(item))[-componentCount:] for item in image[3:]]
    )
    return componentCount, width, height, data


class PixelTexture(_Texture, basenodes.PixelTexture):
    """PixelTexture, in-file node for small textures"""

    def imageSize(self) -> Optional[tuple[int, int]]:
        """The SFImage's (width, height) in texels; None where it has none"""
        image = self.image
        if image is None or len(image) < 3 or not (int(image[0]) and int(image[1])):
            return None
        return int(image[0]), int(image[1])

    def createTexture(self, image: Any, mode: Any = None) -> Any:
        """Create a new texture-holding object

        Uses the TextureCache to try to minimise the
        number of textures created
        """
        decoded = sfimage_pixels(image, self)
        if decoded is None:
            return None
        componentCount, width, height, data = decoded
        tex = texture.Texture()
        tex.store(
            componentCount,
            [0, GL_LUMINANCE, GL_LUMINANCE_ALPHA, GL_RGB, GL_RGBA][componentCount],
            width,
            height,
            data,
        )
        return tex
