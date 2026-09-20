Spatial Audio
=============

.. rst-class:: introduction

OpenGLContext plays sound that is *in* the scene: an emitter under a
``Transform`` is heard from where that transform is, fades with distance, can
be aimed like a spotlight, and pans as you walk past it. The data model is
**not** a private format — it is glTF's `KHR_audio_emitter
<https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0/KHR_audio_emitter>`__
extension, which is the Web Audio ``PannerNode`` model, so a scene authored in
Blender or Godot arrives with its sound intact and no translation layer.
VRML97's own ``Sound`` node is implemented too, on the same machinery. The
mixing is ours, in numpy, so nothing here depends on a copyleft audio library,
and every gain curve is a testable function of geometry. The indented
technical notes point at the code.

**The engine itself is a separate package, `omi_audio
<https://github.com/mcfletch/omi_audio>`__**, which OpenGLContext depends on
the way it depends on ``omi_physics``. It holds the data model, every gain
curve, the clip cache, the mixer, the device seam and the engine, and it knows
nothing about a scenegraph. What is in OpenGLContext is the two integrations:
the ``AudioEmitter``, ``AudioSource`` and ``Sound`` nodes, and the per-context
engine the render pass drives. The split means a project with no renderer — or
a different one — can use the sound without taking OpenGLContext, and the
mixer can be tested without one.

.. _audio-quickstart:

The shortest thing that makes a noise
-------------------------------------

Put an ``AudioEmitter`` under a ``Transform``. That is the whole of it — there
is no engine to create, no device to open and nothing to update per frame:

.. code-block:: python

   from OpenGLContext.scenegraph.basenodes import (
       AudioEmitter, AudioSource, Transform,
   )

   fountain = Transform(translation=(3, 0, -5), children=[
       AudioEmitter(
           gain=0.8,                 # linear, not decibels
           refDistance=2.0,          # full volume within 2 metres
           rolloffFactor=1.0,        # how fast it fades past that
           sources=[AudioSource(url=['water.ogg'], loop=True)],
       ),
   ])

The render pass finds the emitter while it is collecting the frame's nodes,
works out where it is from the transforms above it, and keeps it aimed at the
camera. The camera *is* the listener.

.. rst-class:: technical

The nodes are in ``OpenGLContext/scenegraph/audio.py``; the pass calls
``FlatPass.renderAudio()``, which is four lines and delegates to
``OpenGLContext.audio.scene.update()``.

**Sound costs nothing until a scene has some.** No device is opened, and no
audio thread starts, until a frame is drawn containing something audible.
Every existing OpenGLContext demo is untouched.

The three ways a sound recurs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A source plays once, loops, or comes back on a timer, and the third is not the
second. Ambience is full of sounds an author meant to be *occasional* — a
distant rumble every half minute, a drip, a creak — and looping one of those
gives a continuous noise where a sparse one was wanted.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Wanted
     - Fields
   * - Plays once and is done
     - the default
   * - Continuous
     - ``loop=True``
   * - Every 30 seconds or so
     - ``repeatInterval=30.0, repeatVariance=5.0``

.. code-block:: python

   AudioSource(url=['distant-thunder.wav'],
               repeatInterval=30.0,      # seconds of quiet between plays
               repeatVariance=5.0)       # ±5s, so two of them drift apart

The interval is measured from the frame the clip was noticed to have *ended*,
so a long clip and a short one leave the same gap of quiet. ``repeatVariance``
is what keeps two speakers of the same sound from beating together for ever;
the wait it produces is never negative. Both are ignored while ``loop`` is
set, because a loop has no gaps to time.

``repeatInterval``, ``repeatVariance`` and ``priority`` are the three fields
that go beyond ``KHR_audio_emitter``. The extension has nowhere to say any of
them and ambience wants all three.

**A one-shot that has finished stays finished.** Without the fields above,
nothing restarts it — not on the next frame, not on any later one. A *looping*
source that stopped is a different matter: nothing ends a loop but voice
stealing, so it may take a voice again once one frees, which is what ambience
silenced by a busy moment should do.

.. _audio-dataflow:

How a sound gets from a file to your ears
-----------------------------------------

There are two threads and they meet in exactly one place. Everything
expensive, everything that can fail, and everything that needs to know about
the world happens on the **control thread**; the **audio thread** multiplies
numbers and adds them up.

