"""Overlay UI: panels drawn over a live frame and driven by the pointer.

A game needs a screen it can bring up over the running world -- rendering
options, key bindings, a licence notice, a yes/no question -- and this is the
smallest system that provides one.  It is deliberately not a general widget
toolkit; see ``plans/OVERLAY-UI.md`` for what is in scope and what is not.

The pieces:

* :mod:`~OpenGLContext.ui.geometry` and :mod:`~OpenGLContext.ui.metrics` --
  rectangles and measured text, the arithmetic everything else is laid out from.
* :mod:`~OpenGLContext.ui.widgets` -- labels, buttons, toggles, sliders, text
  fields and key capture, each a scenegraph node so a game can author a screen
  in a file and ``DEF``/``USE`` parts of it.
* :mod:`~OpenGLContext.ui.layout` -- rows, columns and label/control grids.
* :mod:`~OpenGLContext.ui.panel` -- one screen: focus, accelerators, modality.
* :mod:`~OpenGLContext.ui.overlay` -- the stack of panels and the context
  mix-in that feeds it input and draws it.
* :mod:`~OpenGLContext.ui.session` -- editing a node on a copy, so Cancel is
  real at every level of a nested dialog.
* :mod:`~OpenGLContext.ui.skin` -- colours and optional nine-slice artwork.

Typical use is through :class:`~OpenGLContext.ui.overlay.OverlayMixin`, which a
context mixes in to gain ``pushOverlay``/``popOverlay`` and the drawing hook::

    from OpenGLContext.ui import dialogs
    context.pushOverlay(dialogs.confirm(
        'Download the texture pack?', on_answer=self.answered))
"""

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.metrics import FontMetrics

__all__ = ['Rect', 'FontMetrics']
