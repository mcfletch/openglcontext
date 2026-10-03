"""Choosing how to open a source, and opening it.

``oglc-view model.glb``, ``oglc-view world.wrl`` and ``oglc-view tileset.json``
are the same viewer; what differs is one adapter, chosen from the source itself
rather than from which command was typed.

The choice is *data*, not an ``if`` chain: adapters register against the
suffixes and content types they handle through
:class:`OpenGLContext.plugins.Adapter`, alongside the loader, context and node
registries.  A third party adds a format by registering one more entry.  The
choosing itself is :mod:`OpenGLContext.loaders.formats`; what is registered
there is any :class:`~OpenGLContext.loaders.readers.SceneReader`, and the
functions here answer only the ones that are also
:class:`SceneAdapter`\\ s, since a format a viewer cannot show is not one it can
open.  :class:`~OpenGLContext.loaders.sceneloader.SceneLoader` is what a
program reads a source with.

    from OpenGLContext.viewer.adapters import adapter_for

    adapter = adapter_for('model.glb')
    scene = adapter.load('model.glb')

See [docs/gltf.rst](../../../docs/gltf.rst).
"""
from typing import Optional

from OpenGLContext.loaders import formats
from OpenGLContext.loaders.formats import UnknownSourceType, known_sources
from OpenGLContext.viewer.adapters.base import SceneAdapter, ViewerScene

__all__ = ['SceneAdapter', 'ViewerScene', 'UnknownSourceType', 'adapter_for',
           'adapter_named', 'known_sources']


def _viewable(reader: object, what: str) -> SceneAdapter:
    if not isinstance(reader, SceneAdapter):
        raise UnknownSourceType(
            "%s is read by the %r reader, which a viewer cannot show"
            % (what, getattr(reader, 'name', type(reader).__name__)))
    return reader


def adapter_named(name: str) -> SceneAdapter:
    """The adapter registered as ``name`` (``gltf``, ``vrml97``, ...)."""
    return _viewable(formats.adapter_named(name), repr(name))


def adapter_for(source: str, contentType: Optional[str] = None) -> SceneAdapter:
    """The adapter that opens ``source``; see :func:`OpenGLContext.loaders.formats.adapter_for`."""
    return _viewable(formats.adapter_for(source, contentType), repr(source))
