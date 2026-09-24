Audio Engine Internals
======================

.. rst-class:: introduction

How the sound engine is built: the threads, the modules, the gain curves, the
mixer and the clip cache. This page is for extending OpenGLContext or
``omi_audio``, or for using ``omi_audio`` without OpenGLContext. Using sound in
an application is covered in :doc:`audio`.

The engine is the separate `omi_audio <https://github.com/mcfletch/omi_audio>`__
package: the ``KHR_audio_emitter`` data model, the gain curves, the clip cache,
the mixer, the device interface and the engine object. It has no scenegraph
code, and a project with no renderer, or a different one, can use it on its
own. OpenGLContext adds the ``AudioEmitter``, ``AudioSource`` and ``Sound``
nodes, and one engine per context that the render pass drives.

.. _audio-dataflow:

How sound reaches the device
----------------------------

Two threads are involved. Everything expensive, everything that can fail, and
everything that needs to know about the world runs on the control thread,
which is the render loop. The audio thread only multiplies and adds numbers.

.. figure:: images/diagrams/audio-1.svg
   :alt: Data flow from a URL through decoding, spatialisation and mixing to the device
   :class: diagram

   The left side runs once per frame, in the render loop. The right side runs
   on the device's own thread, tens of times a second, and uses only numpy
   arrays that already exist.

The data passed between the threads is a pair of gains and a playback rate
for each playing sound. When an emitter moves, its sound is not restarted,
re-resolved or re-decoded: the voice's target gains are overwritten, and the
mixer ramps to them over the next block.

The render pass collects every ``Auditory`` node path while it walks the
scene, and calls ``FlatPass.renderAudio()``, which calls
``OpenGLContext.audio.scene.update()``. That opens the context's engine if
there is something audible, moves the listener to the camera, copies the
player's volume from the settings, and calls ``updateAudio()`` on each node
with its accumulated world matrix.

.. _pipeline:

The module chain
----------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Module
     - Provides
     - Depends on
   * - ``omi_audio/model.py``
     - ``KHR_audio_emitter`` as typed records, with the extension's own field
       names and defaults; ``from_gltf`` and ``to_gltf``
     - ``spatial``
   * - ``omi_audio/spatial.py``
     - Every gain curve, and the listener
     - numpy
   * - ``omi_audio/clip.py``
     - Files decoded once to mono float32 samples; the ``ClipCache``
     - ``miniaudio`` (optional)
   * - ``omi_audio/formats.py``
     - Which encodings this machine can decode
     - ``clip``, ``_opus``
   * - ``omi_audio/library.py``
     - A glTF document's audio, chosen among its encodings and fetched
       through the caller's resolver
     - ``model``, ``formats``
   * - ``omi_audio/synth.py``
     - Generated tones, noise, chirps, impacts and rumbles
     - ``clip``
   * - ``omi_audio/mixer.py``
     - The voice pool and the block mixing
     - ``clip``, ``spatial``
   * - ``omi_audio/device.py``
     - The output device, and the silent fallback when there is none
     - ``miniaudio`` (optional)
   * - ``omi_audio/engine.py``
     - The one object an application holds
     - all of the above
   * - *— the package boundary —*
     -
     -
   * - ``OpenGLContext/audio/scene.py``
     - One engine per context, driven each frame
     - ``omi_audio.engine``
   * - ``OpenGLContext/audio/areas.py``
     - ``box_gain()``: an area's level at the listener's position
     - numpy
   * - ``OpenGLContext/audio/settings.py``
     - The player's switch, volume and voice budget, as a
       ``ContextDefinition`` sub-node
     - the field system
   * - ``OpenGLContext/scenegraph/audio.py``
     - The ``AudioEmitter``, ``AudioSource`` and ``Sound`` nodes
     - ``omi_audio.model``, ``omi_audio.spatial``
   * - ``OpenGLContext/loaders/gltf/scene.py``
     - ``audio_library`` and ``_audio_emitters``: a document's emitters as
       nodes under their glTF nodes
     - ``omi_audio.model``, ``omi_audio.library``

The mixer imports no path, no matrix and no listener: it receives gains and
produces blocks of samples.

