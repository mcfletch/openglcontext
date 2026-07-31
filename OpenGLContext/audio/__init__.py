"""Giving an OpenGLContext context an ear.

The sound itself is :mod:`omi_audio`: the ``KHR_audio_emitter`` data model,
every gain curve, the clip cache, the numpy mixer, the device seam and the
engine that ties them together.  None of that knows what a scenegraph is, and
none of it belongs here.

What is here is the two seams between that engine and a context:

=========================  ====================================================
:mod:`~.scene`             One engine per context, opened on the first frame
                           that has something audible in it, and driven once a
                           frame from the camera and the render pass's
                           ``Auditory`` node paths.
:mod:`~.settings`          :class:`~.settings.AudioSettings`, the player's own
                           switch, volume and voice budget, declared as a node
                           on the :class:`~OpenGLContext.contextdefinition.ContextDefinition`
                           so it validates, serialises and generates its own
                           settings page like every other field group.
=========================  ====================================================

The nodes that put a sound *in* a scene are
:mod:`OpenGLContext.scenegraph.audio` -- ``AudioEmitter``, ``AudioSource`` and
VRML97's ``Sound`` -- and the glTF loader reads ``KHR_audio_emitter`` blocks
into them through :mod:`OpenGLContext.loaders.gltf.scene`.

Sound is **optional and never fatal**.  ``miniaudio`` may be absent and a device
may fail to open; both end in one warning and a silent run, so a machine with no
sound card is simply a machine with no sound.

See ``docs/audio.html`` for the data-flow diagrams and a worked example.
"""
