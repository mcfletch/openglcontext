"""Tests for the oglc-gltf viewer CLI: pure arg parsing plus headless --capture /
--list-cameras integration (the latter skip if no GL / pygltflib)."""
import os
import subprocess
import sys

import pytest

# Importing the viewer runs its module-level os.environ.setdefault() calls
# (PROFILE/BACKEND/RENDERER=pbr/SHADOWS/...), which configure the renderer when it
# runs as a program. In-process that would leak into unrelated GL *subprocess* tests
# (e.g. handing the shadow suite RENDERER=pbr); snapshot and restore around the import.
_ENV_KEYS = ('OPENGLCONTEXT_PROFILE', 'OPENGLCONTEXT_BACKEND', 'OPENGLCONTEXT_RENDERER',
             'OPENGLCONTEXT_SHADOWS', 'OPENGLCONTEXT_SHADOW_CASCADES',
             'OPENGLCONTEXT_IBL_INTENSITY')
_ENV_SNAPSHOT = {k: os.environ.get(k) for k in _ENV_KEYS}
from OpenGLContext.bin import gltf_view
for _k, _v in _ENV_SNAPSHOT.items():
    if _v is None:
        os.environ.pop(_k, None)
    else:
        os.environ[_k] = _v

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))


class TestParseArgs:
    def test_defaults(self):
        a = gltf_view.parse_args(['model.glb'])
        assert a.source == 'model.glb'
        assert a.shadows is None            # unset -> renderer default (on)
        assert a.lights == 'auto'
        assert a.background is None          # resolved to 'sky' at render time
        assert a.capture is None
        assert a.no_cameras is False and a.turntable is False

    def test_shadows_toggle(self):
        assert gltf_view.parse_args(['m.glb', '--no-shadows']).shadows is False
        assert gltf_view.parse_args(['m.glb', '--shadows']).shadows is True

    def test_camera_and_capture(self):
        a = gltf_view.parse_args(['m.glb', '--camera', 'aerial', '--capture', 'o.png',
                                  '--capture-delay', '0.75', '--frames', '20'])
        assert a.camera == 'aerial'
        assert a.capture == 'o.png'
        assert a.capture_delay == 0.75
        assert a.frames == 20

    def test_size_parsing(self):
        assert gltf_view.parse_args(['m.glb', '--size', '1280x720']).size == (1280, 720)

    def test_bad_size_rejected(self):
        with pytest.raises(SystemExit):
            gltf_view.parse_args(['m.glb', '--size', 'wide'])

    def test_background_passthrough(self):
        assert gltf_view.parse_args(['m.glb', '--background', '0.1,0.2,0.3']).background \
            == '0.1,0.2,0.3'
        assert gltf_view.parse_args(['m.glb', '--background', 'none']).background == 'none'


_RENDER_ENV_KEYS = ('OPENGLCONTEXT_SHADOWS', 'OPENGLCONTEXT_IBL_INTENSITY',
                    'OPENGLCONTEXT_DISABLE_FPS_DISPLAY', 'OPENGLCONTEXT_SHADOW_CASCADES')


class TestApplyRenderEnv:
    @pytest.fixture(autouse=True)
    def _isolate_env(self):
        # apply_render_env writes os.environ directly (as it must for main()), which
        # monkeypatch would not undo -- snapshot and restore so these vars don't leak
        # into later GL subprocess tests (e.g. turning shadows off scene-wide).
        saved = {k: os.environ.get(k) for k in _RENDER_ENV_KEYS}
        yield
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _clean_env(self, monkeypatch):
        for k in _RENDER_ENV_KEYS:
            monkeypatch.delenv(k, raising=False)

    def test_shadows_off_sets_env(self, monkeypatch):
        self._clean_env(monkeypatch)
        gltf_view.apply_render_env(gltf_view.parse_args(['m.glb', '--no-shadows']))
        assert os.environ['OPENGLCONTEXT_SHADOWS'] == '0'

    def test_unset_shadows_leaves_env(self, monkeypatch):
        self._clean_env(monkeypatch)
        gltf_view.apply_render_env(gltf_view.parse_args(['m.glb']))
        assert 'OPENGLCONTEXT_SHADOWS' not in os.environ

    def test_ibl_and_capture_env(self, monkeypatch):
        self._clean_env(monkeypatch)
        gltf_view.apply_render_env(gltf_view.parse_args(
            ['m.glb', '--ibl-intensity', '0.6', '--capture', 'o.png']))
        assert os.environ['OPENGLCONTEXT_IBL_INTENSITY'] == '0.6'
        assert os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] == '1'

    def test_interactive_leaves_cascades_adaptive(self, monkeypatch):
        # Interactive use must NOT pin the cascade count: the fps-adaptive
        # controller sheds cascades under load (the dominant shadow-pass cost),
        # which a fixed pin would defeat.
        self._clean_env(monkeypatch)
        gltf_view.apply_render_env(gltf_view.parse_args(['m.glb']))
        assert 'OPENGLCONTEXT_SHADOW_CASCADES' not in os.environ

    def test_capture_pins_cascades_for_determinism(self, monkeypatch):
        # A --capture render must be reproducible, so it pins the cascade count.
        self._clean_env(monkeypatch)
        gltf_view.apply_render_env(gltf_view.parse_args(['m.glb', '--capture', 'o.png']))
        assert os.environ['OPENGLCONTEXT_SHADOW_CASCADES'] == '3'

    def test_capture_respects_explicit_cascade_override(self, monkeypatch):
        self._clean_env(monkeypatch)
        monkeypatch.setenv('OPENGLCONTEXT_SHADOW_CASCADES', '1')
        gltf_view.apply_render_env(gltf_view.parse_args(['m.glb', '--capture', 'o.png']))
        assert os.environ['OPENGLCONTEXT_SHADOW_CASCADES'] == '1'


