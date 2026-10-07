"""VRML97 worlds read into the engine's scenegraph

`.wrl`, `.wrz` and `.vrml` files are read by `vrml.x3d`'s ClassicVRML reader,
which reads VRML97 with its own dialect: VRML97's field names and defaults,
held as X3D 4.1's. Each node is built from the engine's class for it
(:func:`vrml97_prototypes`): the X3D nodes it implements, and the nodes of its
own that a VRML97 world may name, such as the VRML97 NURBS extension and
`SimpleBackground`. An application adds a node of its own with
:func:`standardPrototype`. The scene is an
:class:`~OpenGLContext.scenegraph.scenegraph.X3DScene`, holding what the read
found wrong in its `problems`.
"""

from vrml.vrml97 import basenamespaces, linearise
from vrml import protofunctions
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.loaders import x3d
from OpenGLContext import atomicfiles
import logging
from typing import IO, Any, ClassVar

log = logging.getLogger(__name__)

#: The node classes a VRML97 world may name without declaring them, by name:
#: the engine's registry over pyvrml97's VRML97 nodes.
STANDARD_PROTOTYPES = basenamespaces.basePrototypes.copy()


def standardPrototype(prototype: Any, key: str) -> str:
    """Make the given prototype available as a standard prototype

    What this means is that VRML97 files loaded
    with this module will be able to access the prototype
    without needing to declare a PROTO within the
    file.

    The name registered is the result of protofunctions.name
    for the prototype.
    """
    name = str(protofunctions.name(prototype))
    STANDARD_PROTOTYPES[name] = prototype
    if name != key:
        log.warning(
            "Standard prototype %r is known by the key %r instead of it's prototype name",
            name,
            key,
        )
    return name


### Update from the basenodes dictionary of OpenGLContext
for key, value in basenodes.PROTOTYPES.items():
    try:
        name = standardPrototype(value, key)
    except TypeError:
        pass


def vrml97_prototypes(standard: "dict[str, Any] | None" = None) -> "dict[str, type]":
    """The node classes a VRML97 world is built from, by name

    The engine's X3D nodes (:func:`OpenGLContext.loaders.x3d.prototypes`),
    with each node of `standard` (:data:`STANDARD_PROTOTYPES`) in its place:
    the engine's registry, such as the VRML97 NURBS extension, and what an
    application has registered. pyvrml97's own VRML97 nodes are left out, as
    X3D's declarations stand in for them.
    """
    found: "dict[str, type]" = dict(x3d.prototypes())
    for name, cls in (STANDARD_PROTOTYPES if standard is None else standard).items():
        if cls is not basenamespaces.basePrototypes.get(name):
            found[name] = cls
    return found


class VRML97Handler(x3d.X3DHandler):
    """Reads a VRML97 world into the engine's nodes

    prototypes -- the standard prototypes the world may name, normally
        :data:`STANDARD_PROTOTYPES`, read at each parse so a registration made
        meanwhile is seen
    """

    filename_extensions: ClassVar[tuple[str, ...]] = (
        ".wrl", ".wrl.gz", ".wrz", ".vrml", ".vrml.gz")

    def __init__(self, prototypes: "dict[str, Any] | None" = None) -> None:
        self.prototypes = prototypes

    def vocabulary(self) -> "dict[str, type]":
        return vrml97_prototypes(self.prototypes)

    @classmethod
    def dumps(cls, node: Any) -> str:
        """Dump node's representation to a VRML97 string"""
        return str(linearise.Lineariser().linear(node))

    @classmethod
    def dump(cls, node: Any, file: str | IO[str]) -> str:
        """Dump node's representation to a VRML97-formatted file

        ``file`` is a filename to write, or a text file open for writing. A
        handle the caller opened is left open, so a caller writing several
        nodes into one file can go on writing to it.
        """
        data = cls.dumps(node)
        if isinstance(file, str):
            atomicfiles.write_text(file, data)
        else:
            file.write(data)
        return data


def defaultHandler() -> "VRML97Handler":
    """Produce a default handler object

    This is registered in the setup.py as the entry point for this plug-in
    """

    return VRML97Handler(STANDARD_PROTOTYPES)