.. _curves:

Gain curves
-----------

A sound's level at the listener is the product of independent factors, each a
function in ``omi_audio.spatial``:

.. code-block:: text

   level = source.gain
         × emitter.gain
         × distance_gain(distance, model, refDistance, maxDistance, rolloff)
         × cone_gain(angle, coneInnerAngle, coneOuterAngle, coneOuterGain)

   left, right = equal_power_pan(azimuth)
   voice.set_gain(level * left, level * right)

``AudioEngine.gains_for()`` computes it for one emitter.

Distance
~~~~~~~~

The three models are ``KHR_audio_emitter``'s, which takes them from Web
Audio's ``PannerNode``. ``d`` below is never less than ``refDistance``.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - ``distanceModel``
     - Gain
     - Reaches silence?
   * - ``inverse`` (default)
     - ``ref / (ref + rolloff × (d − ref))``
     - No; it approaches zero.
   * - ``linear``
     - ``1 − rolloff × (d − ref) / (max − ref)``
     - Yes, at ``maxDistance``.
   * - ``exponential``
     - ``(d / ref) ^ (−rolloff)``
     - No; it approaches zero, faster than ``inverse``.

Only ``linear`` uses ``maxDistance``. A ``linear`` emitter with the default
``maxDistance`` of 0 is at full level inside ``refDistance`` and silent
outside it. An application that wants ``maxDistance`` to act as a cut-off for
every model can test ``PositionalProperties.in_range()`` in
``omi_audio.model`` and not start sounds out of range; there, a
``maxDistance`` of 0 means no limit.

Direction: the cone
~~~~~~~~~~~~~~~~~~~

Both cone angles are angular diameters, so each boundary is at half its angle
from the axis. Inside the inner cone there is no attenuation, outside the
outer cone the gain is ``coneOuterGain``, and between the two it changes
linearly. Both default to 2π, so an emitter that sets neither is not
attenuated by direction. The emitter points along its own −Z, as glTF cameras
and ``KHR_lights_punctual`` lights do.

Panning
~~~~~~~

The source's position is converted to the listener's frame, giving an azimuth
in the horizontal plane: 0 straight ahead, positive to the right. The azimuth
sets a pair of ear gains on a quarter circle, with ``left² + right² = 1`` at
every angle, so panning moves a sound across the stereo field without
changing its loudness. A sound straight ahead is −3 dB in each ear.

A source behind the listener is folded onto its mirror image in front, so a
sound behind and to the right pans right. Web Audio specifies this fold; two
loudspeakers cannot place a sound behind the listener.

.. _aim-rate:

How often a playing sound is re-aimed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For a playing sound, ``AudioEmitter`` recomputes the distance curve, the cone,
the azimuth and the pan fifteen times a second, not every frame; the interval
is ``OpenGLContext.scenegraph.audio.AIM_INTERVAL``. A source's
``playbackRate`` is copied to its voice every frame, since it is a single
float and a pitch that moved in steps would be heard as steps.

A listener walking at a few metres a second changes the gains by a small
fraction per frame, and the mixer ramps between values rather than stepping.
The computation runs for every emitter in a level; a level with many sounds
spends about two milliseconds a frame on it on the reference machine when it
runs every frame. At fifteen times a second the steps are not audible and the
cost does not grow with the frame rate.

The interval does not delay the start of a sound: a source is aimed the first
time it is seen. Emitters are given staggered phases, so they do not all
re-aim in the same frame.

.. _audio-ellipsoids:

VRML97's ellipsoids
~~~~~~~~~~~~~~~~~~~

The ``Sound`` node uses the model VRML97 specifies: two ellipsoids sharing a
focus at the sound, with a ramp between them that is linear in decibels.

.. figure:: images/diagrams/audio-2.svg
   :alt: Two nested ellipsoids around a sound location, with the ramp between them
   :class: diagram

   The sound is at a focus of both ellipsoids, not at their centre, so a
   forward-facing sound reaches much further ahead than behind. The reach at
   angle θ is ``2 f b / ((f+b) − (f−b) cos θ)``: the front and back distances
   along the axis, and their harmonic mean at right angles.

