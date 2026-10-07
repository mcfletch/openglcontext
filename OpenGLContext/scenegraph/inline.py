"""Inline: a scene read from a url and drawn in place

Each url is resolved against the inlining document under its policy
(:meth:`~OpenGLContext.loaders.loader._Loader.resolve`), the reader for it is
chosen as :class:`~OpenGLContext.loaders.sceneloader.SceneLoader` chooses one
(:func:`~OpenGLContext.loaders.formats.adapter_for`), and the Inline draws the
nodes that reader says its result is drawn as
(:meth:`~OpenGLContext.loaders.readers.SceneReader.nodes`): an X3D, VRML97 or
OBJ scene's children, a glTF model's group. The first url that reads is used.

The read happens on the loader pool. X3D's `load` field says whether the
scene is wanted: false leaves the Inline empty, and setting it true reads the
scene again. Setting `url` or `load` supersedes a read still under way.
"""
from collections.abc import Sequence
from typing import Any

from vrml.vrml97 import basenodes, nodetypes
from vrml import protofunctions, fieldtypes
from OpenGLContext import context
from OpenGLContext.loaders import background
import logging

log = logging.getLogger(__name__)


def prepare_scene_loading() -> None:
    """Make an inlined scene's imports, here on the calling thread.

    The scene is read on a loader thread, and a first-use import taken there
    is one nothing can interrupt -- see
    :mod:`OpenGLContext.loaders.background`.  Reading a scene means the reader
    for its format, which comes from the plugin registry, so every registered
    reader and the loader's handlers are imported here.

    The scene is built on that thread too, and its textures, shaders and
    panoramas submit their own loads from there, so their preparations are
    made here as well. An Inline inside it finds this one already made.
    """
    from OpenGLContext import plugins
    from OpenGLContext.loaders import formats  # noqa: F401 imported for the loader thread
    from OpenGLContext.loaders.loader import Loader
    from OpenGLContext.scenegraph import hdrbackground, imagetexture, shaders
    Loader.loadHandlers()
    for entry in plugins.Adapter.all():
        entry.load()
    background.prepare(imagetexture.prepare_image_loading,
                       shaders.prepare_shader_loading,
                       hdrbackground.prepare_panorama_loading)


class InlineURLField( fieldtypes.MFString ):
    """The url of an Inline: setting it reads the scene, where `load` allows"""
    fieldType = "MFString"
    def fset( self, client: Any, value: Any, notify: int = 1 ) -> Any:
        value = super(InlineURLField, self).fset( client, value, notify )
        client.reload()
        return value
    def fdel( self, client: Any, notify: int = 1 ) -> Any:
        """Delete the client's URL, which empties the Inline"""
        value = super( InlineURLField, self).fdel( client, notify )
        client.reload()
        return value


class InlineLoadField( fieldtypes.SFBool ):
    """X3D's `load`: whether the Inline reads its scene"""
    fieldType = "SFBool"
    def fset( self, client: Any, value: Any, notify: int = 1 ) -> Any:
        value = super(InlineLoadField, self).fset( client, value, notify )
        client.reload()
        return value


class Inline(basenodes.Inline):
    """X3D's (and VRML97's) Inline, reading any format a registered reader opens

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/networking.html#Inline
    """
    url = InlineURLField( 'url', 1, list )
    load = InlineLoadField( 'load', 1, True )
    #: The nodes the read scene is drawn as; empty until a read finishes.
    inlined: Sequence[Any] = ()

    def renderedChildren(
        self, types: Any = (nodetypes.Children, nodetypes.Rendering,)
    ) -> list[Any]:
        """The nodes the inlined scene is drawn as"""
        return list(self.inlined)

    def reload( self ) -> None:
        """Empty the Inline and, where `load` is true, read the scene from `url` again"""
        generation = self.__dict__['_generation'] = self.__dict__.get('_generation', 0) + 1
        self.inlined = ()
        url = list(self.__dict__.get('url', ()))
        if not url or not self.__dict__.get('load', True):
            return
        background.load_in_background(
            ' '.join(url), self.loadBackground, url, context.Context.allContexts, generation,
            prepare=prepare_scene_loading,
        )

    def loadBackground(
        self, url: Any, contexts: Sequence[Any] = (), generation: Any = None,
    ) -> None:
        """Read the first of `url` that reads, and draw it; runs on the loader pool

        url -- the urls to try, relative to the root's `baseURI`
        contexts -- weak references to the contexts to redraw once it is read
        generation -- the read this is, from :meth:`reload`; a result for a
            read since superseded is dropped
        """
        from OpenGLContext.loaders import formats
        from OpenGLContext.loaders.loader import Loader
        root = protofunctions.root(self)
        baseURI = root.baseURI if root else None
        for u in url:
            try:
                target = Loader.resolve(u, baseURI)
                reader = formats.adapter_for(target)
                nodes = reader.nodes(reader.read(target))
            except (OSError, ValueError, SyntaxError) as err:
                log.info("Inline url %s did not read: %s", u, err)
                continue
            if generation is not None and generation != self.__dict__.get('_generation'):
                return
            log.info("loaded %s", u)
            self.inlined = tuple(nodes)
            for reference in contexts:
                c = reference()
                if c:
                    c.triggerRedraw(1)
            return
        log.warning(
            """Unable to load any scene from the url %s for the node %s""",
            url,
            str(self),
        )
