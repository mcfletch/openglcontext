"""Tests for the oglc-gltf viewer CLI: pure arg parsing plus headless --capture /
--list-cameras integration (the latter skip if no GL / pygltflib)."""
import os
import subprocess
import argparse

import pytest
import numpy as np
from pygltflib import (
    GLTF2,
    Scene,
    Node,
    Mesh,
    Primitive,
    Attributes,
    Accessor,
    BufferView,
    Buffer,
    Material,
    PbrMetallicRoughness,
    Camera,
    Perspective,
)

from OpenGLContext.testing.gl_env import import_unconfigured

# The viewer settles the renderer as it is imported (profile, backend, PBR,
# shadows), which is right for a program about to draw. These tests read its
# argument parsing, so the settling is put back rather than handed to every
# test collected after this one.
view = import_unconfigured('OpenGLContext.bin.view')

from OpenGLContext.viewer import source
from tests.unit.viewcapture import PROJECT_ROOT, view_command, view_frame
from OpenGLContext.viewer.options import PlacedLight, ViewerOptions


class TestParseArgs:
    def test_defaults(self):
        a = view.parse_args(['model.glb'])
        assert a.source == 'model.glb'
        assert a.shadows is None            # unset -> renderer default (on)
        assert a.lights == 'auto'
        assert a.background is None          # resolved to 'sky' at render time
        assert a.capture is None
        assert a.no_cameras is False and a.turntable is False

    def test_shadows_toggle(self):
        assert view.parse_args(['m.glb', '--no-shadows']).shadows is False
        assert view.parse_args(['m.glb', '--shadows']).shadows is True

    def test_camera_and_capture(self):
        a = view.parse_args(['m.glb', '--camera', 'aerial', '--capture', 'o.png',
                                  '--capture-delay', '0.75', '--frames', '20'])
        assert a.camera == 'aerial'
        assert a.capture == 'o.png'
        assert a.capture_delay == 0.75
        assert a.frames == 20

    def test_size_parsing(self):
        assert view.parse_args(['m.glb', '--size', '1280x720']).size == (1280, 720)

    def test_bad_size_rejected(self):
        with pytest.raises(SystemExit):
            view.parse_args(['m.glb', '--size', 'wide'])

    def test_background_passthrough(self):
        assert view.parse_args(['m.glb', '--background', '0.1,0.2,0.3']).background \
            == '0.1,0.2,0.3'
        assert view.parse_args(['m.glb', '--background', 'none']).background == 'none'


_RENDER_ENV_KEYS = ('OPENGLCONTEXT_SHADOWS', 'OPENGLCONTEXT_IBL_INTENSITY',
                    'OPENGLCONTEXT_DISABLE_FPS_DISPLAY',
                    'OPENGLCONTEXT_SHADOW_CASCADES',
                    'OPENGLCONTEXT_HIDDEN', 'OPENGLCONTEXT_NO_VSYNC')


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
        view.apply_render_env(view.parse_args(['m.glb', '--no-shadows']))
        assert os.environ['OPENGLCONTEXT_SHADOWS'] == '0'

    def test_unset_shadows_leaves_env(self, monkeypatch):
        self._clean_env(monkeypatch)
        view.apply_render_env(view.parse_args(['m.glb']))
        assert 'OPENGLCONTEXT_SHADOWS' not in os.environ

    def test_ibl_and_capture_env(self, monkeypatch):
        self._clean_env(monkeypatch)
        view.apply_render_env(view.parse_args(
            ['m.glb', '--ibl-intensity', '0.6', '--capture', 'o.png']))
        assert os.environ['OPENGLCONTEXT_IBL_INTENSITY'] == '0.6'
        assert os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] == '1'

    def test_interactive_leaves_cascades_adaptive(self, monkeypatch):
        # Interactive use must NOT pin the cascade count: the fps-adaptive
        # controller sheds cascades under load (the dominant shadow-pass cost),
        # which a fixed pin would defeat.
        self._clean_env(monkeypatch)
        view.apply_render_env(view.parse_args(['m.glb']))
        assert 'OPENGLCONTEXT_SHADOW_CASCADES' not in os.environ

    def test_capture_pins_cascades_for_determinism(self, monkeypatch):
        # A --capture render must be reproducible, so it pins the cascade count.
        self._clean_env(monkeypatch)
        view.apply_render_env(view.parse_args(['m.glb', '--capture', 'o.png']))
        assert os.environ['OPENGLCONTEXT_SHADOW_CASCADES'] == '3'

    def test_capture_respects_explicit_cascade_override(self, monkeypatch):
        self._clean_env(monkeypatch)
        monkeypatch.setenv('OPENGLCONTEXT_SHADOW_CASCADES', '1')
        view.apply_render_env(view.parse_args(['m.glb', '--capture', 'o.png']))
        assert os.environ['OPENGLCONTEXT_SHADOW_CASCADES'] == '1'

    def test_capture_renders_without_a_mapped_window(self, monkeypatch):
        """A capture wants no window and no vsync, and must say so itself.

        A mapped surface serialises on the compositor's frame callback, so
        ``SwapBuffers`` blocks forever with nothing consuming frames -- which is
        what ``--capture`` on a headless or Wayland session is.  Every other
        caller in the tree already set these two by hand before running a
        capture; the viewer now sets them for whoever runs it.
        """
        self._clean_env(monkeypatch)
        view.apply_render_env(view.parse_args(['m.glb', '--capture', 'o.png']))
        assert os.environ['OPENGLCONTEXT_HIDDEN'] == '1'
        assert os.environ['OPENGLCONTEXT_NO_VSYNC'] == '1'

    def test_an_interactive_run_still_gets_a_window(self, monkeypatch):
        self._clean_env(monkeypatch)
        view.apply_render_env(view.parse_args(['m.glb']))
        assert not os.environ.get('OPENGLCONTEXT_HIDDEN')

    def test_a_visible_capture_can_still_be_asked_for(self, monkeypatch):
        """Watching one happen is how you find out why it looks wrong."""
        self._clean_env(monkeypatch)
        monkeypatch.setenv('OPENGLCONTEXT_HIDDEN', '0')
        view.apply_render_env(view.parse_args(['m.glb', '--capture', 'o.png']))
        assert os.environ['OPENGLCONTEXT_HIDDEN'] == '0'