At the outer ellipsoid the ramp has reached −20 dB, which the specification
treats as inaudible, and beyond it the gain is zero. The mixer ramps every
gain change across a block, so the step from 0.1 to 0 produces no click.

The geometry is ``omi_audio.spatial.ellipsoid_gain_at(location, direction,
listener_position, ...)``, which takes three world-space vectors. The node
transforms its ``location`` and ``direction`` into world space, multiplies by
``intensity``, and pans. A zero ``direction`` has no front or back, so the
``front`` distances apply in every direction. A ``set_pitch`` on an active
``AudioClip`` is ignored, as VRML97 specifies.

.. _mixer:

The mixer
---------

The mixer runs on the audio thread, where a late block is heard as a click.
That sets how it is built:

- Fixed voice pool - ``Voice`` slots are created once, when the mixer is
  constructed, and reused. Starting a sound configures a slot and allocates
  nothing.

- Buffers made once - ``Mixer.mix()`` writes into pre-allocated arrays through
  numpy's ``out=`` parameters and returns a view. An allocation on the audio
  thread can start a garbage collection on the audio thread.

- No blocking work - the audio thread does not block, decode, resolve paths or
  log. That work happens on the control thread before a clip reaches a voice.

- Lock on the control side only - ``Mixer.play()`` takes a lock so that two
  control threads cannot claim the same slot. Mixing never takes it.

Each voice reads its clip at ``rate`` clip samples per output frame, with
linear interpolation, so a clip at another sample rate and a
``playbackRate`` other than 1 are the same operation.

Gain ramping
~~~~~~~~~~~~

Each ear's gain is interpolated from its value at the end of the last block
to the target the control thread set, reaching the target on the block's last
sample, so a gain change does not click. A new voice starts at its gain
without a ramp, so the attack of a sound such as a gunshot stays sharp.

.. _audio-stealing:

Voice stealing
~~~~~~~~~~~~~~

When every voice is busy, a new sound is compared with the weakest sound
playing, first by ``priority`` and then by how loud it currently is, and
either takes that voice or is refused. Stealing the quietest sound of the
lowest priority is the least audible choice.

Because a voice can be taken back, ``play()`` returns a ``VoiceHandle``, not
the slot. The handle records which sound it was made for, and once that
sound's slot is reused, calls on the handle do nothing:

.. code-block:: python

   handle = engine.play('explosion.wav', priority=0.9)
   ...
   handle.set_gain(0.2, 0.4)   # does nothing once the sound has ended
   handle.set_rate(0.8)        # likewise
   handle.stop()               # likewise

A looping ``AudioSource`` whose voice is stolen takes one again when one is
free, so ambience silenced during a busy moment returns. A one-shot that lost
its voice does not.

.. _mixer-muffle:

The muffle filter
~~~~~~~~~~~~~~~~~

``Mixer.muffle`` blends the mix towards a low-passed copy of itself. The
filter is two cascaded moving averages, each computed as the difference of a
running sum, so a window of any length costs one pass over the block.

The corner is a fixed frequency, 450 Hz, not a fraction of the sample rate: a
fraction of Nyquist would sit in the middle of the audible range at 8 kHz and
above everything audible at 44.1 kHz. The response at 44.1 kHz:

.. list-table::
   :widths: auto

   * - Frequency
     - 100 Hz
     - 330 Hz
     - 450 Hz
     - 660 Hz
     - 1 kHz
     - 2 kHz
     - 4 kHz
   * - Gain
     - −0.1 dB
     - −1.6 dB
     - −3.0 dB
     - −6.7 dB
     - −17.6 dB
     - −26.5 dB
     - −59 dB

.. _formats:

Clips and the cache
-------------------

A ``Clip`` is the one format the mixer accepts: one channel of float32
samples at one sample rate. ``miniaudio`` resamples and converts channels
while decoding, so a file becomes a clip in one pass.

``ClipCache`` is keyed by name, so a sound played many times is decoded once.
A name that fails to decode is cached as a failure: a missing file logs one
warning, not one per play. The cache does not normalise a name or check it
against the filesystem; the caller resolves it first.

