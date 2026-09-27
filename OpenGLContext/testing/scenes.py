"""A scenegraph drawn in a context, in the test process, frame by frame.

The test conventions that draw -- a still frame's GL work
(:mod:`~OpenGLContext.testing.stillframe`), a geometry under a mirroring
transform (:mod:`~OpenGLContext.testing.mirrored`), an optional layer that
fails (:mod:`~OpenGLContext.testing.layers`) -- each need a real context
around a real scene, drawn one frame at a time. :func:`scene_context` makes
one::

    from OpenGLContext.testing.scenes import scene_context, drawn_image

    with scene_context([shape], size=(96, 96)) as context:
        context.OnDraw(force=1)                 # a frame
        image = drawn_image(context)            # the next one, as pixels

The context is the interactive context of the backend the run settled on
(:func:`OpenGLContext.testingcontext.getInteractive`), or ``base`` where a
project has its own. Its window is hidden, it does not wait for the display's
refresh, and it draws no frame-rate counter; ``environment`` sets any other
``OPENGLCONTEXT_*`` configuration for the scene's life and puts the old values
back afterwards. The window is released through the context, as an
application's is on exit.
"""
from __future__ import annotations

import contextlib
import gc
import os
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Optional

import numpy as np

__all__ = ['SCENE_ENVIRONMENT', 'drawn_image', 'scene_context']

#: What a scene drawn for a test is configured with unless the test says
#: otherwise: a hidden window, no wait for the refresh, no frame-rate counter
#: over the picture, and image-based lighting that does not adapt to how fast
#: the first frames came.
SCENE_ENVIRONMENT: Mapping[str, str] = {
    'OPENGLCONTEXT_HIDDEN': '1',
    'OPENGLCONTEXT_NO_VSYNC': '1',
    'OPENGLCONTEXT_DISABLE_FPS_DISPLAY': '1',
    'OPENGLCONTEXT_IBL': 'analytic',
}


@contextlib.contextmanager
def _environment(settings: Mapping[str, str]) -> Iterator[None]:
    from OpenGLContext import renderoptions
    before = {name: os.environ.get(name) for name in settings}
    os.environ.update(settings)
    renderoptions.reset_env_cache()
    try:
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        renderoptions.reset_env_cache()


@contextlib.contextmanager
def scene_context(children: Sequence[Any], *, size: tuple[int, int] = (96, 96),
                  environment: Optional[Mapping[str, str]] = None,
                  base: Any = None, **definition: Any) -> Iterator[Any]:
    """A context drawing a scene of ``children``, current until the block ends.

    ``size`` is the window's in pixels; ``definition`` names further
    :class:`~OpenGLContext.contextdefinition.ContextDefinition` fields.
    Raises :class:`~OpenGLContext.testing.glcontext.GLUnavailable` where no
    core-profile context can be made here.
    """
    from OpenGLContext.testing.glcontext import GLUnavailable, profile_unavailable
    settings = dict(SCENE_ENVIRONMENT)
    settings.update(environment or {})
    with _environment(settings):
        refused = profile_unavailable(settings.get('OPENGLCONTEXT_PROFILE', 'core'))
        if refused:
            raise GLUnavailable(refused)
        from OpenGLContext import testingcontext
        from OpenGLContext.contextdefinition import ContextDefinition
        from OpenGLContext.scenegraph import basenodes
        Base = base if base is not None else testingcontext.getInteractive()
        scene = basenodes.sceneGraph(children=list(children))

        class SceneContext(Base):  # type: ignore[misc,valid-type]  # the backend's class, chosen at run time
            contextDefinition = ContextDefinition(size=tuple(size), **definition)

            def OnInit(self) -> None:
                self.sg = scene

        context = SceneContext()
        context.deferRedraw = True
        try:
            yield context
        finally:
            _release(context)


def _release(context: Any) -> None:
    """Let the context's window go, and with it the engine's hold on its pass.

    The window system's release tells the engine's caches the context is
    going, and the render pass cache drops this context's pass.
    """
    context.releaseWindow()
    gc.collect()


def drawn_image(context: Any) -> np.ndarray:
    """Draw a frame and return it as a top-down ``(H, W, 3)`` uint8 array.

    Read as the frame is presented, before the swap, which is where a
    screenshot reads: after the swap the back buffer's contents are
    undefined.
    """
    from OpenGLContext.capture import read_back_buffer
    frames: list[np.ndarray] = []
    presented = type(context).SwapBuffers

    def reading() -> Any:
        frames.append(read_back_buffer()[0])
        return presented(context)

    context.SwapBuffers = reading
    try:
        context.OnDraw(force=1)
    finally:
        del context.SwapBuffers
    if not frames:
        raise AssertionError('the context drew no frame')
    return frames[-1]
