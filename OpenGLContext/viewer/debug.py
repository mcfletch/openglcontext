"""What the developer overlay says about the scene being viewed.

Every context already reports its frame rate, what the renderer is doing and
where its camera is (:mod:`OpenGLContext.ui.debugoverlay`).  A viewer can answer
the questions a *viewer* raises, which those cannot: which adapter read this
source, how big the thing turned out to be -- the number every bit of the
framing is derived from -- which of its cameras is bound, and whether the avatar
is walking.

Registered as one more section on the overlay that ``Alt+F`` already raises, so
there is one developer overlay rather than a viewer-shaped second one.
"""
import os
from typing import Any, Callable, List, Tuple

__all__ = ['scene_provider', 'install']

#: Where the viewer's section sits among the others: after the frame and the
#: renderer, before the camera -- read as "what is loaded, then how it is drawn".
SCENE_ORDER = 25


def _rows(viewer: Any) -> List[Tuple[str, str]]:
    source = getattr(viewer, 'source', None)
    rows: List[Tuple[str, str]] = [
        ('source', os.path.basename(source) if source else '(nothing loaded)'),
    ]
    adapter = getattr(viewer, 'adapter', None)
    name = getattr(adapter, 'name', '')
    if name:
        rows.append(('format', name))
    if not getattr(viewer, 'sceneLoaded', False):
        return rows

    rows.append(('radius', '%.4g' % float(getattr(viewer, 'radius', 0.0) or 0.0)))

    viewpoints = list(getattr(viewer, 'viewpoints', ()) or ())
    if viewpoints:
        index = int(getattr(viewer, 'cameraIndex', 0) or 0)
        names = list(getattr(viewer, '_cameraNames', ()) or ())
        label = names[index] if index < len(names) else 'camera'
        rows.append(('camera', '%d/%d %s' % (index + 1, len(viewpoints), label)))
    else:
        rows.append(('camera', 'auto-framed'))

    animations = list(getattr(viewer, '_animations', ()) or ())
    if animations:
        index = int(getattr(viewer, '_animationIndex', 0) or 0)
        names = list(getattr(viewer, '_animationNames', ()) or ())
        label = names[index] if index < len(names) else 'animation'
        state = 'playing' if getattr(viewer, '_animationPlaying', False) else 'paused'
        rows.append(('animation', '%d/%d %s (%s)'
                     % (index + 1, len(animations), label, state)))

    rows.append(('moving', 'walk' if getattr(viewer, 'physicsWalking', False)
                 else 'free-fly'))
    return rows


def scene_provider(viewer: Any) -> Callable[[], List[Tuple[str, str]]]:
    """A provider reporting what this viewer has open.

    Every value is read defensively.  The developer overlay is what somebody
    looks at when things are going wrong, and a half-built viewer is exactly
    when that is; a section that raised would take the overlay down with it.
    """
    def rows() -> List[Tuple[str, str]]:
        try:
            return _rows(viewer)
        except Exception as error:              # pragma: no cover - defensive
            return [('scene', 'unreadable: %s' % (error,))]
    return rows


def install(viewer: Any) -> None:
    """Add the viewer's section to this context's developer overlay."""
    viewer.debugOverlay.register('Scene', scene_provider(viewer),
                                 order=SCENE_ORDER)
