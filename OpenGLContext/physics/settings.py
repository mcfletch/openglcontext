"""How a context's physics is configured.

:class:`PhysicsDefinition` is a scenegraph node, declared on the
:class:`~OpenGLContext.contextdefinition.ContextDefinition` as ``physics`` the way
:class:`~OpenGLContext.audio.settings.AudioSettings` is declared as ``audio``, so
it validates, serialises and can be carried by an X3D document. The settings
are the game's choices: whether the world runs, where it runs, how fine its
step is, what gravity is, and which scenery collides.

``Context.physics.set_config(definition)`` takes the same node at run time.
"""
from __future__ import annotations

from typing import Any

from vrml import field, node

from OpenGLContext import renderoptions
from OpenGLContext.physics.checks import number, vector

__all__ = ['BACKENDS', 'COLLIDERS', 'ENGINES', 'MODES', 'PhysicsDefinition', 'default_backend',
           'default_engine', 'definition_for']

#: Where a context steps its world: on its own thread, or in the frame hook.
MODES = ('thread', 'inline')
#: Which scenery becomes static bodies: every shape of the scene, only the
#: ones the application adds, or none.
COLLIDERS = ('scene', 'explicit', 'none')
#: The compute backends a world steps with: ``auto`` hands off from NumPy to GL
#: compute past a count of awake bodies; ``numpy`` and ``cpu`` stay on NumPy;
#: ``gpu`` and ``glcompute`` use GL 4.3 compute on the stepping thread.
BACKENDS = ('auto', 'numpy', 'cpu', 'gpu', 'glcompute')
#: The engines that step a world: Jolt through pyjoltphysics, or omi_physics
#: (deprecated: the ``omi-physics`` extra, for programs that still name it).
ENGINES = ('jolt', 'omi')


def default_backend() -> str:
    """``OPENGLCONTEXT_PHYSICS_BACKEND``, one of :data:`BACKENDS`, else ``auto``."""
    return renderoptions.env_choice('OPENGLCONTEXT_PHYSICS_BACKEND', BACKENDS, {}, 'auto')


def default_engine() -> str:
    """``OPENGLCONTEXT_PHYSICS_ENGINE``, one of :data:`ENGINES`, else ``jolt``.

    Read once a process, so a game's whole suite runs on one engine when the
    variable is set for the run.
    """
    return renderoptions.env_choice_once('OPENGLCONTEXT_PHYSICS_ENGINE', ENGINES, {}, 'jolt')


class PhysicsDefinition(node.Node):
    """The world a context simulates, and how it steps it."""

    PROTO = 'PhysicsDefinition'

    #: Whether the world runs. Off starts no worker and makes no colliders,
    #: and bodies stay where they were put (env: OPENGLCONTEXT_PHYSICS).
    enabled = field.newField(
        'enabled', 'SFBool', 1,
        lambda: renderoptions.env_flag('OPENGLCONTEXT_PHYSICS', True))
    #: ``thread`` steps the world on a worker thread; ``inline`` steps it in the
    #: frame hook, which is what a capture, a replay and a game that controls its
    #: bodies between steps use (env: OPENGLCONTEXT_PHYSICS_MODE).
    mode = field.newField(
        'mode', 'SFString', 1,
        lambda: renderoptions.env_choice('OPENGLCONTEXT_PHYSICS_MODE', MODES, {}, 'thread'))
    #: The omi engine's compute backend, one of :data:`BACKENDS`
    #: (env: OPENGLCONTEXT_PHYSICS_BACKEND). The Jolt engine reads none.
    backend = field.newField('backend', 'SFString', 1, default_backend)
    #: The engine that steps the world, one of :data:`ENGINES`
    #: (env: OPENGLCONTEXT_PHYSICS_ENGINE). ``jolt``, the default, is
    #: pyjoltphysics, which OpenGLContext requires; ``omi`` needs the deprecated
    #: omi_physics, installed by ``pip install OpenGLContext[omi-physics]``.
    engine = field.newField('engine', 'SFString', 1, default_engine)
    #: The fixed step, in steps a second, in both modes. A frame shorter than a
    #: step draws moving bodies between the last two steps.
    tickHz = field.newField('tickHz', 'SFFloat', 1, 120.0)
    #: The longest span of time one frame steps, in seconds. A frame that took
    #: longer steps this much and drops the rest.
    maxCatchUp = field.newField('maxCatchUp', 'SFFloat', 1, 0.1)
    #: Gravity as an acceleration in metres a second squared.
    gravity = field.newField('gravity', 'SFVec3f', 1, (0.0, -9.81, 0.0))
    #: ``scene`` makes a static body of each shape under the scene graph,
    #: ``explicit`` only the shapes the application adds, ``none`` neither.
    colliders = field.newField('colliders', 'SFString', 1, 'scene')
    #: Damping given to a dynamic body that names none, per second.
    linearDamping = field.newField('linearDamping', 'SFFloat', 1, 0.3)
    angularDamping = field.newField('angularDamping', 'SFFloat', 1, 1.5)

    FIELDS = ('enabled', 'mode', 'backend', 'engine', 'tickHz', 'maxCatchUp', 'gravity', 'colliders',
              'linearDamping', 'angularDamping')

    def replaced(self, **changes: Any) -> PhysicsDefinition:
        """A new definition with this one's fields and ``changes`` in place of some."""
        values = {name: getattr(self, name) for name in self.FIELDS}
        values.update(changes)
        return type(self)(**values)

    def validate(self) -> None:
        """Raise ValueError naming the first field the service cannot run with."""
        if self.mode not in MODES:
            raise ValueError('mode %r is not one of %s' % (self.mode, ', '.join(MODES)))
        if self.backend not in BACKENDS:
            raise ValueError('backend %r is not one of %s' % (self.backend, ', '.join(BACKENDS)))
        if self.engine not in ENGINES:
            raise ValueError('engine %r is not one of %s' % (self.engine, ', '.join(ENGINES)))
        if self.colliders not in COLLIDERS:
            raise ValueError('colliders %r is not one of %s'
                             % (self.colliders, ', '.join(COLLIDERS)))
        number(self.tickHz, 'tickHz', positive=True)
        number(self.maxCatchUp, 'maxCatchUp', positive=True)
        vector(self.gravity, 'gravity')
        number(self.linearDamping, 'linearDamping', non_negative=True)
        number(self.angularDamping, 'angularDamping', non_negative=True)


def definition_for(context: Any) -> PhysicsDefinition:
    """The physics definition of ``context``, defaulted if it declares none.

    A context need not have a definition at all, and a bare test double often
    does not.
    """
    definition = getattr(context, 'contextDefinition', None)
    found = getattr(definition, 'physics', None)
    if isinstance(found, PhysicsDefinition):
        return found
    return PhysicsDefinition()