# -- headless integration --------------------------------------------------

def _named_camera_glb():
    """A minimal GLB with two named perspective cameras."""
    import numpy as np
    from pygltflib import (
        GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
        Buffer, Material, PbrMetallicRoughness, Camera, Perspective,
    )
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    blob = pos.tobytes()
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0, 1, 2])]
    g.nodes = [
        Node(mesh=0),
        Node(camera=0, name='front', translation=[0.0, 0.0, 5.0]),
        Node(camera=1, name='side', translation=[5.0, 0.0, 0.0],
             rotation=[0.0, 0.7071, 0.0, 0.7071]),
    ]
    g.cameras = [
        Camera(type='perspective', name='front',
               perspective=Perspective(yfov=0.6, znear=0.1, zfar=50.0)),
        Camera(type='perspective', name='side',
               perspective=Perspective(yfov=0.6, znear=0.1, zfar=50.0)),
    ]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness())]
    g.meshes = [Mesh(primitives=[Primitive(attributes=Attributes(POSITION=0), material=0)])]
    g.accessors = [Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                            max=pos.max(0).tolist(), min=pos.min(0).tolist())]
    g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes)]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


@pytest.fixture(scope="module")
def camera_glb(tmp_path_factory):
    pytest.importorskip("pygltflib")
    path = tmp_path_factory.mktemp("gltfview") / "cams.glb"
    path.write_bytes(_named_camera_glb())
    return str(path)


def _run(args, timeout=180):
    return subprocess.run([sys.executable, '-m', 'OpenGLContext.bin.gltf_view'] + args,
                          timeout=timeout, capture_output=True, text=True,
                          cwd=TESTS_DIR + '/..')


def test_list_cameras(camera_glb):
    """--list-cameras prints the glTF camera names (headless, no window)."""
    try:
        result = _run([camera_glb, '--list-cameras'], timeout=60)
    except subprocess.TimeoutExpired:
        pytest.skip("viewer subprocess timed out")
    out = result.stdout
    assert '0: front' in out and '1: side' in out


def test_capture_named_camera(camera_glb, tmp_path):
    """--capture with a named camera writes a non-blank PNG, then exits."""
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    out = str(tmp_path / "shot.png")
    try:
        _run([camera_glb, '--camera', 'front', '--capture', out,
              '--frames', '6', '--capture-delay', '0.2', '--no-shadows'])
    except subprocess.TimeoutExpired:
        pytest.skip("OpenGL context unavailable / capture timed out")
    if not os.path.exists(out):
        pytest.skip("OpenGL context unavailable for capture")
    arr = np.asarray(Image.open(out).convert("RGB"))
    assert arr.any(), "captured frame is all black"


def test_capture_differs_between_cameras(camera_glb, tmp_path):
    """Selecting different named cameras produces different captures."""
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    outs = {}
    for cam in ('front', 'side'):
        p = str(tmp_path / (cam + ".png"))
        try:
            _run([camera_glb, '--camera', cam, '--capture', p,
                  '--frames', '6', '--capture-delay', '0.2', '--no-shadows'])
        except subprocess.TimeoutExpired:
            pytest.skip("OpenGL context unavailable / capture timed out")
        if not os.path.exists(p):
            pytest.skip("OpenGL context unavailable for capture")
        outs[cam] = np.asarray(Image.open(p).convert("RGB")).astype(int)
    assert np.abs(outs['front'] - outs['side']).mean() > 1.0


