"""Scenegraph glue over the :mod:`omi_physics` rigid-body engine.

The simulation engine lives in the standalone :mod:`omi_physics` package (the OMI
glTF data model, the ``PhysicsWorld``, collision, solver, and the compiled
accelerators). This package is only the part that ties that engine to the
OpenGLContext scenegraph:

* :mod:`~OpenGLContext.physics.manager` -- registers scenegraph ``PhysicsBody``
  handles into a world and writes interpolated poses back to their Transforms.
* :mod:`~OpenGLContext.physics.threaded` -- the same, driven off the render thread.
* :mod:`~OpenGLContext.physics.demo` -- builds a scenegraph and a world together.
* :mod:`~OpenGLContext.physics.debugdraw` -- an instanced wireframe overlay of the
  world's proxies, contacts, and velocities.
* :mod:`~OpenGLContext.physics.gltf_world` -- turns a loaded glTF scenegraph into a
  collision world.
"""
