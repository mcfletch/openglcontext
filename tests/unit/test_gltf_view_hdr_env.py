"""gltf_view --environment HDR routing (headless, no GL).

An equirectangular .hdr (path/URL) or a bundled HDRI name routes to
OPENGLCONTEXT_ENV_HDR and pins full IBL; a cubemap face prefix still routes to
OPENGLCONTEXT_ENV_CUBEMAP.
"""
import os

import pytest

from OpenGLContext.bin import gltf_view

_ENV_VARS = ('OPENGLCONTEXT_ENV_HDR', 'OPENGLCONTEXT_ENV_CUBEMAP',
             'OPENGLCONTEXT_IBL')


class _Args:
    def __init__(self, **kw):
        self.environment = kw.get('environment')
        self.background = kw.get('background')
        self.shadows = None
        self.ibl_intensity = None
        self.capture = None


@pytest.fixture(autouse=True)
def _clean_env():
    # apply_render_env writes os.environ directly (that's its job), so snapshot and
    # fully restore -- monkeypatch.delenv would not undo the vars the call *adds*,
    # which then leak into later subprocess tests.
    saved = {k: os.environ.get(k) for k in _ENV_VARS}
    for k in _ENV_VARS:
        os.environ.pop(k, None)
    yield
    for k in _ENV_VARS:
        os.environ.pop(k, None)
        if saved[k] is not None:
            os.environ[k] = saved[k]


def test_is_hdr_environment():
    assert gltf_view._is_hdr_environment('/x/sky.hdr')
    assert gltf_view._is_hdr_environment('https://ex.com/a/sky.hdr?token=1')
    assert gltf_view._is_hdr_environment('foo.pic')
    assert not gltf_view._is_hdr_environment('/env/pimbackground_')
    assert not gltf_view._is_hdr_environment('')


def test_hdr_url_routes_to_env_hdr(monkeypatch):
    url = 'https://dl.polyhaven.org/x/studio_small_03_1k.hdr'
    gltf_view.apply_render_env(_Args(environment=url))
    import os
    assert os.environ['OPENGLCONTEXT_ENV_HDR'] == url
    assert 'OPENGLCONTEXT_ENV_CUBEMAP' not in os.environ
    assert os.environ['OPENGLCONTEXT_IBL'] == 'full'


def test_catalogue_name_routes_to_env_hdr(monkeypatch):
    gltf_view.apply_render_env(_Args(environment='studio_small_03'))
    import os
    from OpenGLContext.loaders import hdri
    assert os.environ['OPENGLCONTEXT_ENV_HDR'] == hdri.CATALOG['studio_small_03'].url
    assert os.environ['OPENGLCONTEXT_IBL'] == 'full'


def test_cubemap_prefix_still_routes_to_cubemap(monkeypatch):
    gltf_view.apply_render_env(_Args(environment='/env/pimbackground_'))
    import os
    assert os.environ['OPENGLCONTEXT_ENV_CUBEMAP'] == '/env/pimbackground_'
    assert 'OPENGLCONTEXT_ENV_HDR' not in os.environ
    assert os.environ['OPENGLCONTEXT_IBL'] == 'full'


def test_background_none_with_hdr_keeps_ibl_on(monkeypatch):
    # A black backdrop but an HDR env must NOT force IBL off (metals still reflect it).
    gltf_view.apply_render_env(_Args(environment='studio_small_03', background='none'))
    import os
    assert os.environ.get('OPENGLCONTEXT_IBL') != 'off'
    assert 'OPENGLCONTEXT_ENV_HDR' in os.environ


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
