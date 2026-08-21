"""Every HUD widget's default anchor is one the placer knows
(:mod:`OpenGLContext.ui.hudwidgets`).

:func:`~OpenGLContext.ui.hudwidgets.place` falls back to ``center`` for a name
it does not recognise, which is the right thing to do with a name a caller
invented.  It is the wrong thing to happen to a *default*: the widget arrives
in the middle of the screen, over the play area, and nothing says why.

The fallback cannot tell the two cases apart, so the defaults are checked
here instead.
"""
from OpenGLContext.ui import hudwidgets


def _widgets_with_an_anchor():
    for name in sorted(dir(hudwidgets)):
        cls = getattr(hudwidgets, name)
        if not isinstance(cls, type) or 'anchor' not in getattr(cls, '__dict__', {}):
            continue
        try:
            yield name, cls().anchor
        except Exception:               # pragma: no cover - needs no instance
            continue


class TestTheDefaultsAreRecognised:
    def test_every_default_anchor_is_in_ANCHORS(self):
        wrong = {name: anchor for name, anchor in _widgets_with_an_anchor()
                 if anchor not in hudwidgets.ANCHORS}
        assert not wrong, (
            'these default to an anchor place() does not know, so they land '
            'in the middle of the screen: %s' % wrong)

    def test_the_lamp_row_sits_across_the_top(self):
        """A start rig, a life count and a lap tally all belong out of the way."""
        assert hudwidgets.LampRow().anchor == 'top'
