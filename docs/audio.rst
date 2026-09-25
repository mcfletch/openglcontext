Sound
=====

.. rst-class:: introduction

OpenGLContext plays sound from places in the scene. A sound under a
``Transform`` is heard from that transform's position: it gets quieter with
distance and pans between the ears as the listener, who is the camera, moves
past it. Sounds come from files, from glTF documents that use the
`KHR_audio_emitter
<https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0/KHR_audio_emitter>`__
extension, from VRML97's ``Sound`` node, or from clips the application
generates. This page covers using sound in an application. How the mixer, the
gain curves and the voice pool work is in :doc:`audio-internals`.

.. _audio-install:

Installing and file formats
---------------------------

.. code-block:: bash

   pip install OpenGLContext[audio]

This installs ``miniaudio``, which opens the sound card and decodes files.
Without it, or on a machine with no sound device, an application runs the same
and is silent; see :ref:`silence`.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Format
     - Suffix
     - Decoded by
   * - WAV
     - ``.wav``
     - ``miniaudio``
   * - MP3
     - ``.mp3``
     - ``miniaudio``
   * - Ogg Vorbis
     - ``.ogg``
     - ``miniaudio``
   * - FLAC
     - ``.flac``
     - ``miniaudio``
   * - Opus
     - ``.opus``, ``.webm``
     - ``libopus``: ``pip install omi_audio[opus]``, or a ``libopus`` already
       on the system (most Linux desktops have one)

Every sound is mixed down to one channel as it is loaded, because its place in
the stereo field comes from its position in the scene. A stereo recording,
music included, plays as mono.

Every decoder in the chain is MIT- or BSD-licensed.

.. _audio-quickstart:

Putting a sound in a scene
--------------------------

Put an ``AudioEmitter`` under a ``Transform``. There is no engine to create,
no device to open and nothing to update each frame:

.. code-block:: python

   from OpenGLContext.scenegraph.basenodes import (
       AudioEmitter, AudioSource, Transform,
   )

   fountain = Transform(translation=(3, 0, -5), children=[
       AudioEmitter(
           gain=0.8,
           refDistance=2.0,
           sources=[AudioSource(url=['sounds/water.ogg'], loop=True)],
       ),
   ])

The render pass finds the emitter each frame, works out where it is from the
transforms above it, and keeps its sound placed relative to the camera. The
first frame with something audible in it opens the sound device; a scene with
no sound opens none.

An ``AudioEmitter`` is where a sound comes from and how it carries. Its
``AudioSource`` children are what it plays; one emitter can play several.

.. list-table:: ``AudioSource``
   :widths: auto
   :header-rows: 1

   * - Field
     - Default
     - Means
   * - ``url``
     - ``[]``
     - Where the sound is, as a list; the first entry that decodes is played.
       See :ref:`audio-urls`.
   * - ``gain``
     - 1.0
     - Linear multiplier on the file's level. 0.5 is half amplitude, not half
       loudness.
   * - ``loop``
     - False
     - Start again at the end.
   * - ``autoplay``
     - True
     - Start as soon as the emitter is in the scene being drawn. Set it False
       for a sound that waits for ``play()``; see :ref:`audio-events`.
   * - ``playbackRate``
     - 1.0
     - Speed and pitch together. 2.0 is an octave up and twice as fast.
   * - ``priority``
     - 0.0
     - 0 to 1. When more sounds want to play than there are voices, the lowest
       priority, then the quietest, is dropped first.
   * - ``repeatInterval``, ``repeatVariance``
     - 0.0
     - Seconds of quiet before a one-shot plays again, and the random spread
       on that wait. See :ref:`audio-repeat`.

