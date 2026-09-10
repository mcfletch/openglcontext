"""VRML97 loader module for OpenGLContext

This module implements VRML97-parser handler for the
loader module.  The parser is provided by the
vrml.vrml97 module.  Of particular interest to the
end-developer is the standardPrototype function, which
allows you to register prototypes as standard features
for your VRML97 files.

By default, the standard prototype namespace is the
union of:
    vrml.vrml97.basenodes and
    OpenGLContext.scenegraph.basenodes

with prototypes from the second replacing those in the
first.
"""

from vrml.vrml97 import basenamespaces, parser, linearise
from vrml import protofunctions
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.loaders import base
from vrml.vrml97 import parseprocessor
from OpenGL._bytes import as_str
import threading
import logging
from typing import Any, Dict, IO, Tuple, Union

log = logging.getLogger(__name__)

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

_parser = parser.Parser(parser.grammar, "vrmlFile")


class VRML97Handler(base.BaseHandler):
    """Handler for loading VRML97-encoded scenegraphs

    This is a load handler for the loader module which
    will be instantiated by the load or loads function
    in order to handle the result of downloading/opening
    a VRML97-encoded file.

    The prototypes argument is normally a pointer to
    the STANDARD_PROTOTYPES namespace, so that prototype
    registration during downloading will be available
    during parsing.
    """

    filename_extensions = [".wrl", ".wrl.gz", ".wrz", ".vrml", ".vrml.gz"]
    LOCK = threading.RLock()

    def __init__(self, prototypes: Dict[str, Any]) -> None:
        """Initialise the file-handler

        prototypes -- prototype namespace provided by the
            vrml.protonamespace package
        """
        self.prototypes = prototypes

    def parse(self, data: Any, baseURL: str, *args: Any,
              **named: Any) -> Tuple[bool, Any]:
        """Parse the loaded data (with the provided meta-information)"""
        with self.LOCK:
            success, results, next = _parser.parse(
                as_str(data),
                processor=parseprocessor.ParseProcessor(
                    basePrototypes=self.prototypes,
                    baseURI=baseURL,
                ),
            )
            return success, results[1] if success else None

    @classmethod
    def dumps(cls, node: Any) -> str:
        """Dump node's representation to a VRML97 string"""
        return str(linearise.Lineariser().linear(node))

    @classmethod
    def dump(cls, node: Any, file: Union[str, IO[str]]) -> str:
        """Dump node's representation to a VRML97-formatted file

        ``file`` is a filename to write, or a text file open for writing. A
        handle the caller opened is left open, so a caller writing several
        nodes into one file can go on writing to it.
        """
        data = cls.dumps(node)
        if isinstance(file, str):
            with open(file, "w", encoding="utf-8") as handle:
                handle.write(data)
        else:
            file.write(data)
        return data


def defaultHandler() -> "VRML97Handler":
    """Produce a default handler object

    This is registered in the setup.py as the entry point for this plug-in
    """

    return VRML97Handler(STANDARD_PROTOTYPES)
