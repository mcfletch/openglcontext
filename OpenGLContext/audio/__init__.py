"""Spatial audio for OpenGLContext scenes.

The data model is glTF's ``KHR_audio_emitter`` extension, which is the Web Audio
API's ``PannerNode`` model: an emitter has a *distance* curve, an optional
directional *cone*, and a *gain*, and a listener hears it panned about its own
forward axis.  Choosing a published model rather than inventing one means a
scene authored in Blender or Godot plays here with no translation layer, and it
is the same decision :mod:`OpenGLContext.physics` made with the OMI physics
extensions.

The pieces, in the order sound travels through them:

=========================  ====================================================
:mod:`~.model`             ``KHR_audio_emitter`` as typed records: audio data,
                           sources, emitters and their positional properties.
:mod:`~.clip`              Files decoded to mono float32 samples, cached by path.
:mod:`~.spatial`           The listener's pose and every gain curve: distance,
                           cone, VRML97 ellipsoid, and equal-power panning.
:mod:`~.mixer`             A fixed pool of voices summed into stereo blocks.
:mod:`~.device`            Where those blocks go -- ``miniaudio``, or silence.
:mod:`~.engine`            The one object an application holds, tying the rest
                           together and keeping decoding off the audio thread.
=========================  ====================================================

Sound is **optional and never fatal**.  The ``miniaudio`` backend may be absent
and a device may fail to open; both end in one warning and a silent run, so a
machine with no sound card is simply a machine with no sound.

See ``docs/audio.html`` for the data-flow diagrams and a worked example.
"""

from OpenGLContext.audio.clip import Clip, ClipCache, DecodeError, decode_file
from OpenGLContext.audio.device import (
    AudioDevice, DeviceError, MiniaudioDevice, NullDevice, miniaudio_available,
    open_device,
)
from OpenGLContext.audio.engine import AudioEngine
from OpenGLContext.audio.mixer import Mixer, Voice, VoiceHandle
from OpenGLContext.audio.model import (
    Audio, AudioDocument, AudioEmitter, AudioSource, PositionalProperties,
    from_gltf, to_gltf,
)
from OpenGLContext.audio.spatial import (
    DistanceModel, Listener, ShapeType, cone_gain, distance_gain, ellipsoid_gain,
    ellipsoid_reach, equal_power_pan,
)

__all__ = [
    'Audio', 'AudioDevice', 'AudioDocument', 'AudioEmitter', 'AudioEngine',
    'AudioSource', 'Clip', 'ClipCache', 'DecodeError', 'DeviceError',
    'DistanceModel', 'Listener', 'MiniaudioDevice', 'Mixer', 'NullDevice',
    'PositionalProperties', 'ShapeType', 'Voice', 'VoiceHandle', 'cone_gain',
    'decode_file', 'distance_gain', 'ellipsoid_gain', 'ellipsoid_reach',
    'equal_power_pan', 'from_gltf', 'miniaudio_available', 'open_device',
    'to_gltf',
]