.. list-table:: ``AudioEmitter``
   :widths: auto
   :header-rows: 1

   * - Field
     - Default
     - Means
   * - ``type``
     - ``'positional'``
     - ``'global'`` is heard the same everywhere, with no distance or panning:
       music, a narrator, the player's own vehicle.
   * - ``gain``
     - 1.0
     - Linear multiplier on every source it plays.
   * - ``refDistance``
     - 1.0
     - Metres within which the sound is at full level.
   * - ``distanceModel``
     - ``'inverse'``
     - How the level falls beyond ``refDistance``; see below.
   * - ``rolloffFactor``
     - 1.0
     - How quickly it falls. Larger is faster.
   * - ``maxDistance``
     - 0.0
     - Metres at which a ``'linear'`` sound reaches silence. The other two
       models ignore it.
   * - ``shapeType``
     - ``'omnidirectional'``
     - ``'cone'`` aims the sound along the emitter's −Z, like a spotlight.
   * - ``coneInnerAngle``, ``coneOuterAngle``
     - 2π
     - Radians, measured side to side. Full level inside the inner cone,
       ``coneOuterGain`` outside the outer one, a linear blend between.
   * - ``coneOuterGain``
     - 0.0
     - Level behind the cone.

The emitter's fields and names are the ``KHR_audio_emitter`` extension's.
``priority``, ``repeatInterval`` and ``repeatVariance`` are OpenGLContext
additions, since the extension has nowhere to say them.

How far a sound carries
~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - ``distanceModel``
     - Beyond ``refDistance``
     - Use it for
   * - ``'inverse'``
     - Falls off like a real sound in open air; faint but audible at any
       distance
     - Something that should behave like an object in the world
   * - ``'linear'``
     - Falls in a straight line to silence at ``maxDistance``
     - A sound that must be gone beyond a known range. Needs a
       ``maxDistance`` larger than ``refDistance``
   * - ``'exponential'``
     - Like ``'inverse'``, falling faster
     - A sound that should be local without a hard edge

The formulas are in :ref:`curves`.

.. _audio-urls:

Referring to sound files
------------------------

An ``AudioSource`` built in application code opens its ``url`` entries as file
paths, relative to the working directory. An application that ships its
sounds in its package builds the path from the package:

.. code-block:: python

   import os
   SOUNDS = os.path.join(os.path.dirname(__file__), 'sounds')
   AudioSource(url=[os.path.join(SOUNDS, 'door.ogg')])

A source read from a VRML97 or glTF file resolves each entry against that
file, and may reach only what that file may reach: files under its own
directory for a scene loaded from disk, and same-origin URLs for one fetched
over ``http(s)``. An entry outside those limits is skipped with a warning and
the next entry is tried. The rules are the same as for textures; see
:doc:`untrusted`.

List a better format first and a fallback after it, and the first one that
decodes on this machine is played:

.. code-block:: python

   AudioSource(url=['sounds/wind.opus', 'sounds/wind.ogg'])

A file that is missing or will not decode logs one warning and plays as
silence. Nothing raises.

.. _gltf:

Sound in glTF files
-------------------

The :doc:`glTF loader <gltf>` turns a document's ``KHR_audio_emitter`` block
into ``AudioEmitter`` and ``AudioSource`` nodes while it builds the scene:

.. code-block:: python

   from OpenGLContext.loaders.gltf import loader
   scene = loader.load_gltf('room.gltf')   # its emitters are already in there

In the file, the extension has three lists at the top level: ``audio`` (the
data), ``sources`` (how to play it) and ``emitters`` (where it comes from and
how it carries). A node names the emitters it carries, and they are placed at
that node's transform:

.. code-block:: json

   {
     "extensionsUsed": ["KHR_audio_emitter"],
     "extensions": {"KHR_audio_emitter": {
       "audio":    [{"uri": "sounds/fountain.mp3"}],
       "sources":  [{"audio": 0, "loop": true, "autoplay": true, "gain": 0.8}],
       "emitters": [{"type": "positional", "sources": [0],
                     "positional": {"refDistance": 2.0}}]
     }},
     "nodes": [{"name": "Fountain", "translation": [3, 0, -5],
                "extensions": {"KHR_audio_emitter": {"emitters": [0]}}}]
   }

