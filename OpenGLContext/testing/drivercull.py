"""Whether this driver culls a back face with a vertex at clip w = 0, and the switch where it does not.

Mesa's radeonsi driver culls triangles in the vertex stage on GFX10 and later
(NGG culling), and while that culling is active it turns the rasterizer's own
face culling off. Its face test divides by clip w, and a triangle whose
facing comes out infinite or NaN is passed on for the rasterizer to decide.
A vertex exactly on the plane through the eye (clip w = 0) gives that, so a
back-facing triangle with such a vertex is drawn. On Mesa 25.2.8 with a
Radeon 8060S (gfx1151), a solid Cone seen from inside, centred on the eye,
has its apex and base centre on that plane and fills the view; it does the
same under ``glCullFace(GL_FRONT_AND_BACK)``. ``AMD_DEBUG=nonggc`` turns the
vertex-stage culling off, and the rasterizer then culls those faces. A
vertex a hundredth of a unit off the plane is culled either way.
``plans/MESA-NGG-CULLING-W0.md`` is the report written for Mesa, with a
standalone C program that shows it.

The driver starts each shader with this culling off and compiles a culled
variant once a draw passes 128 vertices. Frames drawn before the variant is
ready are culled correctly, and the frames after it are not. A test that
draws a frame or two meets the fault only when the variant is ready that
soon, which beside the rest of a suite is a few runs in every 1,000.

:func:`_probe` draws the Cone from inside in a second window while the first
is open, through the engine's VRML97 pass. On the affected stack that draw
shows the fault on every run. Run in a child process before the session's
first window, it answers whether this machine is affected, so the switch
goes on only where the defect is, and a driver that culls correctly is run
as an application would run it.

The switch is for test sessions. An application on an affected stack sets
``AMD_DEBUG=nonggc`` itself (docs/backends.rst, "Known driver defects").

``OPENGLCONTEXT_NGG_CULLING`` pins the answer: ``on`` leaves the driver's
culling as it is, ``off`` adds ``nonggc`` to ``AMD_DEBUG``, and ``auto`` (the
default) runs the probe. The decision is written back into the variable, so a
child process the run starts (an xdist worker, a script test) inherits it and
does not probe again.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, MutableMapping, Sequence
from typing import Any, Optional

#: Pins whether the driver's vertex-stage culling is switched off.
CULLING_VARIABLE = 'OPENGLCONTEXT_NGG_CULLING'

#: What that variable may say. ``auto`` asks this machine.
CULLINGS = ('auto', 'on', 'off')

#: Mesa's radeonsi debug variable, and the flag in it that turns NGG culling off.
DRIVER_VARIABLE = 'AMD_DEBUG'
NO_NGG_CULLING = 'nonggc'

#: The probe's exit code for "the second window drew faces it culls".
MISCULLS = 1

#: The probe's exit code for "there is no GL here, or not this driver".
CANNOT_TELL = 3

#: Frames the second window draws before its centre is read.
FRAMES = 3


def setting(environ: Optional[MutableMapping[str, str]] = None) -> str:
    """What :data:`CULLING_VARIABLE` says, as one of :data:`CULLINGS`

    Unset and empty both mean ``auto``.  Any other value raises ValueError,
    since a mistyped pin would otherwise reverse what the run asked for.
    """
    if environ is None:
        environ = os.environ
    written = (environ.get(CULLING_VARIABLE, '') or '').strip().lower()
    if not written:
        return 'auto'
    if written not in CULLINGS:
        raise ValueError('%s=%r is not recognised (expected one of %s)'
                         % (CULLING_VARIABLE, written, ', '.join(CULLINGS)))
    return written


def probe_command() -> Sequence[str]:
    """The child process that finds out whether this driver misculls"""
    return (sys.executable, '-m', __name__)


def misculls_from(returncode: int) -> bool:
    """True where a probe ending with `returncode` saw the second window miscull

    Zero is a driver that culled.  :data:`CANNOT_TELL` is a machine with no
    GL, or with a driver this switch does not apply to.  A crash is an answer
    about something else, and leaves the driver alone.
    """
    return returncode == MISCULLS


#: The answer for this process, so the child runs once rather than per caller.
_MISCULLS: Optional[bool] = None


def driver_misculls(run: Optional[Callable[[Sequence[str]], int]] = None) -> bool:
    """True where this machine's driver draws the culled faces of :func:`solid_cone_scene`

    Asked once per process.  ``run`` takes the command and returns its exit
    status, so the reading of that status can be tested without the driver.
    """
    global _MISCULLS
    if _MISCULLS is not None:
        return _MISCULLS
    if run is None:
        run = _run
    try:
        returncode = run(probe_command())
    except OSError:
        _MISCULLS = False
        return _MISCULLS
    _MISCULLS = misculls_from(returncode)
    return _MISCULLS


def _run(command: Sequence[str]) -> int:
    """Run the probe, discarding its output, and return its exit status"""
    try:
        finished = subprocess.run(list(command), capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:     # pragma: no cover - needs a hung driver
        return CANNOT_TELL
    return finished.returncode


def forget() -> None:
    """Ask the machine again next time.  For the cases that test this module."""
    global _MISCULLS
    _MISCULLS = None


def with_flag(value: Optional[str], flag: str = NO_NGG_CULLING) -> str:
    """`value`, a comma-separated ``AMD_DEBUG``, with `flag` among its flags"""
    flags = [part.strip() for part in (value or '').split(',') if part.strip()]
    if flag not in flags:
        flags.append(flag)
    return ','.join(flags)


def culling_choice(asked: str, misculls: Callable[[], bool]) -> str:
    """``'on'`` or ``'off'``, from the setting and the machine

    A pinned setting is returned as it is, and the machine is not asked.
    """
    if asked != 'auto':
        return asked
    return 'off' if misculls() else 'on'


def settle(environ: Optional[MutableMapping[str, str]] = None,
           misculls: Callable[[], bool] = driver_misculls) -> str:
    """Decide this session's culling and apply it to `environ`; ``'on'`` or ``'off'``

    ``'off'`` adds :data:`NO_NGG_CULLING` to :data:`DRIVER_VARIABLE`.  The
    driver reads that variable as it starts, so this runs before the process
    makes its first GL context.  The decision is written to
    :data:`CULLING_VARIABLE` for the child processes the run starts.
    """
    if environ is None:
        environ = os.environ
    decided = culling_choice(setting(environ), misculls)
    if decided == 'off':
        environ[DRIVER_VARIABLE] = with_flag(environ.get(DRIVER_VARIABLE))
    environ[CULLING_VARIABLE] = decided
    return decided


def solid_cone_scene() -> list[Any]:
    """A viewpoint inside a solid, emissive green Cone: a frame that culls is black

    The Cone is centred on the viewpoint, so its apex and the centre of its
    base are at clip w = 0.
    """
    from OpenGLContext.scenegraph.basenodes import (  # noqa: PLC0415 the scenegraph imports GL
        Appearance, Cone, Group, Material, Shape, Viewpoint,
    )
    shape = Shape(geometry=Cone(bottomRadius=3, height=20, solid=True),
                  appearance=Appearance(material=Material(diffuseColor=(0, 0, 0),
                                                          emissiveColor=(0, 1, 0))))
    return [Viewpoint(position=(0, 0, 0)), Group(children=[shape])]


def second_window_green(frames: int = FRAMES) -> tuple[int, str]:
    """(green at the centre, GL_RENDERER) of a second window's frame of :func:`solid_cone_scene`

    The first window stays open while the second draws: the second window's
    frames are the ones the affected driver draws with its culled variant.
    """
    from OpenGL.GL import GL_RENDERER, glGetString  # noqa: PLC0415 imported for the child alone
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 opens windows
    with scene_context(solid_cone_scene(), renderer='vrml97') as first:
        drawn_image(first)
        with scene_context(solid_cone_scene(), renderer='vrml97') as second:
            green = 0
            for _frame in range(frames):
                green = int(drawn_image(second)[48, 48, 1])
            second.setCurrent()
            try:
                renderer = (glGetString(GL_RENDERER) or b'').decode('ascii', 'replace')
            finally:
                second.unsetCurrent()
    return green, renderer


def _probe() -> int:
    """0 where a second window culls, :data:`MISCULLS` where it does not; the child's body

    :data:`CANNOT_TELL` with no GL, or with a driver other than radeonsi.
    """
    try:
        green, renderer = second_window_green()
    except Exception:
        return CANNOT_TELL
    if 'radeonsi' not in renderer:
        return CANNOT_TELL
    return MISCULLS if green >= 128 else 0


if __name__ == '__main__':                # pragma: no cover - the child process
    sys.exit(_probe())
