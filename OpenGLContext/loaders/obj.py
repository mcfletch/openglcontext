"""Wavefront OBJ models read into the scenegraph.

``Loader.load('house.obj')`` returns a scene graph holding one ``Transform`` per
object or group (``o`` and ``g``), named by the name the file gives, and in each
a ``Shape`` per material and primitive kind: a ``PBRMesh`` of triangles, line
segments or points, drawn with the ``PhysicalMaterial`` its ``usemtl`` names.
:mod:`~OpenGLContext.loaders.objfile` reads the geometry,
:mod:`~OpenGLContext.loaders.mtlfile` and
:mod:`~OpenGLContext.loaders.objmaterials` the materials; this puts them in a
scene::

    from OpenGLContext.loaders.loader import Loader
    scene = Loader.load('house.obj')            # or .obj.gz
    chimney = scene.getDEF('Chimney')

Faces are drawn from both sides: an OBJ does not say which way its triangles
face. A file with no geometry reads as an empty scene.
"""
from __future__ import annotations

import logging
from typing import Any, Union

import numpy as np
from OpenGL.GL import GL_LINES, GL_POINTS, GL_TRIANGLES

from OpenGLContext.loaders import base
from OpenGLContext.loaders.gltf.meshes import estimate_tangents, reads_tangents
from OpenGLContext.loaders.objfile import FREEFORM, ObjMesh, parse_obj
from OpenGLContext.loaders.objmaterials import LibraryMaterial, MaterialBuilder, load_libraries
from OpenGLContext.loaders.resolver import DEFAULT_MAX_RESOURCE_BYTES, gunzipped
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

__all__ = ['OBJHandler', 'defaultHandler']

log = logging.getLogger(__name__)

DRAW_MODES = {'triangles': GL_TRIANGLES, 'lines': GL_LINES, 'points': GL_POINTS}


def tangents_of(mesh: ObjMesh, material: Any) -> Any:
    """The tangents a mesh needs for its material's normal map, or None

    The shader leaves a normal map out where a mesh has no tangents. OBJ
    texture coordinates run up the picture, and the tangent estimate takes
    glTF's, which run down it, so v is turned over for the estimate.
    """
    if (mesh.kind != 'triangles' or mesh.texcoords is None or mesh.normals is None
            or not reads_tangents(material)):
        return None
    turned = mesh.texcoords * np.array([1.0, -1.0], np.float32) + np.array([0.0, 1.0], np.float32)
    return estimate_tangents(mesh.positions, mesh.normals, turned, mesh.indices)


class OBJHandler(base.BaseHandler):
    """The loader handler for ``.obj`` and ``.obj.gz``"""

    filename_extensions = ('.obj', '.obj.gz')

    def parse(self, data: Union[bytes, str], baseURL: str, *args: Any,
              **named: Any) -> tuple[bool, Any]:
        """The scene graph an OBJ document describes

        ``baseURL`` is where the document was read from: the material
        libraries and textures it names are looked for beside it. Raises
        ``ValueError`` naming the file and line for a statement that cannot
        be read.
        """
        source = baseURL or 'document.obj'
        if isinstance(data, (bytes, bytearray, memoryview)):
            data = gunzipped(bytes(data), DEFAULT_MAX_RESOURCE_BYTES, source)
        model = parse_obj(data, source)
        libraries = load_libraries(model.libraries, source) if model.libraries else {}
        builder = MaterialBuilder(source)
        appearances: dict[str, Any] = {}
        unknown: set[str] = set()

        def appearance_of(material: str, coloured: bool) -> Any:
            entry: Union[LibraryMaterial, None] = libraries.get(material)
            if entry is not None:
                if material not in appearances:
                    appearances[material] = builder.appearance(entry)
                return appearances[material]
            if material and material not in unknown:
                unknown.add(material)
                log.warning('%s: material %r is not in any library it names', source, material)
            return builder.default(coloured)

        scene = basenodes.sceneGraph()
        for part in model.parts:
            transform = basenodes.Transform(DEF=part.name) if part.name else basenodes.Transform()
            for mesh in part.meshes:
                appearance = appearance_of(mesh.material, mesh.colors is not None)
                geometry = PBRMesh(
                    positions=mesh.positions, normals=mesh.normals, texcoords=mesh.texcoords,
                    tangents=tangents_of(mesh, appearance.material), colors=mesh.colors,
                    indices=mesh.indices, solid=False, draw_mode=DRAW_MODES[mesh.kind],
                    appearance=appearance)
                transform.children.append(basenodes.Shape(geometry=geometry, appearance=appearance))
            scene.children.append(transform)
            if part.name:
                scene.regDefName(part.name, transform)
        freeform = sum(model.ignored[word] for word in FREEFORM)
        if freeform:
            log.warning('%s: %d free-form geometry statements (curves and surfaces) are not read',
                        source, freeform)
        if model.ignored:
            log.debug('%s: statements read past: %s', source, dict(model.ignored))
        if builder.unused:
            log.debug('%s: map channels not used: %s', source, sorted(builder.unused))
        return True, scene


def defaultHandler() -> OBJHandler:
    """The handler instance ``plugins.Loader`` registers for OBJ"""
    return OBJHandler()
