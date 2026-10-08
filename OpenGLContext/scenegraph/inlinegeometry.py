"""InlineGeometry: a file's triangles drawn as one geometry

X3D's `InlineGeometry` (Networking component, 4.1) is a geometry node whose
triangles are read from `url`: any format a registered reader opens, as
:class:`~OpenGLContext.scenegraph.inline.Inline` reads one (an OBJ, a glTF
model, an X3D or VRML97 document). Every shape in the file is placed by its
transforms and joined into one mesh
(:func:`~OpenGLContext.scenegraph.meshdata.merged_arrays`), drawn with the
appearance of the `Shape` holding this node; the file's own materials are not
used. `smooth` false draws each triangle with its own normal. `solid` culls
back faces, as on the other geometry nodes.

The file is read on the loader pool, and the mesh it makes is put in place on
the render thread of an open context (straight away where none is open). X3D's
`load` false leaves the geometry empty; setting `url` or `load` reads again.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Optional

from vrml import field, node, protofunctions
from vrml.x3d import loadsensor
from vrml.x3d import nodes as x3d

from OpenGLContext import context
from OpenGLContext.loaders import background
from OpenGLContext.scenegraph import meshdata
from OpenGLContext.scenegraph.inline import (
    InlineLoadField, InlineURLField, prepare_scene_loading, read_first, redraw,
)
from OpenGLContext.scenegraph.meshgeometry import MeshDrawn

log = logging.getLogger(__name__)

__all__ = ['InlineGeometry']


class InlineGeometry(MeshDrawn, x3d.InlineGeometry):
    """X3D's InlineGeometry: the triangles of the file `url` names

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/networking.html#InlineGeometry
    """

    url = InlineURLField('url', 1, list)
    load = InlineLoadField('load', 1, True)
    #: The mesh of the file's triangles as read, before `smooth` and `solid`;
    #: NULL until a read finishes.
    loaded = field.newField(' loaded', 'SFNode', 1, node.NULL)

    def dependOn(self, holder: Any) -> None:
        """Make `holder` depend on the fields and on the mesh read"""
        super().dependOn(holder)
        holder.depend(self, protofunctions.getField(self, ' loaded'))

    def buildMesh(self) -> Optional[Any]:
        """The read triangles, flat where `smooth` is false; None before a read"""
        loaded = self.loaded
        found = loaded.meshArrays() if loaded else None
        if found is None:
            return None
        if not self.smooth:
            found = meshdata.flattened(found)
        return self.meshFrom(found, solid=bool(self.solid))

    def reload(self) -> None:
        """Empty the geometry and, where `load` is true, read `url` again"""
        generation = self.__dict__['_generation'] = self.__dict__.get('_generation', 0) + 1
        if self.loaded:
            self.loaded = node.NULL
        url = list(self.__dict__.get('url', ()))
        if not url or not self.__dict__.get('load', True):
            return
        loadsensor.set_load_state(self, loadsensor.LOADING)
        background.load_in_background(
            ' '.join(url), self.loadBackground, url, context.Context.allContexts, generation,
            prepare=prepare_scene_loading,
        )

    def loadBackground(self, url: Sequence[str], contexts: Sequence[Any] = (),
                       generation: Any = None) -> None:
        """Read the first of `url` that reads and make its mesh; runs on the loader pool"""
        from OpenGLContext.scenegraph.frommesh import mesh_from_primitive  # noqa: PLC0415 PBRMesh imports GL
        read = read_first(url, self)
        found = meshdata.merged_arrays(read[1]) if read is not None else None
        if found is None:
            log.warning('InlineGeometry %s: no triangles read from %s',
                        self.DEF or '', ' '.join(url))
        mesh = mesh_from_primitive(found) if found is not None else None
        self._deliver(contexts, mesh, generation)

    def _deliver(self, contexts: Sequence[Any], mesh: Optional[Any], generation: Any) -> None:
        """Put `mesh` in place on an open context's render thread, or here where none is open"""
        for reference in contexts:
            found = reference()
            if found is not None:
                found.renderQueue.call(self._place, mesh, generation, contexts)
                return
        self._place(mesh, generation, contexts)

    def _place(self, mesh: Optional[Any], generation: Any, contexts: Sequence[Any] = ()) -> None:
        """`mesh` as the read triangles, unless a read since has superseded it"""
        if generation is not None and generation != self.__dict__.get('_generation'):
            return
        self.loaded = mesh if mesh is not None else node.NULL
        loadsensor.set_load_state(self, loadsensor.LOADED if mesh is not None
                                  else loadsensor.FAILED)
        redraw(contexts)
