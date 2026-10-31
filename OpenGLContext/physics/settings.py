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

__all__ = ['COLLIDERS', 'ENGINES', 'HANDLER_ERRORS', 'MODES', 'PhysicsDefinition', 'check_engine', 'default_engine',
           'definition_for']

#: Where a context steps its world: on its own thread, or in the frame hook.
MODES = ('thread', 'inline')
#: What becomes of an exception a handler, step code or a posted function raises:
#: ``log`` logs it once and goes on, ``raise`` also raises it from the next frame.
HANDLER_ERRORS = ('log', 'raise')
#: Which scenery becomes static bodies: every shape of the scene, only the
#: ones the application adds, or none.
COLLIDERS = ('scene', 'explicit', 'none')
#: The engines that step a world: Jolt, through pyjoltphysics.
ENGINES = ('jolt',)
#: Where the physics guide tells a program that named the omi engine what to do.
MIGRATION_NOTE = 'docs/physics.rst, "Programs that named the omi engine"'


def check_engine(name: str) -> str:
    """``name`` where it is one of :data:`ENGINES`; ValueError naming the choices otherwise.

    ``'omi'`` is told that the engine is Jolt and where the migration note is.
    """
    if name in ENGINES:
        return name
    if name == 'omi':
        raise ValueError("engine 'omi' is not an engine of OpenGLContext; the engine is 'jolt' "
                         '(leave engine unset), and omi_physics is a package of its own (see %s)'
                         % (MIGRATION_NOTE,))
    raise ValueError('engine %r is not one of %s' % (name, ', '.join(ENGINES)))


def default_engine() -> str:
    """``OPENGLCONTEXT_PHYSICS_ENGINE``, one of :data:`ENGINES`, else ``jolt``.

    Read once a process: a change to the variable after the first call has no
    effect.
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
    #: The engine that steps the world, one of :data:`ENGINES`
    #: (env: OPENGLCONTEXT_PHYSICS_ENGINE): ``jolt``, pyjoltphysics, which
    #: OpenGLContext requires. The field is where a further engine would be named.
    engine = field.newField('engine', 'SFString', 1, default_engine)
    #: The fixed step, in steps a second, in both modes. A frame shorter than a
    #: step draws moving bodies between the last two steps; a free-running
    #: world is drawn a step behind the frame clock.
    tickHz = field.newField('tickHz', 'SFFloat', 1, 120.0)
    #: The longest span of time one frame steps, in seconds. A frame that took
    #: longer steps this much and drops the rest.
    maxCatchUp = field.newField('maxCatchUp', 'SFFloat', 1, 0.1)
    #: The most bodies the world holds at once, every kind counted (a static
    #: instance and a ragdoll bone each count one). An add past it raises
    #: ValueError on the calling thread.
    maxBodies = field.newField('maxBodies', 'SFInt32', 1, 65536)
    #: Gravity as an acceleration in metres a second squared.
    gravity = field.newField('gravity', 'SFVec3f', 1, (0.0, -9.81, 0.0))
    #: ``scene`` makes a static body of each shape under the scene graph,
    #: ``explicit`` only the shapes the application adds, ``none`` neither.
    colliders = field.newField('colliders', 'SFString', 1, 'scene')
    #: ``log`` logs an exception a handler, step code or a posted function
    #: raises and goes on; ``raise`` also raises it from the next ``frame`` or
    #: ``step``, as a test wants (env: OPENGLCONTEXT_PHYSICS_HANDLER_ERRORS; the
    #: testing plugin makes it ``raise``).
    handlerErrors = field.newField(
        'handlerErrors', 'SFString', 1,
        lambda: renderoptions.env_choice('OPENGLCONTEXT_PHYSICS_HANDLER_ERRORS', HANDLER_ERRORS,
                                         {}, 'log'))
    #: Damping given to a dynamic body that names none, per second.
    linearDamping = field.newField('linearDamping', 'SFFloat', 1, 0.3)
    angularDamping = field.newField('angularDamping', 'SFFloat', 1, 1.5)

    FIELDS = ('enabled', 'mode', 'engine', 'tickHz', 'maxCatchUp', 'maxBodies', 'gravity',
              'colliders', 'handlerErrors', 'linearDamping', 'angularDamping')

    def replaced(self, **changes: Any) -> PhysicsDefinition:
        """A new definition with this one's fields and ``changes`` in place of some."""
        values = {name: getattr(self, name) for name in self.FIELDS}
        values.update(changes)
        return type(self)(**values)

    def validate(self) -> None:
        """Raise ValueError naming the first field the service cannot run with."""
        if self.mode not in MODES:
            raise ValueError('mode %r is not one of %s' % (self.mode, ', '.join(MODES)))
        check_engine(self.engine)
        if self.handlerErrors not in HANDLER_ERRORS:
            raise ValueError('handlerErrors %r is not one of %s'
                             % (self.handlerErrors, ', '.join(HANDLER_ERRORS)))
        if self.colliders not in COLLIDERS:
            raise ValueError('colliders %r is not one of %s'
                             % (self.colliders, ', '.join(COLLIDERS)))
        number(self.tickHz, 'tickHz', positive=True)
        number(self.maxCatchUp, 'maxCatchUp', positive=True)
        if int(self.maxBodies) < 1:
            raise ValueError('maxBodies must be at least 1, not %r' % (self.maxBodies,))
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