The audio can be a ``uri`` beside the document, an inline ``data:`` URI, or a
``bufferView`` inside the file with a ``mimeType``, as in a ``.glb``. A
``uri`` follows the rules in :ref:`audio-urls`; a reference the loader refuses
silences that one sound and the rest of the scene loads.

A glTF source plays only when it says ``"autoplay": true``, which is the
extension's default of false. Emitters listed on a *scene* rather than a node
must be ``global``, as the extension requires.

.. _audio-gltf-names:

Playing an authored sound from code
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``scene.sounds`` maps each emitter's ``name`` to the ``AudioEmitter`` built for
it, so a sound placed in the file by an artist is started by the application
when something happens:

.. code-block:: python

   scene = loader.load_gltf('car.glb')
   horn = scene.sounds['Horn']     # "emitters": [{"name": "Horn", ...}]
   ...
   def onHorn(self):
       horn.play()

``AudioEmitter.play()`` starts each of its sources from the beginning on the
next frame, as :ref:`AudioSource.play() <audio-events>` does. Leave
``autoplay`` out of such a source in the file, so it waits to be played. The
emitter is also registered under its name for ``scene.getDEF()``, unless a
node already has that name, in which case the emitter gets the next free one
(``Horn_001``). An emitter placed on several nodes is built once per node;
``scene.sounds`` holds the first. An unnamed emitter plays and is not listed.

.. _codecs:

Better formats than MP3
~~~~~~~~~~~~~~~~~~~~~~~

``KHR_audio_emitter`` guarantees only MP3. A source can offer a better
encoding of the same sound through a codec extension that names a second
entry in the ``audio`` list:

.. code-block:: json

   {"audio": 0, "extensions": {"OMI_audio_ogg_vorbis": {"audio": 1}}}

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Extension
     - MIME type
     - Suffix
   * - ``OMI_audio_ogg_vorbis``
     - ``audio/ogg``
     - ``.ogg``
   * - ``OMI_audio_opus``
     - ``audio/opus``, ``audio/webm``
     - ``.opus``, ``.webm``

The better encoding is played where this machine can decode it, and the
source's own MP3 everywhere else. A document with no MP3 fallback lists the
codec extension in ``extensionsRequired``. Both extensions are kept and written
back unchanged when the document is saved.

.. _audio-events:

Playing a sound when something happens
--------------------------------------

There are two ways, depending on whether the sound belongs to something in the
scene.

A sound that belongs to a node - a door, a turret, a machine - is an
``AudioSource`` with ``autoplay=False``, under that node, started with
``play()``:

.. code-block:: python

   creak = AudioSource(url=['sounds/door.ogg'], autoplay=False)
   door = Transform(children=[door_shape, AudioEmitter(sources=[creak])])
   ...
   def onOpen(self):
       creak.play()

``play()`` starts the source from the beginning on the next frame, whether or
not it has played before. A source still sounding starts again from the top,
so one source is one sound at a time, and it keeps following the node as the
node moves.

A sound that overlaps itself, such as rapid fire, or that has no node to
belong to, is played through the context's audio engine:

.. code-block:: python

   from omi_audio import model
   from OpenGLContext.audio import scene as audioscene

   GUNSHOT = model.AudioEmitter(positional=model.PositionalProperties(
       distanceModel='linear', refDistance=6.0, maxDistance=120.0))

   def onFire(self, shooter, muzzle):
       engine = audioscene.engine_for(self)     # None when sound is switched off
       if engine is None:
           return
       if shooter is self.player:
           engine.play('sounds/rifle.wav', gain=0.6, priority=0.6)
       else:
           engine.play('sounds/rifle.wav', emitter=GUNSHOT, position=muzzle,
                       gain=0.6, priority=0.6)

