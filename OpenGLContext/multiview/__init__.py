"""Several views of one scene: the cameras, the layout, and how a frame draws them.

A context draws one scene through several cameras at once, each into its own
rectangle of the window -- a map beside a three-quarter view, or the top, front
and side views of an editor around a perspective one. An editor is one caller;
a game's rear-view mirror, a security-camera wall and a split-screen player
list are others.

The parts, and the module each is in:

``views``
    :class:`~OpenGLContext.multiview.views.View`,
    :class:`~OpenGLContext.multiview.views.ViewStyle` and
    :class:`~OpenGLContext.multiview.views.ViewLayout` -- what is drawn where,
    and which view an event belongs to. A context draws whatever layout is
    assigned to its ``viewLayout``.
``strategy``
    how a frame reaches every view: one instanced submission with the vertex
    stage routing it, one with a geometry stage, or the scene drawn once per
    view. :class:`~OpenGLContext.multiview.strategy.MultiviewCapabilities`
    decides from the driver.
``cameras``
    :class:`~OpenGLContext.multiview.cameras.OrthoView` -- an orthographic view
    along any axis, which is what an elevation is.
``gestures``
    :class:`~OpenGLContext.multiview.gestures.ViewGestures` -- the pointer
    moving the camera of whichever view it lands in.
``viewset``
    :class:`~OpenGLContext.multiview.viewset.ViewSet` -- several arrangements
    of one set of views, shown by name.
``quad``
    :class:`~OpenGLContext.multiview.quad.QuadView` -- three orthographic views
    around a perspective one, ready to assign.

``docs/multiview.rst`` is the guide.
"""
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform
from OpenGLContext.multiview.gestures import ViewGestures
from OpenGLContext.multiview.grid import Grid
from OpenGLContext.multiview.quad import QuadView
from OpenGLContext.multiview.views import (
    MAX_VIEWS,
    Rect,
    View,
    ViewLayout,
    ViewStyle,
)
from OpenGLContext.multiview.viewset import ViewSet

__all__ = [
    'Grid',
    'MAX_VIEWS',
    'OrthoView',
    'OrthoViewPlatform',
    'QuadView',
    'Rect',
    'View',
    'ViewGestures',
    'ViewLayout',
    'ViewSet',
    'ViewStyle',
]