.. figure:: images/diagrams/audio-1.svg
   :alt: Data flow from a URL through decoding, spatialisation and mixing to the device
   :class: diagram

   Everything on the left happens once per frame, in the render loop. Everything
   on the right happens on the device's own thread, tens of times a second, and
   touches nothing but numpy arrays that already exist.

The one thing crossing the boundary is **a pair of floats per playing sound**.
A moving emitter is not restarted, re-resolved or re-decoded; its voice's
target gains are overwritten, and the mixer ramps to them across the next
block.

.. rst-class:: technical

``omi_audio/engine.py`` owns the left-hand side, ``omi_audio/mixer.py`` the
right. The mixer imports no path, no matrix and no listener: it is handed
gains and produces blocks.

.. _pipeline:

The module chain
----------------

The table below is divided by a marked row, *the package boundary*. Above it
is the ``omi_audio`` package, which has no idea a scenegraph exists; below it
is OpenGLContext's own code, which is where the two meet.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Module
     - Answers
     - Depends on
   * - ``omi_audio/model.py``
     - ``KHR_audio_emitter`` as typed records, with the extension's own field names
       and defaults; glTF round-trips through ``from_gltf``/``to_gltf``
     - ``spatial``
   * - ``omi_audio/spatial.py``
     - Every gain curve, and where the listener is
     - numpy
   * - ``omi_audio/clip.py``
     - Files → mono float32 samples, decoded once
     - ``miniaudio`` (optional)
   * - ``omi_audio/synth.py``
     - Tones, noise, chirps and impacts made out of arithmetic
     - ``clip``
   * - ``omi_audio/mixer.py``
     - The voice pool and the block mixing
     - ``clip``, ``spatial``
   * - ``omi_audio/device.py``
     - Where blocks go, and what to do when nowhere
     - ``miniaudio`` (optional)
   * - ``omi_audio/engine.py``
     - The one object an application holds
     - all of the above
   * - *— the package boundary —*
     -
     -
   * - ``OpenGLContext/audio/scene.py``
     - Attaching an engine to a context and driving a frame
     - ``omi_audio.engine``
   * - ``OpenGLContext/audio/settings.py``
     - The player's switch, volume and voice budget, as a ``ContextDefinition``
       sub-node
     - the field system
   * - ``OpenGLContext/scenegraph/audio.py``
     - The ``AudioEmitter``, ``AudioSource`` and ``Sound`` nodes
     - ``omi_audio.model``, ``omi_audio.spatial``

.. _curves:

The gain curves, and why there are four of them
-----------------------------------------------

A sound's loudness at the listener is a **product of independent factors**,
each a small pure function. Splitting them this way is what makes each of them
testable in isolation and replaceable without touching the others.

.. code-block:: bash

   level = source.gain
         × emitter.gain
         × distance_gain(distance, model, refDistance, maxDistance, rolloff)
         × cone_gain(angle, coneInnerAngle, coneOuterAngle, coneOuterGain)

   left, right = equal_power_pan(azimuth)
   voice.set_gain(level * left, level * right)

Distance
~~~~~~~~