With no ``emitter``, a sound plays centred at full level: the player's own
weapon has no direction to come from. With one, it is placed at ``position``,
in world coordinates, at the moment it starts. The first ``play()`` of a name
decodes the file and later ones reuse it. ``play()`` returns ``None`` when the
file will not decode or every voice is busy with something more important;
both are ordinary outcomes and need no check.

.. _audio-collisions:

Playing a sound when two things collide
---------------------------------------

Subscribe to the bodies that should make a sound, and play one for each blow
the :doc:`physics manager <physics>` delivers. ``approach`` is how fast the two
were closing, in metres per second, which sets how loud the sound is:

.. code-block:: python

   from omi_audio import model, synth

   THUD = synth.impact(0.15, seed=3)            # or a file name
   PLACED = model.AudioEmitter(
       positional=model.PositionalProperties(refDistance=2.0))

   def OnInit(self):
       ...
       self.blows = []
       self.scene.manager.events.subscribe(
           self.blows.append, body=self.crates, above=0.5)

   def OnIdle(self):
       self.scene.advance(dt)                    # delivers this frame's blows
       engine = audioscene.engine_for(self)
       for blow in self.blows:
           if engine is not None:
               engine.play(THUD, emitter=PLACED, position=blow.point,
                           gain=min(1.0, blow.approach / 8.0), priority=0.3)
       self.blows.clear()

``above`` is the closing speed in metres per second below which a contact is
not a blow. Leave it above about 0.1: a body resting on the floor closes on it
slightly on every step. The world records every physics step, so a frame that
ran four steps delivers the blows of all four, and a bounce is heard at any
frame rate. Two watched bodies meeting are delivered once, not once for each.
The subscription's callback runs inside ``advance()``; collecting the blows and
playing them afterwards keeps the audio calls in one place.
:ref:`physics-collisions` describes the subscription and every field of a
blow.

.. _audio-areas:

Background sound for an area
----------------------------

A zone (:doc:`zones`) plays an area's ambience: a global emitter named by a
``ZoneAudio`` is heard only while the camera is inside the zone and fades out
over its ``blend``, and a ``ZoneReverb`` gives everything heard there the
reverb of the place. A glTF file declares both with ``OGLC_zone``; the render
pass sets the gains and the reverb each frame.

.. code-block:: python

   birds = AudioEmitter(type='global', sources=[
       AudioSource(url=['sounds/birds.ogg'], loop=True, autoplay=True)])
   forest = Transform(translation=(0, 10, -40), children=[
       Zone(size=(80, 30, 60), blend=15.0, settings=[ZoneAudio(emitters=[birds])])])

Without zones, each area gets its own looping emitter. For a round area, place it at the
centre with ``distanceModel='linear'``: it is at full level within
``refDistance`` and fades to silence at ``maxDistance``.

.. code-block:: python

   AudioEmitter(distanceModel='linear', refDistance=15.0, maxDistance=25.0,
                sources=[AudioSource(url=['sounds/market.ogg'], loop=True)])

For an area of another shape, make the emitter ``global`` and set its gain
each frame from where the camera is. ``box_gain()`` is 1 inside a box and
falls to 0 over ``margin`` metres outside it:

.. code-block:: python

   from OpenGLContext.audio.areas import box_gain

   cave = AudioSource(url=['sounds/drips.ogg'], loop=True, gain=0.0)
   cave_sound = AudioEmitter(type='global', sources=[cave])  # anywhere in the scene

   def OnIdle(self):
       where = self.getViewPlatform().position
       cave.gain = box_gain(where, centre=(-14, 1, -10),
                            half_size=(5, 4, 5), margin=4.0)

A changed gain reaches the playing sound within a fifteenth of a second and is
ramped, so it does not click. Every looping source holds a voice while it
plays, including at a gain of zero. A silent one is the quietest sound
playing, so it is the first to give its voice up when the pool is full, and it
takes one again when one is free.

.. _audio-synth:

Sounds the game computes
------------------------