A clip given through ``AudioSource.useClip()`` or ``ClipCache.put()`` is
resampled to the engine's rate if it is not already at it, because the mixer
runs at the rate the device was opened at.

Resolving audio references
~~~~~~~~~~~~~~~~~~~~~~~~~~

``omi_audio`` never resolves, opens or interprets a document's ``uri``. A
scene file may come from a third party, and a reference in it may be
relative, absolute, percent-encoded, a ``data:`` URI, an ``http:`` URL, or an
attempt to escape the content directory; only the loader has the document's
location and the rules for what it may reach.

Audio references go through the loader's ``Resolver`` (see :doc:`untrusted`),
and the resolved bytes go to ``omi_audio.AudioLibrary``, which decodes them
and keeps the result for the document. In ``loaders/gltf/scene.py``,
``audio_library`` builds the library with ``_fetch_audio`` as its fetch
callback, and ``_audio_emitters`` resolves a node's or a scene's references
through ``AudioDocument.emitters_for_node`` and ``emitters_for_scene``.
``omi_audio.model.to_gltf`` writes the model back out, leaving out every field
at its default.

A source built from a glTF document gets its samples through
``AudioSource.useLibrary()``, which takes the document's source record rather
than an audio index, because the library chooses between the encodings the
source offers. For such a source, ``url`` records where the sound is, for
display, and the library supplies the bytes. ``url`` is empty for audio with no
location: a ``bufferView``, a ``data:`` URI, or a reference the resolver
refuses.

Choosing among encodings
~~~~~~~~~~~~~~~~~~~~~~~~

``omi_audio.formats.decodable()`` asks each decoder which formats it reads, so
the answer follows what is installed. Vorbis is decoded by ``miniaudio``; Opus
by ``libopus`` through ``omi_audio._opus``, which uses the library from
``opuslib-next-bundled`` or, without it, one already on the system. The two are
reported separately: a machine with ``libopus`` and no ``miniaudio`` decodes
Opus but not the MP3 fallback.

Every encoding a source offers goes into ``url``, better first, including ones
this build cannot decode. ``AudioLibrary.clip_for()`` chooses which encoding
is fetched and requests only codecs it can decode. If the better encoding
cannot be resolved it uses the MP3; if it is still downloading it waits for it
rather than playing the MP3 in the meantime. An application with its own
decoder adds that encoding to ``library.encodings``, and the library requests
it from then on.

.. _audio-silent-paths:

The silent paths
----------------

``open_device()`` does not raise. A missing ``miniaudio``, a device that will
not open, and the backend falling back to its own null output all return a
``NullDevice`` after one warning. In ``omi_audio``, ``tests/test_device.py``
covers each of them, including a test that forces the import to fail, and
``tests/test_clip.py`` covers decoding with the backend removed.

.. _audio-testing:

Testing sound without a sound card
----------------------------------

Most of the engine is arithmetic on arrays, and a test can check the arrays.
Build an engine on a ``NullDevice`` and read the mix; a silent device pulls
nothing, so a voice advances only when the test calls ``mix()``:

.. code-block:: python

   from omi_audio.device import NullDevice
   from omi_audio.engine import AudioEngine
   from omi_audio import synth

   engine = AudioEngine(device=NullDevice(sample_rate=8000), voices=8)
   engine.mixer.play(synth.tone(440.0, 1.0, sample_rate=8000), pan=1.0)
   block = engine.mixer.mix(64)          # (64, 2) float32
   assert block[:, 0].max() < 1e-9       # nothing in the left ear
   assert block[:, 1].max() > 0.1        # and plenty in the right

Scene nodes are tested the same way: call ``updateAudio(engine, matrix, now)``
as the render pass would, then read ``engine.active_voices`` or the mix.

``omi_audio``'s own suite tests the curves at known distances and angles,
panning on each side of the listener, voice stealing under load, the gain
ramp, the muffle's frequency response, the glTF round trip, both silent paths,
and the level in dBFS at the device for a source at a given position. One test
checks that mixing a full pool for twenty blocks allocates nothing
measurable. OpenGLContext's ``tests/unit/test_audio_*.py`` test what
OpenGLContext adds: the nodes, the per-context engine, the render-pass wiring
and the glTF import.