Three models, taken from ``KHR_audio_emitter``, which takes them from
Web Audio. ``refDistance`` is the radius inside which nothing is attenuated;
``maxDistance`` is where the fall stops (**zero means never**, which is the
extension's default).

.. list-table::
   :widths: auto
   :header-rows: 1

   * - ``distanceModel``
     - Gain
     - Reaches silence?
   * - ``inverse`` (default)
     - ``ref / (ref + rolloff × (d − ref))``
     - No — asymptotic. The physically natural one.
   * - ``linear``
     - ``1 − rolloff × (d − ref) / (max − ref)``
     - Yes, at ``maxDistance``. Needs one set.
   * - ``exponential``
     - ``(d / ref) −rolloff``
     - No — asymptotic, but falls faster than inverse.

Reach for ``linear`` when a sound must be *gone* past a certain range — it is
the only one that gets there — and ``inverse`` for anything meant to sound
like a real object in a real room.

Direction: the cone
~~~~~~~~~~~~~~~~~~~

Set ``shapeType='cone'`` and an emitter radiates like a spotlight. Both angles
are **angular diameters**, side to side, so the boundary is at half of each.
Inside the inner cone nothing is attenuated; outside the outer cone the gain
is ``coneOuterGain``; between them it interpolates linearly. The defaults are
a full turn, which is why an emitter that sets none of them is never
attenuated by direction. The emitter points along its own **−Z**, as glTF
cameras and ``KHR_lights_punctual`` do.

Panning
~~~~~~~

The source is put into the listener's own frame — azimuth in the horizontal
plane, 0 straight ahead and positive to the right — and the azimuth becomes a
pair of ear gains that trace a quarter circle: ``left² + right² = 1`` at every
angle. Panning therefore moves a sound across the stereo field without
changing how loud it is. A sound dead ahead is −3 dB in each ear; that is not
a bug, it is what constant power means.

A source *behind* the listener folds onto its mirror image in front:
behind-and-right pans right. Two loudspeakers cannot put a sound behind
anybody, and the fold is what Web Audio specifies rather than something chosen
here.

.. _aim-rate:

How often a playing sound is re-aimed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All of the above — the distance curve, the cone, the azimuth and the pan — is
worked out for a *playing* sound fifteen times a second rather than once a
frame. The interval is ``OpenGLContext.scenegraph.audio.AIM_INTERVAL``.

What it produces is a pair of volumes that move continuously and slowly: a
listener walking at a few metres a second changes them by a fraction over a
frame, and the mixer ramps between values rather than stepping to them. What
it costs is paid by every emitter in a level on every frame, so a level with a
busy soundscape spends a measurable part of its frame there — about two
milliseconds on the reference machine. Fifteen a second is faster than the
result can audibly step and slow enough that the cost stops scaling with the
frame rate.

**Starting** a sound is not delayed by it: a source is aimed the first time it
is seen, so a sound is placed before it is heard. The interval governs only
how often one already playing is asked again. Emitters take staggered phases
so a level's worth of them do not all re-aim on one frame, which would turn
the saving into a stutter.

VRML97's ellipsoids
~~~~~~~~~~~~~~~~~~~

The ``Sound`` node describes something none of the above can: **two ellipsoids
sharing a focus at the sound**, with a ramp between them that is linear in
*decibels*. It is implemented rather than approximated, because approximating
a published specification is how a world stops sounding the way its author
heard it.

.. figure:: images/diagrams/audio-2.svg
   :alt: Two nested ellipsoids around a sound location, with the ramp between them
   :class: diagram

   The sound sits at a *focus* of both ellipsoids, not at their centre, which is
   why a forward-facing sound reaches much further ahead of itself than behind.
   The reach at any angle collapses to ``2 f b / ((f+b) − (f−b) cos θ)`` — each
   distance along the axis, and their harmonic mean at right angles.

At the outer ellipsoid the ramp has reached −20 dB, which the specification
calls inaudible, and beyond it the gain is zero. That step from 0.1 to 0 *is*
a discontinuity — and it is left alone, because the mixer ramps every gain
change across a block anyway. The curve stays the specification's own; the
smoothing happens where smoothing belongs.

.. _mixer:

The mixer, and why it looks the way it does
-------------------------------------------

Everything about the mixer's shape follows from one fact: it runs on the audio
thread, and the audio thread must never be late. Miss a block and you do not
get a slow frame, you get a click.

- **The pool is fixed.** ``Voice`` slots are made once, at construction, and
  reused for ever. Starting a sound configures a slot; it never allocates one. A
  scene firing a thousand sounds a second costs what a scene firing ten does.

- **The buffers are made once too.** ``Mixer.mix()`` writes through numpy's
  ``out=`` parameters into pre-allocated arrays and returns a *view*. An
  allocation on the audio thread is a garbage collection on the audio thread.

- **Nothing there blocks, decodes, resolves a path or logs.** Those all happen
  on the control thread, before a clip reaches a voice.

- **The lock is control-side only.** ``Mixer.play()`` takes it so two *control*
  threads cannot claim one slot. The mixing never takes it.

Gain ramping
~~~~~~~~~~~~

A gain that jumps from one block to the next is a step, and a step is a click.
Each ear's gain is therefore interpolated from where the last block left it to
where the control thread has aimed it, reaching the target on the block's
final sample. A *new* voice, by contrast, starts at its gain with no ramp —
ramping in would soften the transient that makes a gunshot read as a gunshot.

Voice stealing
~~~~~~~~~~~~~~

The pool has to be able to refuse, and to take back. When every voice is busy,
the newcomer is ranked against the weakest one playing — by ``priority``
first, then by how audible it currently is — and either steals it or is
refused. Stealing the quietest sound of the lowest priority is the least
audible theft available.

Because a slot can be taken back, ``play()`` hands out a ``VoiceHandle``
rather than the slot itself. A handle remembers *which* sound it was for, so a
caller still steering a sound whose slot was recycled steers nothing instead
of steering somebody else's explosion. That mistake is silent, intermittent
and very hard to find, which is why it is designed out rather than documented.

.. code-block:: python

   handle = engine.play('explosion.wav', priority=0.9)
   ...
   handle.set_gain(0.2, 0.4)   # does nothing at all once the sound has gone
   handle.stop()               # likewise; no caller ever has to test first

Muffling
~~~~~~~~

``mixer.muffle`` runs from 0 (clear) to 1 (underwater) and blends the mix
towards a low-passed copy of itself. Two cascaded moving averages, each taken
as the difference of a running sum, so a window of any length costs one pass
over the block.

The corner is **a frequency** — 450 Hz — and not a fraction of the sample
rate, which matters more than it looks: "muffled" is a judgement about the
sound, so a corner set as a share of Nyquist would sit in the middle of the
register at 8 kHz and above everything audible at 44.1 kHz. At 44.1 kHz:

.. list-table::
   :widths: auto

   * - Frequency
     - 100 Hz
     - 330 Hz
     - 450 Hz
     - 660 Hz
     - 1 kHz
     - 2 kHz
     - 4 kHz
   * - Gain
     - −0.1 dB
     - −1.6 dB
     - −3.0 dB
     - −6.7 dB
     - −17.6 dB
     - −26.5 dB
     - −59 dB

The bass comes through and the top goes, which is what makes it a *timbre*
change rather than a volume change. A pure sine has nothing above its
fundamental, so a low-pass can only alter how loud it is; anything meant to
show a filter off wants ``synth.tone(..., harmonics=N)``, which is what the
demo below uses. It is a blend rather than a switch so an application can fade
it in as a listener submerges.

.. code-block:: python

   engine.muffle = min(1.0, depth_below_surface / 0.5)

.. _silence:

Silence is a backend, not an error
----------------------------------

Sound can be unavailable two ways, and both end in the same place:

- **The package is absent.** ``miniaudio`` is an optional dependency of
  ``omi_audio``, pulled in by ``pip install OpenGLContext[audio]`` (or ``pip
  install omi_audio[playback]`` on its own).

- **No device opens.** A container with no ALSA or PulseAudio, a machine with no
  sound card, a device something else holds exclusively — or the backend falling
  back to its *own* null output, which means the same thing wearing a disguise.

Each produces **one warning and a silent run**: never an exception that
reaches the user, never a refusal to start. ``open_device()`` cannot raise. A
machine with no sound is a normal machine, continuous integration is one, and
audio must never be why an application will not start.

That makes the fallback real code that has to keep working, so it is tested
directly — including a test that forces the import to fail — rather than being
assumed.

.. rst-class:: technical

In ``omi_audio``, ``tests/test_device.py`` covers the absent-package path, the
will-not-open path and the backend's-own-null path; ``tests/test_clip.py``
covers decoding with the backend forced away.

.. _audio-settings:

Settings, and whose volume is whose
-----------------------------------

Sound is a **sub-node** of the ``ContextDefinition`` — ``definition.audio``,
an ``AudioSettings`` node — rather than loose fields, for the same reason the
movement modes are: it has more than one knob, they belong together, and a
node gets validation, defaults, serialisation and a generated settings page
from the field system.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Environment
     - Default
     - Means
   * - ``audio.enabled``
     - ``OPENGLCONTEXT_AUDIO``
     - on
     - Off opens no device and starts no thread. What a capture run, a benchmark or a
       headless build wants.
   * - ``audio.volume``
     - ``OPENGLCONTEXT_AUDIO_VOLUME``
     - 1.0
     - The *player's* volume, read every frame so a settings slider takes effect at
       once.
   * - ``audio.voices``
     - —
     - 32
     - How many sounds may play at once. A quality setting as much as a budget: a
       busy scene on a small pool loses its quietest sounds first.

They appear in the F10 settings screen under *Sound*, generated from the
node's fields like every other setting.

Two volumes, and they multiply
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is the one thing here that is easy to get wrong, and the symptom of
getting it wrong is a volume control that prints a new number and changes
nothing:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - 
     - Who owns it
     - Written by
   * - ``definition.audio.volume`` → ``engine.volume``
     - the **player**
     - the settings screen, a volume key. Re-read every frame.
   * - ``engine.master_gain``
     - the **application**
     - the application, once. How loud this scene is authored to be.

The mixer sees their product. Writing one over the other every frame — the
tempting shortcut — makes whichever loses last exactly one frame. A volume key
should therefore write ``context.contextDefinition.audio.volume``, not
``engine.master_gain``: that is the number the settings screen shows and the
one that is saved.

.. _formats:

Clips, formats and the cache
----------------------------

A ``Clip`` is the only shape of audio the mixer knows: **one channel of
float32 samples at one rate**. Everything is normalised to that on the way in,
because the alternative is a mixer that branches on sample format, channel
count and rate in its inner loop, sixty times a second, on the audio thread.

Mono is not a simplification but a requirement: a stereo source has already
decided where it sits in the stereo field, and a sound that has decided cannot
then be panned to where it actually is in the world. A stereo file is mixed
down as it is decoded.

``miniaudio`` decodes ``.wav``, ``.mp3``, ``.ogg`` (Vorbis) and ``.flac``, and
resamples and re-channels *while* decoding, so the normalising above is one
pass rather than a decode followed by two conversions. It is MIT-licensed, as
is every decoder it bundles — nothing in the chain is copyleft, which is the
reason it is the only audio package this project takes.

``ClipCache`` is keyed by name, so a sound fired sixty times a second decodes
once. A name that fails to decode is remembered as a failure: a missing file
warns once, not once per shot, and yields a silence rather than an exception.
The cache does not normalise a name or test it against the filesystem —
whatever a name means is settled before it gets there, which for a glTF
document is the job of the resolver.

``AudioSource.url`` is a *list*, most preferred first, and the first entry
that decodes wins. That is how the glTF codec extensions are read: offer the
better format, fall back to the one everything can play.

Each entry is resolved against the document the source was read from, and is
held to what that document may reach: a scene loaded from disk may play audio
**under its own directory**, and one fetched over ``http(s)`` may play
**same-origin** audio. An entry outside those bounds is skipped with a warning
and the next one is tried, so a scene that also offers a clip it is allowed to
reach still plays. A source built in application code has no document behind
it and is not confined — that name came from the application. The rules are
the same ones every other external reference follows; see
``loaders/resolver.py``.

A source built from a glTF document takes its samples from that document's
``omi_audio.AudioLibrary`` instead, through ``AudioSource.useLibrary()``,
which is handed the document's source record rather than an audio index —
choosing between the encodings a source offers is the library's job. A
document names its audio by index rather than by anything a node could open —
audio inside a ``.glb`` has no name at all — so ``url`` there records *where
the sound is*, for anything that displays it, while the library is what
produces the bytes. It is empty for audio that has no location: a
``bufferView``, a ``data:`` URI, or a reference the resolver refuses.

.. _codecs:

Codec extensions
~~~~~~~~~~~~~~~~

``KHR_audio_emitter`` guarantees only MP3. A document that wants a better
encoding offers it through a codec extension on the *source*, naming a second
entry in the same ``audio`` array that holds the same sound:

.. code-block:: json

   {"audio": 0, "extensions": {"OMI_audio_ogg_vorbis": {"audio": 1}}}

The source's own ``audio`` stays as the fallback, so one document plays
everywhere and sounds better where the codec is available. Both extensions are
read, kept and written back unchanged; only decoding differs.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Extension
     - Container / MIME
     - Suffix
     - Plays
   * - ``OMI_audio_ogg_vorbis``
     - Ogg, ``audio/ogg``
     - ``.ogg``
     - **yes**
   * - ``OMI_audio_opus``
     - Ogg or WebM, ``audio/opus``, ``audio/webm``
     - ``.opus``, ``.webm``
     - no — falls back to the MP3

``omi_audio.formats.decodable()`` asks the backend which formats it reads
rather than asserting a list, so this table follows the ``miniaudio`` that is
installed: it reads Vorbis and not Opus, and a build that gained Opus would be
used without any code changing. An Opus source therefore plays its MP3
fallback, and a document that offers Opus with *no* fallback says so by
putting the extension in ``extensionsRequired``.

Every encoding a source offers goes into ``url``, better first, including one
this build cannot decode — ``url`` says where the sound is. Which one is
actually fetched is ``AudioLibrary.clip_for()``, and it asks only for codecs
it can read. An encoding that will not resolve falls back to the MP3; one that
is merely still downloading is waited for, since falling through on "not here
yet" would play the worse encoding of every sound whose better one had not
landed. An application with its own decoder sets ``library.encodings`` and the
better encoding is asked for from then on.

Sounds with no files
~~~~~~~~~~~~~~~~~~~~

``omi_audio.synth`` makes clips out of arithmetic — a tone, a swept chirp,
white noise, a percussive impact. They cost nothing to redistribute, which is
why the demo below ships no assets, and they are genuinely useful as
placeholders: a game with a synthesised gunshot is a game that can be played
and tuned.

.. code-block:: python

   from omi_audio import synth
   engine.clips.put('ping', synth.impact(0.4, seed=1))
   engine.play('ping', priority=1.0)

To put one *in a scene* rather than play it directly, hand it to an
``AudioSource`` with ``useClip()``. There is nothing to name and nothing to
register: the source takes the clip, and everything after that is the path a
decoded clip takes, so a synthesised sound is positioned, attenuated, panned
and voiced exactly as any other.

.. code-block:: python

   source = AudioSource(loop=True, gain=0.0)
   source.useClip(synth.tone(400.0, 2.0, harmonics=7, fade=0.0))
   emitter = AudioEmitter(sources=[source])
   ...
   source.gain = 0.3            # every frame, from whatever is being simulated
   source.playbackRate = 1.8

That is how a sound a game *computes* is made — a motor note whose pitch is
road speed, wind that goes as the square of it, a footstep varied so two in a
row are not the same one twice. The clip arrives at the engine's own sample
rate, resampled if it is not already there, because the mixer runs at the rate
the device was opened at and a clip at another would play at the wrong pitch;
that is the same courtesy ``ClipCache.put()`` does a clip registered by name.
A clip handed over this way takes precedence over ``url`` and over a
document's audio library — an application that hands one over has said which
sound it means.

A loop wants a clip whose end meets its beginning. A ramp at each end —
``fade``, which every generator applies by default so a one-shot does not
click — becomes a pulse at the loop rate, which is a sound of its own. Pass
``fade=0.0`` and give ``tone()`` a whole number of cycles, or use ``rumble()``
with ``decay=0.0`` and ``attack=0.0``, which holds its level throughout and
joins noise to noise.

.. _gltf:

Loading sound from glTF
-----------------------

A document's ``KHR_audio_emitter`` block is read into the native model and
turned into scenegraph nodes as the scene is built. A node's emitters become
children of that node's ``Transform``; a scene's emitters — which the
extension requires to be ``global`` — hang off the root, where no transform
reaches them.

.. code-block:: python

   from OpenGLContext.loaders.gltf import loader
   scene = loader.load_gltf('room.gltf')   # its emitters are already in there

Audio arrives the three ways glTF allows, and all three work: a ``uri`` beside
the document, a ``data:`` URI inline, and a ``bufferView`` inside the file —
which is what a ``.glb``, the dominant shipping format, uses.

Who decides what a ``uri`` means
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**This does.** ``omi_audio`` never resolves, opens or interprets a document's
``uri``: a scene file comes from a third party, and a reference in one may be
relative, absolute, percent-encoded, a ``data:`` URI, an ``http:`` URL or a
deliberate attempt to escape the content directory. Only the loader knows
where the document was and what it may reach.

So audio goes through the same security-hardened ``Resolver`` every other
external reference does — same-origin http(s) only, or confined to the base
directory, size-capped — and the bytes are handed to
``omi_audio.AudioLibrary``, which decodes them and holds the result for the
document. A sound is confined to the document's own origin exactly as a
texture is, and a reference the resolver refuses costs that sound rather than
the scene.

.. rst-class:: technical

``loaders/gltf/scene.py``: ``audio_library`` builds the ``AudioLibrary`` with
``_fetch_audio`` as its fetch callback, and ``_audio_emitters`` resolves a
node's or scene's references through
``omi_audio.model.AudioDocument.emitters_for_node`` / ``emitters_for_scene`` —
the latter enforcing the extension's rule that a scene, which has no
transform, carries only ``global`` emitters. The model reader is
``omi_audio.model.from_gltf``, and ``omi_audio.model.to_gltf`` writes it back
out, omitting every field still at its default.

.. _vrml:

The VRML97 ``Sound`` node
-------------------------

VRML97's own ``Sound`` and ``AudioClip`` play, with the fields pyvrml97
declares for them:

.. code-block:: python

   Sound(
       source=AudioClip(url=['ambience.wav'], loop=True, pitch=1.0),
       location=(0, 1, 0), direction=(0, 0, -1),
       minFront=2.0, minBack=2.0, maxFront=40.0, maxBack=10.0,
       intensity=0.8, priority=0.2, spatialize=True,
   )

Of the time-dependent behaviour it honours what can be seen from outside:
``startTime`` and ``stopTime`` bound when the clip sounds, ``loop`` repeats
it, ``pitch`` sets the playback rate, and ``isActive`` and
``duration_changed`` are sent. Fractional seeking into a clip that started
before the scene did is not implemented; a clip whose ``startTime`` has passed
begins at its start. ``spatialize=FALSE`` still fades with distance but sits
in the middle of the stereo field, which is what the specification says.

.. rst-class:: technical

The geometry is ``omi_audio.spatial.ellipsoid_gain_at(location, direction,
listener_position, ...)``, which takes three world-space vectors and works the
distance and the angle out for itself. All the node does is put its
``location`` and ``direction`` into world space, multiply by ``intensity``,
and pan — a sound with a zero ``direction`` has no front to tell from its
back, so its ``front`` distances reach in every direction.

.. _api:

Driving it directly
-------------------

A game does not want to put a node in the scene for every gunshot. The engine
is available directly, and it is the same engine the nodes use:

.. code-block:: python

   from OpenGLContext.audio import scene as audioscene

   engine = audioscene.engine_for(self)          # None if audio is switched off
   if engine is not None:
       engine.play('weapon/rocket_fire.wav',
                   emitter=emitter_record,        # an omi_audio.model.AudioEmitter
                   position=muzzle_world_position,
                   gain=1.0, priority=0.8)

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Call
     - Does
   * - ``engine.play(source, ...)``
     - Starts a clip or a named file; returns a ``VoiceHandle`` or None. None is an
       ordinary outcome, not an error.
   * - ``engine.aim(handle, emitter, position, forward)``
     - Re-points a playing sound. Accepts a None handle.
   * - ``engine.gains_for(emitter, position, forward, gain)``
     - The two numbers, without playing anything — useful for tests and for deciding
       whether a sound is worth starting at all.
   * - ``engine.listen(view_platform)``
     - Moves the listener. The render pass already does this each frame.
   * - ``engine.master_gain``
     - The application's mix level. Set it once; it is not the player's volume and is
       never overwritten by one.
   * - ``engine.volume``
     - The player's volume, refreshed each frame from ``definition.audio.volume``.
       Write the field, not this.
   * - ``engine.muffle``
     - 0 clear to 1 underwater, on the whole mix.
   * - ``audioscene.describe(context)``
     - A dict for a debug overlay: device, voice count, volume, muffle.

.. _audio-testing:

Testing sound without a sound card
----------------------------------

Nearly all of this is arithmetic over arrays, and an array can be asserted
about. Build an engine on a ``NullDevice`` and read the mix:

.. code-block:: python

   from omi_audio.device import NullDevice
   from omi_audio.engine import AudioEngine
   from omi_audio import synth

   engine = AudioEngine(device=NullDevice(sample_rate=8000), voices=8)
   engine.mixer.play(synth.tone(440.0, 1.0, sample_rate=8000), pan=1.0)
   block = engine.mixer.mix(64)          # (64, 2) float32
   assert block[:, 0].max() < 1e-9       # nothing in the left ear
   assert block[:, 1].max() > 0.1        # and plenty in the right

``omi_audio``'s own suite covers the curves at known distances and angles,
panning either side of the listener, voice stealing under pressure, the ramp,
the muffle's frequency response, the glTF round-trip, both silent paths, and
the level in dBFS at the device boundary for a source at a stated position.
One test asserts that mixing a full pool for twenty blocks allocates nothing
measurable, which is the property the whole design rests on. OpenGLContext's
own ``tests/unit/test_audio_*.py`` cover what it adds: the nodes, the
per-context engine, the pass wiring and the glTF import.

.. _audio-demos:

Demo
----

``tests/audio_spatial.py`` puts three sounds in a room and lets you walk
around them: one orbits you (panning), one sits far off (distance), and one is
a cone you can only hear from in front of. ``m`` muffles everything; the space
bar fires a one-shot. Every clip is synthesised, so the demo ships no assets,
and it runs identically — silently — on a machine with no sound.

.. code-block:: bash

   python tests/audio_spatial.py
