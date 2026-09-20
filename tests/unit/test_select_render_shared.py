"""The two legacy colour-pick passes share one helper.

`_flat.FlatPass.selectRender` and `flatcompat.FlatPass.selectRender` were ~90
duplicated lines with *diverging* id encodings (one packs the id <<12 and reads
GL_RGBA, the other reads GL_RGB unshifted). They now both delegate to the shared
`_flat._color_select_render`, passing their own packing/format so behaviour is
preserved while the body lives in one place.
"""
from OpenGL.GL import GL_RGB, GL_RGBA

from OpenGLContext.passes import _flat, flatcompat


def _capture(monkeypatch):
    seen = {}

    def fake(pass_obj, mode, toRender, events, **kw):
        seen.update(kw)
        seen['delegated'] = True
    monkeypatch.setattr(_flat, '_color_select_render', fake)
    return seen


def test_core_flatpass_delegates_with_shifted_rgba(monkeypatch):
    seen = _capture(monkeypatch)
    fp = _flat.FlatPass.__new__(_flat.FlatPass)
    fp.selectRender('mode', 'toRender', 'events')
    assert seen['delegated']
    assert seen['id_shift'] == 12
    assert seen['read_format'] == GL_RGBA
    assert seen['setup_fixed_function'] is False


def test_compat_flatpass_delegates_with_unshifted_rgb(monkeypatch):
    seen = _capture(monkeypatch)
    fp = flatcompat.FlatPass.__new__(flatcompat.FlatPass)
    fp.selectRender('mode', 'toRender', 'events')
    assert seen['delegated']
    assert seen['id_shift'] == 0
    assert seen['read_format'] == GL_RGB
    assert seen['setup_fixed_function'] is True


class TestTheBodyItself:
    """Driving the shared helper, rather than a stand-in for it.

    The cases above assert that both passes delegate, which they do by
    replacing the helper -- so the ninety lines they delegate *to* never run
    under them. These drive the real body over real records in a real context,
    which is what catches a change to the record's shape or to what is drawn
    from it.
    """

    def _scene(self, count=3):
        from OpenGLContext.scenegraph import basenodes
        moves = [basenodes.Transform(
            translation=(index * 3.0 - 3.0, 0, -8.0),
            children=[basenodes.Shape(
                geometry=basenodes.Box(size=(2, 2, 2)),
                appearance=basenodes.Appearance(
                    material=basenodes.Material()))])
            for index in range(count)]
        return basenodes.sceneGraph(children=moves)

    def _pass(self, scene):
        import numpy as np
        from OpenGLContext import frustum
        passing = flatcompat.FlatPass.__new__(flatcompat.FlatPass)
        _flat.SGObserver.__init__(passing, scene, [])
        passing.frustum = frustum.Frustum(planes=np.zeros((0, 4), 'f'))
        return passing

    def _drive(self, gl_context, events):
        """Run the helper over a real render set and report what it drew."""
        import numpy as np
        from OpenGL.GL import GL_RGB
        scene = self._scene()
        passing = self._pass(scene)
        toRender = passing.renderSet(np.identity(4, 'f'))
        drawn = []
        for record in toRender:
            node = record[5]
            node.Render = lambda mode=None, _n=node: drawn.append(_n)

        class Definition:
            debugSelection = False
            pickEnabled = True

        class Context:
            contextDefinition = Definition()

        passing.matrix = np.identity(4, 'f')
        passing.projection = np.identity(4, 'f')
        passing.viewport = (0, 0, 64, 64)
        passing.getViewport = lambda: (0, 0, 64, 64)

        class Mode:
            context = Context()

        _flat._color_select_render(
            passing, Mode(), toRender, events,
            id_shift=0, read_format=GL_RGB,
            setup_fixed_function=True, require_pick_enabled=False)
        return toRender, drawn

    def test_every_record_is_drawn_in_its_own_colour(self, gl_context_compat):
        """One draw per record, of the node the record carries."""
        class Event:
            def getPickPoint(self):
                return (32, 32)

            def setObjectPaths(self, paths):
                self.paths = paths

        toRender, drawn = self._drive(gl_context_compat,
                                      {'a': Event()})

        assert len(toRender) == 3
        assert drawn == [record[5] for record in toRender]

    def test_no_pick_points_draws_nothing(self, gl_context_compat):
        _toRender, drawn = self._drive(gl_context_compat, {})
        assert drawn == []
