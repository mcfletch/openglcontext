"""Helpers for building physics demos.

A :class:`DemoScene` keeps a scenegraph and a :class:`PhysicsWorld` in lockstep:
each ``add_*`` call creates a ``Transform``/``Shape`` for rendering and a
``PhysicsBody`` the world drives.  :meth:`advance` steps the world from real
elapsed time and refreshes the debug overlay.  The demos in ``tests/physics_*.py``
build on this so each stays short and readable.
"""
from typing import Any, Dict, Iterable, List, Optional, Union
import numpy as np

from OpenGLContext.scenegraph import basenodes as _basenodes
from OpenGLContext.scenegraph.transform import Transform
from OpenGLContext.scenegraph.physicsbody import PhysicsBody

from omi_physics import model
from .manager import PhysicsManager
from .debugdraw import PhysicsDebugDraw, PROXIES, CONTACTS
from omi_physics.mathutil import Vec

# basenodes registers its node classes at runtime, so it carries no static
# attributes; access it through an ``Any`` alias.
basenodes: Any = _basenodes


def disable_vsync() -> None:
    """Uncap the frame rate.

    A forced redraw every frame (``triggerRedraw`` in ``OnIdle``) blocks on
    ``SwapBuffers`` when the GLFW window is hidden and no compositor is presenting
    frames (the auto-exit capture path).  Disabling the swap interval avoids the
    stall and lets an animated physics demo run and capture.
    """
    try:
        import glfw
        glfw.swap_interval(0)
    except Exception:
        pass


class DemoScene:
    """A scenegraph and :class:`PhysicsWorld` kept in step by ``add_*`` and :meth:`advance`."""

    def __init__(self, gravity: Optional[model.Gravity] = None,
                 debug_flags: int = PROXIES | CONTACTS,
                 background: Vec = (0.15, 0.16, 0.2), **world_kw: Any) -> None:
        if gravity is None:
            gravity = model.Gravity(gravity=9.81, direction=(0, -1, 0))
        self.manager = PhysicsManager(gravity=gravity, **world_kw)
        self.world = self.manager.world
        self.children: List[Any] = []
        self.debug = PhysicsDebugDraw(self.world, flags=debug_flags)
        self.background = background
        self._materials: Dict[str, int] = {}
        self._was_active = True

    # -- materials -------------------------------------------------------
    def material(self, name: str) -> int:
        """World material index for a preset name, added to the world on first use."""
        if name not in self._materials:
            mat = model.MATERIAL_PRESETS.get(name, model.Material())
            self._materials[name] = self.world.add_material(mat)
        return self._materials[name]

    def raw_material(self, mat: model.Material) -> int:
        """Add a :class:`model.Material` to the world and return its index."""
        return self.world.add_material(mat)

    # -- appearance ------------------------------------------------------
    def _appearance(self, color: Vec) -> Any:
        """A basic diffuse ``Appearance`` in ``color``."""
        return basenodes.Appearance(material=basenodes.Material(
            diffuseColor=color, shininess=0.3))

    # -- bodies ----------------------------------------------------------
    def add_box(self, size: Vec = (1, 1, 1), position: Vec = (0, 0, 0),
                color: Vec = (0.8, 0.8, 0.85), dynamic: bool = True,
                mass: float = 1.0, material: Union[str, int] = 'wood',
                collision_filter: int = -1, velocity: Vec = (0, 0, 0),
                rotation: Vec = (0, 0, 1, 0)) -> Any:
        """Add a box body and its render mesh; return the :class:`PhysicsBody`."""
        shape = self.world.add_shape(model.Shape.box(size))
        geom = basenodes.Box(size=size)
        return self._spawn(geom, shape, position, color, dynamic, mass, material,
                           collision_filter, velocity, rotation)

    def add_sphere(self, radius: float = 0.5, position: Vec = (0, 0, 0),
                   color: Vec = (0.9, 0.5, 0.3), dynamic: bool = True,
                   mass: float = 1.0, material: Union[str, int] = 'rubber',
                   collision_filter: int = -1, velocity: Vec = (0, 0, 0)) -> Any:
        """Add a sphere body and its render mesh; return the :class:`PhysicsBody`."""
        shape = self.world.add_shape(model.Shape.sphere(radius))
        geom = basenodes.Sphere(radius=radius)
        return self._spawn(geom, shape, position, color, dynamic, mass, material,
                           collision_filter, velocity, (0, 0, 1, 0))

    def _spawn(self, geom: Any, shape_idx: int, position: Vec, color: Vec,
               dynamic: bool, mass: float, material: Union[str, int],
               collision_filter: int, velocity: Vec, rotation: Vec) -> Any:
        """Build the transform/shape and physics body for one object and register both."""
        mt = model.DYNAMIC if dynamic else model.STATIC
        motion = model.Motion(type=mt, mass=mass, linearVelocity=tuple(velocity))
        mat_index = material if isinstance(material, int) else self.material(material)
        collider = model.Collider(shape=shape_idx, physicsMaterial=mat_index,
                                  collisionFilter=collision_filter)
        transform = Transform(translation=tuple(position), rotation=tuple(rotation),
                              children=[basenodes.Shape(
                                  geometry=geom, appearance=self._appearance(color))])
        body = PhysicsBody(transform, motion, collider)
        self.manager.add(body)
        self.children.append(transform)
        return body

    def add_mesh_body(self, geometry: Any, shape: model.Shape,
                      position: Vec = (0, 0, 0), color: Vec = (0.8, 0.75, 0.6),
                      dynamic: bool = True, mass: float = 1.0,
                      material: Union[str, int] = 'wood',
                      rotation: Vec = (0, 0, 1, 0)) -> Any:
        """Attach an already-cooked ``model.Shape`` to an arbitrary render mesh."""
        shape_idx = self.world.add_shape(shape)
        return self._spawn(geometry, shape_idx, position, color, dynamic, mass,
                           material, -1, (0, 0, 0), rotation)

    def add_gravity_volume(self, field: Any, region: Any = None) -> Any:
        """Add a local gravity volume to the world."""
        from omi_physics.gravity import GravityVolume
        return self.world.add_gravity_volume(GravityVolume(field, region))

    def add_trigger_box(self, size: Vec = (1, 1, 1), position: Vec = (0, 0, 0),
                        color: Vec = (0.2, 0.9, 0.9)) -> Any:
        """Add a static, non-solid trigger box; return the :class:`PhysicsBody`."""
        shape = self.world.add_shape(model.Shape.box(size))
        transform = Transform(translation=tuple(position))
        body = PhysicsBody(transform, model.Motion(type=model.STATIC),
                           trigger=model.Trigger(shape=shape))
        self.manager.add(body)
        return body

    # -- scene / stepping ------------------------------------------------
    def scene_graph(self, extra: Iterable[Any] = ()) -> Any:
        """The full scenegraph: bodies, debug overlay, ``extra`` nodes, and background."""
        children = list(self.children) + [self.debug.root] + list(extra)
        children.append(basenodes.SimpleBackground(color=self.background))
        return basenodes.sceneGraph(children=children)

    def advance(self, dt: float) -> bool:
        """Step the world; return True while the scene still needs redrawing.

        Once every dynamic body is asleep nothing changes, so the caller can stop
        forcing redraws and let the display settle (one trailing frame renders the
        final resting state)."""
        self.manager.advance(dt)
        active = bool(np.any(self.world.awake[self.world.motion_type == 2]))
        self.debug.update()
        render = active or self._was_active
        self._was_active = active
        return render
