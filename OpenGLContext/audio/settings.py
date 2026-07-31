"""What a player gets to decide about sound.

A declared node rather than loose fields on the
:class:`~OpenGLContext.contextdefinition.ContextDefinition`, for the same reason
the movement modes are: sound has more than one knob, they belong together, and
a node gets validation, defaults, serialisation and a generated settings page
from the field system rather than from a parallel layer.

**Whose volume is whose** is the distinction worth understanding here, because
getting it wrong makes a volume control appear not to work:

:attr:`AudioSettings.volume`
    The **player's** volume -- what the slider on the settings screen moves, what
    a volume key should write, and what is saved with the rest of the player's
    settings.  The engine reads it every frame, so moving it is heard at once.
:attr:`~omi_audio.engine.AudioEngine.master_gain`
    The **application's** mix level -- how loud this scene was authored to be.
    An application sets it once and the player never sees it.

The two multiply.  Writing one over the other every frame -- which is the
tempting shortcut -- makes whichever loses last exactly one frame, and the
symptom is a volume key that prints a new number and changes nothing.
"""

from __future__ import annotations

from typing import Any

from vrml import field, node

from OpenGLContext import renderoptions


class AudioSettings(node.Node):
    """Sound, as the player controls it."""

    PROTO = 'AudioSettings'

    #: Whether the scene's sounds are played at all.  Off opens no device and
    #: starts no audio thread, which is what a capture run, a benchmark or a
    #: machine with no sound card wants.  A scene with nothing audible in it
    #: costs nothing either way; see :mod:`OpenGLContext.audio.scene`.
    enabled = field.newField(
        'enabled', 'SFBool', 1,
        lambda: renderoptions.env_flag('OPENGLCONTEXT_AUDIO', True))
    #: The player's volume: 0 silent, 1 as the application intended.  Linear
    #: rather than decibels because that is what ``KHR_audio_emitter`` gains
    #: are, and mixing the two units in one chain is how a volume control ends
    #: up feeling wrong at one end of its travel.
    volume = field.newField(
        'volume', 'SFFloat', 1,
        lambda: renderoptions.env_number('OPENGLCONTEXT_AUDIO_VOLUME', 1.0))
    #: How many sounds may play at once.  Past the pool's size the least
    #: important is dropped, so this is a quality setting as much as a budget:
    #: a busy scene on a small pool loses its quietest sounds first.
    voices = field.newField('voices', 'SFInt32', 1, 32)

    #: How a generated settings page presents these; see
    #: :mod:`OpenGLContext.ui.generate`.
    UI_HINTS = {
        'enabled': {'label': 'Sound'},
        'volume': {'label': 'Volume', 'minimum': 0.0, 'maximum': 1.0,
                   'step': 0.05},
        'voices': {'label': 'Simultaneous sounds', 'minimum': 4,
                   'maximum': 128, 'step': 4},
    }

    #: The order a settings page shows them in.
    FIELDS = ('enabled', 'volume', 'voices')


def settings_for(context: Any) -> AudioSettings:
    """The audio settings of ``context``, defaulted if it declares none.

    A context need not have a definition at all -- a bare test double often does
    not -- and a scene with sound in it should still run when it does not.
    """
    definition = getattr(context, 'contextDefinition', None)
    settings = getattr(definition, 'audio', None)
    if isinstance(settings, AudioSettings):
        return settings
    return AudioSettings()
