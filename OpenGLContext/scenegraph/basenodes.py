"""Every registered scenegraph node class, by name, in one namespace

These are the OpenGLContext implementations of the ``vrml.vrml97.basenodes``
nodes and a few others, gathered here so that a caller reaches any of them
without knowing which module it lives in::

    from OpenGLContext.scenegraph import basenodes

    sg = basenodes.sceneGraph( children = [
        basenodes.Transform( children = [
            basenodes.Shape(
                geometry = basenodes.Box( size = (1, 1, 1) ),
                appearance = basenodes.Appearance(
                    material = basenodes.Material( diffuseColor = (1, 0, 0) ),
                ),
            ),
        ] ),
    ] )

This is also the vocabulary the VRML97 parser resolves node names against, so
a name registered here can be used in a ``.wrl`` file.

**Adding a node.** Register the class with :class:`OpenGLContext.plugins.Node`
under the name it should be known by, and import your package before building
a scenegraph::

    from OpenGLContext.plugins import Node

    Node( 'Wobbler', 'mypackage.nodes.Wobbler' )

The registry is a list in the running process, filled by
``OpenGLContext/__init__.py`` for the built-in nodes.  What puts a third
party's node on it is the application importing that package; nothing is
scanned and nothing is installed.

**Register before this module is first imported.**  The names here are read
from the registry once, when the module loads, so a class registered
afterwards is absent until something reloads it.  Importing your package
early -- before the scenegraph is built -- is all this asks.

Registering a name that is already taken is not a way to replace a built-in
node: the two lookups disagree about which of the two wins, so which class a
scenegraph gets depends on how it was reached.  Give a new node a new name.
"""

import logging

__all__ = []
PROTOTYPES = {}

log = logging.getLogger(__name__)


def _load():
    """Load the registered node-types from package resource declarations"""
    from OpenGLContext import plugins

    entrypoints = plugins.Node.all()
    for entrypoint in entrypoints:
        name = entrypoint.name
        try:
            classObject = entrypoint.load()
        except (ImportError, AttributeError) as err:
            log.warning("""Unable to load node implementation for %s: %s""", name, err)
        else:
            globals()[name] = classObject
            PROTOTYPES[name] = classObject
            __all__.append(name)
            log.debug("""Loaded node implementation for %s: %s""", name, classObject)


_load()
del _load
