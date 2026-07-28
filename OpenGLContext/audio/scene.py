"""Giving a context an ear, and driving the scene's sounds once a frame.

This is the whole of the seam between the render loop and
:mod:`OpenGLContext.audio`.  The render pass already collects every
:class:`~vrml.vrml97.nodetypes.Auditory` node path and already knows where the
camera is; :func:`update` turns those two facts into sound.

**Silence costs nothing.**  A context gets no engine, and therefore opens no
device and starts no audio thread, until a frame is drawn with something audible
in it.  A scene with no sounds -- which is most test scenes and every existing
OpenGLContext demo -- is untouched by any of this.

The engine hangs off the context rather than being a global, because two windows
are two listeners, and it is held weakly so closing a window does not leak a
device.
"""

from __future__ import annotations

import logging
import time
import weakref
from typing import Any, Dict, Optional, Sequence

from OpenGLContext.audio.device import open_device
from OpenGLContext.audio.engine import AudioEngine
from OpenGLContext.audio.settings import settings_for
from OpenGLContext.scenegraph.audio import stop_scene_audio, update_scene_audio

log = logging.getLogger(__name__)

#: Engines by context.  Weak, so a closed window's device goes with it; keyed by
#: the context itself rather than stored on it so a context class needs to know
#: nothing about audio to have some.
_engines: "weakref.WeakKeyDictionary[Any, AudioEngine]" = weakref.WeakKeyDictionary()


def existing_engine(context: Any) -> Optional[AudioEngine]:
    """The engine ``context`` already has, or None.  Never makes one."""
    return _engines.get(context)


def enabled(context: Any) -> bool:
    """Whether this context's settings allow sound at all."""
    return bool(settings_for(context).enabled)


def engine_for(context: Any) -> Optional[AudioEngine]:
    """The engine for ``context``, opened on first ask.

    Returns None where the context's definition has audio switched off, which is
    the one case a caller has to handle -- and handling it is doing nothing.
    """
    if not enabled(context):
        return None
    engine = _engines.get(context)
    if engine is None:
        settings = settings_for(context)
        engine = AudioEngine(device=open_device(), voices=int(settings.voices))
        engine.volume = settings.volume
        _engines[context] = engine
    return engine


def close(context: Any) -> None:
    """Release ``context``'s engine and its device.  Safe if it had none."""
    engine = _engines.pop(context, None)
    if engine is not None:
        engine.close()


def update(context: Any, paths: Sequence[Any], now: Optional[float] = None) -> int:
    """Keep ``context``'s sounds in step with its camera, for one frame.

    ``paths`` are the render pass's collected ``Auditory`` node paths.  An empty
    sequence returns immediately **without opening a device**, which is what
    makes sound free for a scene that has none.

    ``now`` is absolute seconds, because VRML97's ``startTime`` and ``stopTime``
    are absolute; it is taken from the wall clock when not given.

    Returns how many nodes were driven, for a debug overlay.
    """
    if not paths or not enabled(context):
        return 0
    engine = engine_for(context)
    if engine is None:
        return 0
    # The *player's* volume, read every frame: the settings screen writes the
    # field, and a volume slider that only takes effect on the next launch is a
    # volume slider nobody uses.  The application's own `master_gain` is left
    # alone -- writing over it here would make an application's mix level last
    # exactly one frame.
    engine.volume = settings_for(context).volume
    platform = _view_platform(context)
    if platform is not None:
        engine.listen(platform)
    return update_scene_audio(engine, paths,
                              time.time() if now is None else now)


def stop(context: Any, paths: Sequence[Any]) -> None:
    """Silence every sound in a scene that is going away."""
    stop_scene_audio(paths)
    engine = _engines.get(context)
    if engine is not None:
        engine.stop_all()


def _view_platform(context: Any) -> Any:
    """The context's camera, however it exposes one."""
    getter = getattr(context, 'getViewPlatform', None)
    if getter is not None:
        return getter()
    return getattr(context, 'platform', None)


def describe(context: Any) -> Dict[str, Any]:
    """What this context's audio is doing, for a debug overlay."""
    engine = _engines.get(context)
    if engine is None:
        return {'audio': 'off' if not enabled(context) else 'idle'}
    return {
        'audio': 'silent' if engine.silent else '%d Hz' % (engine.sample_rate,),
        'voices': engine.active_voices,
        'volume': round(engine.volume, 2),
        'mix': round(engine.master_gain, 2),
        'muffle': round(engine.muffle, 2),
    }
