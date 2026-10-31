"""oglc-ragdoll: a walking figure that a blow knocks down, falls limp and gets up again.

Keys:
    h      strike the figure on the chest; powered, it staggers and recovers
    k      knock it down: struck, then limp over a third of a second
    g      get up: the bones move back to the walk over a second
    p      powered or kinematic: whether blows move it at all

The figure is Cesium Man from the Khronos sample models (CC-BY 4.0, Cesium),
its skeleton made a ragdoll by ``RagdollRig`` and driven by ``RagdollFigure``.
"""
from __future__ import annotations

import argparse
from typing import Any

from OpenGLContext.physics import PhysicsDefinition, Proxy
from OpenGLContext.scenegraph import basenodes, surfaces

__all__ = ['MODEL', 'RagdollYard', 'definition', 'main']

#: The sample model the yard loads.
MODEL = 'CesiumMan'
#: The blow ``h`` and ``k`` strike, newton-seconds, and the height on the chest it lands at.
BLOW = 45.0
#: How long the fall into limp takes, and the get-up, seconds.
FALL_BLEND = 0.3
GET_UP_BLEND = 1.0


def definition() -> PhysicsDefinition:
    """The world the yard runs in: in the frame, at 120 Hz, so a fall plays the same on every run."""
    return PhysicsDefinition(mode='inline', tickHz=120.0, maxCatchUp=0.1, colliders='explicit')


def _shape(geometry: Any, material: Any) -> Any:
    return basenodes.Shape(geometry=geometry, appearance=basenodes.Appearance(material=material))


class RagdollYard:
    """The demo's floor, figure and blows, with no GL and no window.

    ``physics`` is an inline physics service (see :func:`definition`) and
    ``model`` a :class:`~OpenGLContext.character.model.CharacterModel`
    with a humanoid skeleton. The context puts :meth:`scene` before the
    camera, calls :meth:`update` once a frame, and forwards keys to
    :meth:`strike`, :meth:`knock_down`, :meth:`get_up` and :meth:`toggle_power`.
    """

    def __init__(self, physics: Any, model: Any) -> None:
        from OpenGLContext.character.ragdoll import RagdollFigure
        self.physics = physics
        self.model = model
        floor = surfaces.pbr_material(surfaces.checkered_marble(512, tiles=8))
        stone = surfaces.pbr_material(surfaces.sandstone(256))
        self.root = basenodes.Group(children=[model.group])
        self._static((12.0, 1.0, 12.0), (0.0, -0.5, 0.0), floor)
        self._static((3.0, 0.3, 0.8), (0.0, 0.15, -1.6), stone)
        if model.clips:
            model.play(sorted(model.clips)[0])
        self.figure = RagdollFigure(physics, model, mode='powered', mass=70.0,
                                    root_force=6000.0, root_torque=2000.0)
        self.down = False
        #: The yard's clock, seconds, and when a get-up hands the figure back to its motors.
        self.time = 0.0
        self._powered_at: float | None = None

    def _static(self, size: Any, position: Any, material: Any) -> Any:
        node = basenodes.Transform(translation=tuple(position), children=[
            _shape(basenodes.Box(size=tuple(size)), material)])
        self.root.children.append(node)
        return self.physics.add_static(node, proxy=Proxy.box(size))

    def scene(self) -> Any:
        """The scenegraph: two lights, a sky, the floor and the figure."""
        return basenodes.sceneGraph(children=[
            basenodes.DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=1.0),
            basenodes.DirectionalLight(direction=(0.5, -0.3, 0.8), intensity=0.35),
            self.root,
            basenodes.SimpleBackground(color=(0.58, 0.66, 0.76)),
        ])

    def update(self, dt: float) -> None:
        """Advance the walk by ``dt`` seconds, send it as the ragdoll's target and draw the bones."""
        self.time += max(0.0, float(dt))
        if self._powered_at is not None and self.time >= self._powered_at:
            self._powered_at = None
            self.figure.set_mode('powered', 0.2)
        self.figure.update(dt)
        self.figure.draw()

    def strike(self, scale: float = 1.0) -> None:
        """Strike the chest from the front, ``scale`` times :data:`BLOW`."""
        names = self.figure.rig.names
        bone = 'chest' if 'chest' in names else names[min(1, len(names) - 1)]
        self.figure.ragdoll.hit(bone, (0.0, 0.0, -BLOW * scale))

    def knock_down(self) -> None:
        """A heavier blow, and the figure goes limp over :data:`FALL_BLEND`."""
        self.strike(1.5)
        self.figure.following = False
        self.figure.set_mode('limp', FALL_BLEND)
        self.down = True

    def get_up(self) -> None:
        """Move the bones back to the walk over :data:`GET_UP_BLEND`, then powered again."""
        self.figure.following = True
        self.figure.set_mode('kinematic', GET_UP_BLEND)
        self._powered_at = self.time + GET_UP_BLEND
        self.down = False

    def toggle_power(self) -> str:
        """Powered or kinematic; the mode now."""
        mode = 'kinematic' if self.figure.ragdoll.mode.value == 'powered' else 'powered'
        self._powered_at = None
        self.figure.following = True
        self.figure.set_mode(mode, 0.2)
        self.down = False
        return mode


def main() -> int:                              # pragma: no cover - needs a window
    """Open the yard in a window."""
    argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0]).parse_args()
    from OpenGLContext.character.model import CharacterModel
    from OpenGLContext.context import Context as BaseContext
    from OpenGLContext.contextdefinition import ContextDefinition
    from OpenGLContext.loaders.gltf import sample_model_url

    class RagdollContext(BaseContext):
        renderer = 'pbr'
        initialPosition = (0.0, 1.0, 3.5)
        contextDefinition = ContextDefinition(physics=definition())

        def OnInit(self) -> None:
            self.yard = RagdollYard(self.physics, CharacterModel.load(sample_model_url(MODEL)))
            self.sg = self.yard.scene()
            self.animate(self.yard.update)
            for key, handler in (('h', self.yard.strike), ('k', self.yard.knock_down),
                                 ('g', self.yard.get_up), ('p', self.yard.toggle_power)):
                self.addEventHandler('keypress', name=key,
                                     function=lambda event, handler=handler: handler())
            print(__doc__, flush=True)

    RagdollContext.ContextMainLoop()
    return 0


if __name__ == '__main__':                      # pragma: no cover - needs a window
    main()
