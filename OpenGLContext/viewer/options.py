"""Everything a viewer can be told to do, in one object.

:class:`ViewerOptions` is what the viewing component reads.  An application
constructs one directly; ``oglc-gltf`` has ``argparse`` fill one in, since
``argparse`` populates any object handed to it as its namespace.  One type
serves both, so a library caller needs no command line and the two can never
drift into disagreeing about a default.

**The defaults live here, and only here.**  Every command-line option is
declared with ``default=argparse.SUPPRESS``, so an option nobody passed leaves
the field alone instead of overwriting it with ``None``.  A default written in
two places is a default that is eventually wrong in one of them.

    from OpenGLContext.viewer import ViewerContext, ViewerOptions

    class MyViewer(ViewerContext):
        options = ViewerOptions(source='model.glb', physics=True)
"""
import os
from dataclasses import dataclass, field, fields
from typing import Any, Optional, Sequence, Tuple

__all__ = ['ViewerOptions']


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == '':
        return default
    return value != '0'


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value == '':
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass
class ViewerOptions:
    """What to show, how to light it, where to stand, and what to do then.

    Mutable: a browser that walks a catalogue rewrites ``yaw`` and
    ``background`` as it moves from model to model.
    """

    #: Scene to open: a filesystem path or an http(s) URL.  None falls back to
    #: the ``GLTF`` environment variable.
    source: Optional[str] = None
    #: Adapter to read it with, by registry name (``gltf``, ``vrml97``, ...).
    #: None chooses one from the source, which is what a named file settles;
    #: this is for a URL that serves a scene from a path with no suffix.
    format: Optional[str] = None

    # -- cameras ----------------------------------------------------------
    #: Initial camera, by the glTF's own name or a 0-based index.
    camera: Optional[str] = None
    #: Ignore the model's cameras; centre it and frame the whole thing.
    no_cameras: bool = False
    #: Print the camera names and exit, without opening a window.
    list_cameras: bool = False

    # -- auto-framing -----------------------------------------------------
    #: Model yaw when auto-framing, in radians -- the three-quarter angle.
    yaw: float = field(default_factory=lambda: _env_float('YAW', -0.62))
    #: Fit factor: below 1 pulls the camera in so a wide, flat model whose
    #: bounding sphere overstates its footprint still fills the frame.
    margin: Optional[float] = None
    #: Camera height as a fraction of the model radius.
    elevation: Optional[float] = None
    #: Downward camera tilt in radians.
    tilt: Optional[float] = None
    #: Explicit camera position in world space.  With :attr:`look_at` this
    #: replaces auto-framing entirely, which is how an interior shot is set up.
    eye: Optional[Tuple[float, ...]] = None
    #: Explicit camera target in world space.
    look_at: Optional[Tuple[float, ...]] = None

    # -- lighting and environment -----------------------------------------
    #: ``auto`` adds a default rig only to a model with no lights of its own;
    #: ``on`` always adds it, ``off`` never does.
    lights: str = 'auto'
    #: Force shadows on or off; None leaves the renderer's own default.
    shadows: Optional[bool] = None
    #: Scale on the analytic-sky ambient contribution.
    ibl_intensity: Optional[float] = None
    #: Image-based environment: a cubemap face prefix, an equirectangular
    #: Radiance ``.hdr``, or a bundled HDRI name.  Reflected by metals and
    #: drawn as the skybox.
    environment: Optional[str] = None
    #: ``sky``, ``none``, ``cube``, ``hdr`` or an ``R,G,B`` triple.  None picks
    #: the loaded environment if there is one and the gradient sky otherwise.
    background: Optional[str] = None

    # -- animation --------------------------------------------------------
    #: Play embedded animations.
    animate: bool = True
    #: Which animation, by name or 0-based index; None plays the first.
    animation: Optional[str] = None
    #: Pin the animation to this time, for a reproducible capture.
    anim_time: Optional[float] = None
    #: Slowly rotate the model.
    turntable: bool = False
    #: Never rotate the model, so a capture lines up with a reference image.
    no_rotate: bool = False

    # -- moving about ------------------------------------------------------
    #: Walk the model with gravity and collision.  Off by default: an isolated
    #: or floorless model would otherwise drop the avatar out of the shot,
    #: where a framed view was what was wanted.
    physics: bool = field(
        default_factory=lambda: _env_flag('OPENGLCONTEXT_PHYSICS'))

    # -- streaming sources -------------------------------------------------
    #: Screen-space error target in pixels for a streamed dataset: how wrong a
    #: tile may look before a finer one is fetched.  Lower is sharper and
    #: slower.  None leaves the adapter's own default.
    sse: Optional[float] = None
    #: Resident tile memory in MiB.  None leaves the adapter's own default.
    memory: Optional[int] = None
    #: Do not shift an Earth-centred dataset to the origin.  It is shifted by
    #: default because float precision runs out at planetary coordinates.
    no_recenter: bool = False
    #: Where to cache tiles fetched from a URL.  None uses the shared cache.
    cache_dir: Optional[str] = None

    # -- the window and the frame -----------------------------------------
    #: Window size as ``(width, height)``; None leaves the backend's default.
    size: Optional[Tuple[int, int]] = None
    #: Render to this PNG once the scene has settled, then exit.
    capture: Optional[str] = None
    #: Seconds to let the scene settle before capturing.
    capture_delay: float = 0.5
    #: Frames to render before capturing, whatever the delay says.
    frames: int = 10

    def replace(self, **named: Any) -> 'ViewerOptions':
        """A copy with ``named`` changed -- for a caller who wants to keep the
        original, since a viewer edits the options it is given."""
        from dataclasses import replace as _replace
        return _replace(self, **named)


#: Field names, for the parity check that keeps the command line and the
#: dataclass describing the same viewer.
OPTION_NAMES: Sequence[str] = tuple(f.name for f in fields(ViewerOptions))
