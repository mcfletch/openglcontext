"""Navigation over a level's own collision geometry.

A navmesh is **generated from the collision mesh at load time**, never baked
and never read from content: that gives navigation for levels nobody ever baked
one for, regeneration when the geometry changes, and no dependence on data this
project may not read.

See :mod:`OpenGLContext.nav.navmesh`.
"""

from OpenGLContext.nav.navmesh import NavMesh, build, from_world

__all__ = ['NavMesh', 'build', 'from_world']
