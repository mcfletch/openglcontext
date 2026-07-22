"""GPU-instanced vegetation with distance LOD.

- :class:`InstancedBillboards` — camera-facing quads for grass and tree impostors,
  with impostor cross-fade and grass distance-dissolve.
- :class:`InstancedMeshLOD` — real tree meshes drawn near the camera (the
  high-detail LOD; impostor billboards take over at distance).
- :func:`world_grid_scatter` — world-anchored jittered scatter for pop-free
  camera-following grass fields.

:data:`LOD_NEAR`/:data:`LOD_FAR` are the shared mesh-to-impostor cross-fade window,
driving both the near-mesh and impostor shaders so their handoff stays seamless.
"""
from OpenGLContext.scenegraph.vegetation.base import LOD_NEAR, LOD_FAR
from OpenGLContext.scenegraph.vegetation.billboards import InstancedBillboards
from OpenGLContext.scenegraph.vegetation.nearmesh import InstancedMeshLOD
from OpenGLContext.scenegraph.vegetation.clumps import InstancedClumps, load_clump_glb
from OpenGLContext.scenegraph.vegetation.grid import world_grid_scatter

__all__ = ["InstancedBillboards", "InstancedMeshLOD", "InstancedClumps",
           "load_clump_glb", "world_grid_scatter", "LOD_NEAR", "LOD_FAR"]