``omi_audio.synth`` makes clips from arithmetic: tones, chirps, noise, impacts
and rumbles. They need no files, so they work as placeholders while a game is
being built. ``useClip()`` gives one to an ``AudioSource``:

.. code-block:: python

   from omi_audio import synth

   motor = AudioSource(loop=True, gain=0.0)
   motor.useClip(synth.tone(110.0, 1.0, harmonics=7, fade=0.0))
   car_body.children.append(AudioEmitter(sources=[motor]))

   def OnIdle(self):
       motor.gain = 0.2 + 0.1 * throttle
       motor.playbackRate = 0.5 + speed / 40.0

A sound whose level or pitch follows the simulation - an engine note, wind
rising with speed, a footstep varied each time - sets ``gain`` and
``playbackRate`` every frame. A new ``playbackRate`` applies from the next
frame. A clip given with ``useClip()`` takes precedence over ``url``.

A looped clip must end where it begins. The generators fade each end by
default so a one-shot does not click, and in a loop that fade is heard as a
pulse. For a loop, pass ``fade=0.0`` and give ``tone()`` a whole number of
cycles (110 Hz for 1 second is 110), or use ``rumble()`` with ``decay=0.0``
and ``attack=0.0``.

A generated clip can also be registered by name and played through the engine:

.. code-block:: python

   engine.clips.put('ping', synth.impact(0.4, seed=1))
   engine.play('ping', priority=1.0)

.. _audio-repeat:

Occasional sounds
-----------------

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

   AudioSource(url=['sounds/distant-thunder.wav'],
               repeatInterval=30.0,      # seconds of quiet between plays
               repeatVariance=5.0)       # ±5 s, so two of them drift apart

The interval is timed from the end of the clip, so a long clip and a short one
leave the same gap of quiet. Both fields are ignored while ``loop`` is set.

.. _api:

The audio engine
----------------

Each context has one engine, opened the first time it is asked for.
``audioscene.engine_for(context)`` returns it, or ``None`` when sound is
switched off.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Call
     - Does
   * - ``engine.play(source, emitter=None, position=None, gain=1.0, priority=0.0, loop=False, rate=1.0)``
     - Starts a clip, or a file by name. Returns a ``VoiceHandle``, or
       ``None`` when the clip does not decode or the voice pool refuses it.
   * - ``handle.set_gain(left, right)``, ``handle.set_rate(rate)``, ``handle.stop()``
     - Steer a playing sound. Each does nothing once the sound has ended or
       lost its voice.
   * - ``engine.aim(handle, emitter, position, forward)``
     - Re-places a playing sound at a new position. Accepts a ``None`` handle.
   * - ``engine.gains_for(emitter, position, forward, gain)``
     - Returns the two ear gains a sound would get, without playing it.
   * - ``engine.clips.put(name, clip)``
     - Registers a generated clip under a name.
   * - ``engine.master_gain``
     - The application's overall mix level. See :ref:`audio-settings`.
   * - ``engine.muffle``
     - 0 (clear) to 1 (underwater). See :ref:`audio-muffle`.
   * - ``audioscene.describe(context)``
     - Returns a dict for a debug overlay: device, voice count, volume,
       muffle.

.. _audio-settings:

Volume and settings
-------------------

Audio settings are an ``AudioSettings`` node at ``definition.audio`` on the
``ContextDefinition``, and appear under *Sound* in the F10 :ref:`settings
screen <overlayui-settings>`.

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
     - Off opens no device and starts no thread. Use it for capture runs,
       benchmarks and headless builds.
   * - ``audio.volume``
     - ``OPENGLCONTEXT_AUDIO_VOLUME``
     - 1.0
     - The player's volume. Read every frame, so a settings slider takes
       effect at once.
   * - ``audio.voices``
     - —
     - 32
     - How many sounds can play at once.

The environment variables are listed with the others in :doc:`environment`.