# -- headless integration --------------------------------------------------

def _named_camera_glb():
    """A minimal GLB with two named perspective cameras."""
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


def test_list_cameras(camera_glb):
    """--list-cameras prints the glTF camera names (headless, no window)."""
    result = subprocess.run(view_command([camera_glb, '--list-cameras']), timeout=60,
                            capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert result.returncode == 0, result.stderr
    assert '0: front' in result.stdout and '1: side' in result.stdout


def test_capture_named_camera(camera_glb, tmp_path):
    """--capture with a named camera writes a non-blank PNG, then exits."""
    arr = view_frame([camera_glb, '--camera', 'front', '--frames', '6',
                      '--capture-delay', '0.2', '--no-shadows'],
                     str(tmp_path / "shot.png"))
    assert arr.any(), "captured frame is all black"


def test_capture_differs_between_cameras(camera_glb, tmp_path):
    """Selecting different named cameras produces different captures."""
    outs = {
        cam: view_frame([camera_glb, '--camera', cam, '--frames', '6',
                         '--capture-delay', '0.2', '--no-shadows'],
                        str(tmp_path / (cam + ".png")))
        for cam in ('front', 'side')
    }
    assert np.abs(outs['front'] - outs['side']).mean() > 1.0


class TestRemoteSourceRouting:
    """The viewer must load a remote source through the resolver-backed
    ``load_gltf_url`` (which resolves a multi-file ``.gltf``'s external
    ``.bin``/image refs against the document origin), and a local path through
    plain ``load_gltf``. A single-file download of the ``.gltf`` alone loses the
    base URL, so its relative external references cannot resolve."""

    def test_is_url(self):
        assert source.is_url('http://example.com/m.gltf')
        assert source.is_url('https://example.com/m.gltf')
        assert not source.is_url('/local/m.gltf')
        assert not source.is_url('m.glb')
        assert not source.is_url(None)

    def test_resolve_source_keeps_url(self):
        url = 'https://example.com/models/BoxTextured/glTF/BoxTextured.gltf'
        assert source.resolve_source(url) == url

    def test_resolve_source_answers_none_for_a_missing_file(self):
        assert source.resolve_source('/no/such/model.gltf') is None

    def test_resolve_source_accepts_existing_file(self, tmp_path):
        p = tmp_path / "m.gltf"
        p.write_text("{}")
        assert source.resolve_source(str(p)) == str(p)

    @staticmethod
    def _patch_loaders(monkeypatch, calls):
        def url_loader(s, *_a, **_k):
            calls['url'] = s
            return 'URLSCENE'

        def file_loader(s, *_a, **_k):
            calls['file'] = s
            return 'FILESCENE'

        monkeypatch.setattr(source.gltf, 'load_gltf_url', url_loader)
        monkeypatch.setattr(source.gltf, 'load_gltf', file_loader)

    def test_url_routes_through_load_gltf_url(self, monkeypatch):
        calls = {}
        self._patch_loaders(monkeypatch, calls)
        url = 'https://example.com/m.gltf'
        assert source.load_gltf_source(url) == 'URLSCENE'
        assert calls == {'url': url}          # went to the URL path, not the file path

    def test_local_path_routes_through_load_gltf(self, monkeypatch):
        calls = {}
        self._patch_loaders(monkeypatch, calls)
        assert source.load_gltf_source('/local/m.glb') == 'FILESCENE'
        assert calls == {'file': '/local/m.glb'}


class TestPhysicsDefault:
    """oglc-gltf opens in free-fly, not walk. Engaging the walk/character controller
    on load ground-snaps and falls the avatar, which -- for an isolated, floorless
    model (a lone cube) -- drops the camera straight past the geometry so the viewer
    shows an empty background. Free-fly keeps the freshly framed model in view; the
    user opts into walk with `g` or --physics."""

    def test_defaults_to_free_fly(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_PHYSICS', raising=False)
        assert view.parse_args(['m.glb']).physics is False

    def test_physics_flag_opts_in(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_PHYSICS', raising=False)
        assert view.parse_args(['m.glb', '--physics']).physics is True

    def test_env_var_opts_in(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', '1')
        assert view.parse_args(['m.glb']).physics is True

    def test_no_physics_flag_overrides_env(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', '1')
        assert view.parse_args(['m.glb', '--no-physics']).physics is False


class TestEyeLookAtCamera:
    """Explicit interior camera: --eye / --look-at bypass auto-framing (Sponza)."""

    def test_parse_vec3(self):
        assert view._parse_vec3('12,0,2') == (12.0, 0.0, 2.0)  # noqa: SLF001 the --eye/--look-at value parser on its own
        assert view._parse_vec3('-14.0,4,-3') == (-14.0, 4.0, -3.0)  # noqa: SLF001 the --eye/--look-at value parser on its own

    def test_bad_vec3_rejected(self):
        with pytest.raises(argparse.ArgumentTypeError):
            view._parse_vec3('1,2')  # noqa: SLF001 the --eye/--look-at value parser on its own

    def test_eye_lookat_args(self):
        a = view.parse_args(['m.glb', '--eye=12,0,2', '--look-at=-14,4,-3'])
        assert a.eye == (12.0, 0.0, 2.0)
        assert a.look_at == (-14.0, 4.0, -3.0)

    def test_a_point_light_is_placed_at_its_location(self):
        a = view.parse_args(['m.glb', '--point-light=1,2.5,-3'])
        assert a.point_lights == (PlacedLight((1.0, 2.5, -3.0)),)

    def test_a_point_light_takes_an_intensity_in_candela(self):
        a = view.parse_args(['m.glb', '--point-light=1,2,3,15'])
        assert a.point_lights[0].intensity == 15.0

    def test_point_lights_accumulate_in_order(self):
        a = view.parse_args(['m.glb', '--point-light=1,2,3',
                             '--point-light=-4,5,6,8'])
        assert [light.location for light in a.point_lights] == [
            (1.0, 2.0, 3.0), (-4.0, 5.0, 6.0)]

    def test_no_point_lights_by_default(self):
        assert view.parse_args(['m.glb']).point_lights == ()

    @pytest.mark.parametrize('text', ['1,2', '1,2,3,4,5', '1,2,3,-1', 'a,b,c',
                                      '1,2,nan', '1,2,3,inf'])
    def test_a_malformed_point_light_is_rejected(self, text):
        with pytest.raises(argparse.ArgumentTypeError):
            view._parse_point_light(text)  # noqa: SLF001 the --point-light value parser on its own

    def test_default_no_explicit_camera(self):
        a = view.parse_args(['m.glb'])
        assert a.eye is None and a.look_at is None

    def test_an_explicit_eye_and_target_aim_the_platform(self):
        """--eye/--look-at bypasses auto-framing and points the camera itself."""
        inst = view.TestContext.__new__(view.TestContext)

        class _Platform:
            def setFrustum(self, *a): self.frustum = a
            def setPosition(self, p): self.position = p
            def setOrientation(self, o): self.orientation = o
            quaternion = None
        inst.platform = _Platform()
        inst.options = ViewerOptions(eye=(12.0, 0.0, 2.0),
                                     look_at=(-14.0, 4.0, -3.0))
        inst.frameModel(18.0)
        # camera sits at the eye, and a look direction was turned into a rotation
        assert tuple(round(v, 3) for v in inst.platform.position) == (12.0, 0.0, 2.0)
        assert inst.platform.quaternion is not None


def test_a_registry_that_will_not_read_is_a_usage_error(monkeypatch, capsys):
    """A missing or malformed registry is a message, as an unknown key is."""
    from OpenGLContext.bin import view
    from OpenGLContext.contentpacks import catalog

    def unreadable(_key):
        raise catalog.BadCatalog('packs.json is not a registry')

    monkeypatch.setattr(view, 'open_pack', unreadable)
    with pytest.raises(SystemExit) as stopped:
        view.main(['--pack', 'demo/world'])
    assert stopped.value.code == 2
    assert 'packs.json is not a registry' in capsys.readouterr().err