class TestRemoteSourceRouting:
    """The viewer must load a remote source through the resolver-backed
    ``load_gltf_url`` (which resolves a multi-file ``.gltf``'s external
    ``.bin``/image refs against the document origin), and a local path through
    plain ``load_gltf``. A single-file download of the ``.gltf`` alone loses the
    base URL, so its relative external references cannot resolve."""

    def test_is_url(self):
        assert gltf_view._is_url('http://example.com/m.gltf')
        assert gltf_view._is_url('https://example.com/m.gltf')
        assert not gltf_view._is_url('/local/m.gltf')
        assert not gltf_view._is_url('m.glb')
        assert not gltf_view._is_url(None)

    def test_resolve_source_keeps_url(self):
        url = 'https://example.com/models/BoxTextured/glTF/BoxTextured.gltf'
        assert gltf_view._resolve_source(url) == url

    def test_resolve_source_rejects_missing_file(self):
        with pytest.raises(SystemExit):
            gltf_view._resolve_source('/no/such/model.gltf')

    def test_resolve_source_accepts_existing_file(self, tmp_path):
        p = tmp_path / "m.gltf"
        p.write_text("{}")
        assert gltf_view._resolve_source(str(p)) == str(p)

    @staticmethod
    def _patch_loaders(monkeypatch, calls):
        def url_loader(s, *a, **k):
            calls['url'] = s
            return 'URLSCENE'

        def file_loader(s, *a, **k):
            calls['file'] = s
            return 'FILESCENE'

        monkeypatch.setattr(gltf_view.gltf, 'load_gltf_url', url_loader)
        monkeypatch.setattr(gltf_view.gltf, 'load_gltf', file_loader)

    def test_url_routes_through_load_gltf_url(self, monkeypatch):
        calls = {}
        self._patch_loaders(monkeypatch, calls)
        url = 'https://example.com/m.gltf'
        assert gltf_view._load_source(url) == 'URLSCENE'
        assert calls == {'url': url}          # went to the URL path, not the file path

    def test_local_path_routes_through_load_gltf(self, monkeypatch):
        calls = {}
        self._patch_loaders(monkeypatch, calls)
        assert gltf_view._load_source('/local/m.glb') == 'FILESCENE'
        assert calls == {'file': '/local/m.glb'}


class TestPhysicsDefault:
    """oglc-gltf opens in free-fly, not walk. Engaging the walk/character controller
    on load ground-snaps and falls the avatar, which -- for an isolated, floorless
    model (a lone cube) -- drops the camera straight past the geometry so the viewer
    shows an empty background. Free-fly keeps the freshly framed model in view; the
    user opts into walk with `g` or --physics."""

    def test_defaults_to_free_fly(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_PHYSICS', raising=False)
        assert gltf_view.parse_args(['m.glb']).physics is False

    def test_physics_flag_opts_in(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_PHYSICS', raising=False)
        assert gltf_view.parse_args(['m.glb', '--physics']).physics is True

    def test_env_var_opts_in(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', '1')
        assert gltf_view.parse_args(['m.glb']).physics is True

    def test_no_physics_flag_overrides_env(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', '1')
        assert gltf_view.parse_args(['m.glb', '--no-physics']).physics is False


class TestEyeLookAtCamera:
    """Explicit interior camera: --eye / --look-at bypass auto-framing (Sponza)."""

    def test_parse_vec3(self):
        assert gltf_view._parse_vec3('12,0,2') == (12.0, 0.0, 2.0)
        assert gltf_view._parse_vec3('-14.0,4,-3') == (-14.0, 4.0, -3.0)

    def test_bad_vec3_rejected(self):
        import argparse
        with pytest.raises(argparse.ArgumentTypeError):
            gltf_view._parse_vec3('1,2')

    def test_eye_lookat_args(self):
        a = gltf_view.parse_args(['m.glb', '--eye=12,0,2', '--look-at=-14,4,-3'])
        assert a.eye == (12.0, 0.0, 2.0)
        assert a.look_at == (-14.0, 4.0, -3.0)

    def test_default_no_explicit_camera(self):
        a = gltf_view.parse_args(['m.glb'])
        assert a.eye is None and a.look_at is None

    def test_frame_eye_lookat_sets_platform_pose(self):
        # _frame_eye_lookat aims the platform from eye toward target without GL.
        import numpy as np
        inst = gltf_view.TestContext.__new__(gltf_view.TestContext)

        class _Platform:
            def setFrustum(self, *a): self.frustum = a
            def setPosition(self, p): self.position = p
            quaternion = None
        inst.platform = _Platform()
        inst._frame_eye_lookat((12.0, 0.0, 2.0), (-14.0, 4.0, -3.0), radius=18.0)
        # camera sits at the eye, and a look direction was turned into a rotation
        assert tuple(round(v, 3) for v in inst.platform.position) == (12.0, 0.0, 2.0)
        assert inst.platform.quaternion is not None