There are two volume controls, and the mixer uses their product. The settings
screen and a volume key write ``context.contextDefinition.audio.volume``, the
player's volume. The application sets ``engine.master_gain`` once, to how loud
the scene is authored to be. Copying one into the other each frame undoes
every change to the one being overwritten.

.. _audio-muffle:

Muffling
--------

``engine.muffle`` runs from 0 (clear) to 1 (underwater) and takes the treble
off everything the player hears. It is a blend, so it can be faded in:

.. code-block:: python

   engine.muffle = min(1.0, depth_below_surface / 0.5)

:doc:`Water <water>` sets it when the camera goes under the surface. A pure
tone has no treble to remove, so it only gets quieter; a sound with harmonics
or noise in it changes character. The filter's response is in
:ref:`mixer-muffle`.

.. _vrml:

The VRML97 ``Sound`` node
-------------------------

:doc:`VRML97's <vrml97>` ``Sound`` and ``AudioClip`` nodes play, with the
fields the specification gives them:

.. code-block:: python

   Sound(
       source=AudioClip(url=['ambience.wav'], loop=True, pitch=1.0),
       location=(0, 1, 0), direction=(0, 0, -1),
       minFront=2.0, minBack=2.0, maxFront=40.0, maxBack=10.0,
       intensity=0.8, priority=0.2, spatialize=True,
   )

Full level inside the ``min`` ellipsoid, silent outside the ``max`` one, with
a fade between. ``startTime`` and ``stopTime`` bound when the clip plays and
``pitch`` sets the playback rate; ``isActive`` and ``duration_changed`` are
sent. A clip whose ``startTime`` has already passed starts from its beginning.
With ``spatialize=FALSE`` the sound still fades with distance but stays
centred. The geometry is in :ref:`audio-ellipsoids`.

.. _silence:

Running without sound
---------------------

When ``miniaudio`` is not installed, or no sound device opens (a container, a
machine with no sound card, a device another program holds exclusively), the
engine logs one warning and the application runs silently. Nothing raises and
nothing refuses to start. Scene nodes are driven the same way, so a game
behaves identically on a continuous-integration runner. Testing a game's sound
without a device is covered in :ref:`audio-testing`.

.. _audio-demos:

Demos
-----

``oglc-audio-demo`` is a yard to walk around with the arrow keys, with one of
each thing on this page in it:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Key
     - What happens
     - Shows
   * - :kbd:`b`
     - Drops five balls; each bounce thuds, louder the harder it lands
     - :ref:`audio-collisions`
   * - :kbd:`g`
     - Strikes the bell
     - ``AudioSource.play()``, :ref:`audio-events`
   * - :kbd:`space`
     - Fires the player's weapon
     - ``engine.play()`` with no place, :ref:`audio-events`
   * - :kbd:`r`
     - Starts or stops a motor whose pitch and level follow its speed
     - :ref:`audio-synth`
   * - walk onto a pad
     - The cave (dark slate, left, with its echo) or the stream (blue tiles,
       right) fades in: each is a zone with a ``ZoneAudio``, and the cave's
       ``ZoneReverb`` gives it the reverb
     - :ref:`audio-areas`
   * - :kbd:`m`
     - Muffles everything
     - :ref:`audio-muffle`
   * - :kbd:`+` / :kbd:`-`
     - The player's volume
     - :ref:`audio-settings`

.. code-block:: bash

   oglc-audio-demo

Its source, ``OpenGLContext/bin/audio_demo.py``, is the working code for each
recipe. The behaviour is in ``AudioYard``, which holds no GL: the window feeds
it the time step and the keys, and the render pass sets the zones' gains and
reverb from where the camera is. ``box_gain``, above, is the same thing for an
application that keeps its areas in code rather than as zones.

:doc:`tests/audio_spatial.py <tutorials/audio_spatial>` is the tutorial for
placement: one sound circles you (panning), one is far away (distance), and
one is a cone you can hear only from in front.

Every clip in both is generated at start-up, so neither ships sound files, and
both run silently on a machine with no sound device.
