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
