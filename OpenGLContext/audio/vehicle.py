"""A road vehicle's sound as a piece of scene.

:class:`VehicleSoundtrack` owns one ``global`` :class:`AudioEmitter` with four
sources -- the motor, tyre and wind loops and a one-shot impact -- and writes
:class:`omi_audio.vehicle.VehicleSound`'s gains and rates onto them once a
frame from an ``omi_physics`` vehicle: its speed, its wheels' ``slip`` and
``grounded``, and its ``throttle``.

    track = VehicleSoundtrack(VehicleSoundTuning(tyre_scrub_at=3.5))
    scene.children.append(track.node)
    ...
    track.update(dt, vehicle)           # once a frame, after the physics
    track.hit(closing_speed)            # when the physics reports a contact

The emitter is ``global``: the listener rides in this vehicle, so its sound is
not placed or panned. With no audio device the nodes still traverse and
nothing plays.
"""
from __future__ import annotations

from typing import Any

from omi_audio import model
from omi_audio.clip import DEFAULT_SAMPLE_RATE, Clip
from omi_audio.vehicle import (
    DEFAULT_TUNING,
    VehicleSound,
    VehicleSoundTuning,
    impact_clip,
    motor_clip,
    tyre_clip,
    wind_clip,
)

from OpenGLContext.scenegraph.audio import AudioEmitter, AudioSource

__all__ = ['VehicleSoundtrack']


def _looping(clip: Clip) -> AudioSource:
    """A continuous voice, started once and never stopped: a silent vehicle is
    its loops playing at nothing, so no silence starts or ends with a click."""
    source = AudioSource(loop=True, autoplay=True, gain=0.0)
    source.useClip(clip)
    return source


class VehicleSoundtrack:
    """A vehicle's voices as scene nodes, and what feeds them.

    Mount :attr:`node` anywhere in the scene. :attr:`sound` is the
    :class:`~omi_audio.vehicle.VehicleSound` that decides the levels.
    """

    def __init__(self, tuning: VehicleSoundTuning = DEFAULT_TUNING,
                 sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self.sound = VehicleSound(tuning)
        self.motor = _looping(motor_clip(tuning, sample_rate))
        self.tyres = _looping(tyre_clip(tuning, sample_rate))
        self.wind = _looping(wind_clip(tuning, sample_rate))
        #: Silent until :meth:`hit` plays it.
        self.impact = AudioSource(loop=False, autoplay=False, gain=0.0)
        self.impact.useClip(impact_clip(tuning, sample_rate))
        #: What to put in the scene.
        self.node = AudioEmitter(
            type=model.GLOBAL,
            sources=[self.motor, self.tyres, self.wind, self.impact])

    def update(self, dt: float, vehicle: Any, speed: float | None = None
               ) -> None:
        """Read ``vehicle`` and write this frame's levels onto the nodes.

        ``vehicle`` has ``wheels`` (each with ``slip`` and ``grounded``), a
        ``throttle`` and a ``speed()``; ``speed`` in m/s is used in place of
        ``vehicle.speed()`` where given.
        """
        wheels = list(getattr(vehicle, 'wheels', ()))
        grounded = any(wheel.grounded for wheel in wheels)
        slip = (sum(abs(float(wheel.slip)) for wheel in wheels) / len(wheels)
                if wheels else 0.0)
        self.sound.update(
            dt, speed=vehicle.speed() if speed is None else speed, slip=slip,
            throttle=abs(float(vehicle.throttle)), grounded=grounded)
        self.motor.gain = self.sound.motor.gain
        self.motor.playbackRate = self.sound.motor.rate
        self.tyres.gain = self.sound.tyres.gain
        self.wind.gain = self.sound.wind.gain

    def hit(self, closing: float) -> float:
        """Play the impact at the gain ``closing`` m/s gives; returns the gain,
        0 for a touch too gentle to sound."""
        gain = self.sound.hit(closing)
        if gain > 0.0:
            self.impact.gain = gain
            self.impact.play()
        return gain
