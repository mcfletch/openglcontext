"""One loaded character: its rig, its clips, and what it is holding.

The three parts of :mod:`OpenGLContext.character` over one glTF document, so a
game that wants the ordinary thing writes the ordinary thing::

    model = CharacterModel.load('marine.glb')
    model.attach('grip', load_gltf('handgun.glb').group)
    model.play('run', fade=0.2)
    model.layer('upper', mask=model.mask('spine')).play('fire', loop=False)
    ...
    model.update(dt)                 # once a frame
    scene.children = [model.group]   # the renderable root

Everything here is a thin pass-through to :class:`~.humanoid.Humanoid`,
:class:`~.mixer.AnimationMixer` and :mod:`~.attachment`, and each of those
stays usable on its own -- a model with no skeleton still animates, and a
skeleton with no clips can still be posed and hung things on.

**A point is a socket or a bone.** :meth:`point` looks for an attachment point
the model declares first and falls back to a humanoid bone of that name, so
``attach('grip', weapon)`` works on a model authored with a grip point and
``attach('rightHand', weapon)`` works on one that was not.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from OpenGLContext.character.attachment import SOCKET_PREFIX, attach, detach, sockets
from OpenGLContext.character.humanoid import Humanoid
from OpenGLContext.character.mixer import BASE_LAYER, AnimationMixer, Layer, Track

__all__ = ['CharacterModel']


class CharacterModel:
    """A rigged model, ready to pose, animate and equip."""

    def __init__(self, scene: Any, socket_prefix: str = SOCKET_PREFIX) -> None:
        self.scene = scene
        #: The renderable root -- mount this in the scenegraph.
        self.group = scene.group
        #: Which node is which bone, or None if no bone could be identified.
        self.humanoid: Optional[Humanoid] = Humanoid.from_scene(scene)
        #: Every clip the document carries, by name.
        self.mixer = AnimationMixer.from_scene(scene)
        #: The attachment points the model declares, by name.
        self.points: Dict[str, Any] = sockets(scene, prefix=socket_prefix)

    # -- construction -----------------------------------------------------
    @classmethod
    def load(cls, source: Any, **named: Any) -> "CharacterModel":
        """Load a character from a path, a URL or the bytes of a ``.glb``."""
        from OpenGLContext.loaders.gltf import load_gltf
        return cls(load_gltf(source, **named))

    @classmethod
    def from_scene(cls, scene: Any, **named: Any) -> "CharacterModel":
        """Wrap a document somebody else has already loaded."""
        return cls(scene, **named)

    # -- what it can play -------------------------------------------------
    @property
    def clips(self) -> Dict[str, Any]:
        """The clips this model carries, by name."""
        return self.mixer.clips

    def play(self, name: str, **named: Any) -> Track:
        """Play a clip -- see :meth:`~.mixer.AnimationMixer.play`."""
        return self.mixer.play(name, **named)

    def layer(self, name: str = BASE_LAYER, **named: Any) -> Layer:
        """One animation layer -- see :meth:`~.mixer.AnimationMixer.layer`."""
        return self.mixer.layer(name, **named)

    def update(self, dt: float) -> None:
        """Advance the animation by ``dt`` seconds and pose the model."""
        self.mixer.update(dt)

    def mask(self, *bones: str, exclude: Iterable[str] = ()) -> frozenset:
        """The nodes under ``bones``, for masking a layer.

        Empty where the model has no recognised skeleton, which leaves a layer
        built from it contributing nothing rather than moving the wrong joints.
        """
        if self.humanoid is None:
            return frozenset()
        return self.humanoid.mask(*bones, exclude=exclude)

    # -- what it is holding -----------------------------------------------
    def point(self, name: str) -> Optional[Any]:
        """The ``Transform`` to mount something on, by point name or bone name."""
        found = self.points.get(name)
        if found is not None:
            return found
        if self.humanoid is None:
            return None
        return self.humanoid.transform(name)

    def attach(self, name: str, node: Any) -> Optional[Any]:
        """Hang ``node`` on the named point; None if the model has no such point.

        None rather than an error: a character model that was authored without
        a grip point is a model that cannot hold a weapon, which a game should
        be able to notice and carry on from -- the same way it carries on when
        the weapon itself will not load.
        """
        point = self.point(name)
        return None if point is None else attach(point, node)

    def detach(self, name: str, node: Any) -> bool:
        """Take ``node`` off the named point; False if it was not on it."""
        point = self.point(name)
        return False if point is None else detach(point, node)
