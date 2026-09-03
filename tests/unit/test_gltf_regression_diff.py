"""The regression runner's non-GL logic: diffing a new render against a baseline,
deciding what counts as a regression, selecting scenes, blessing, argument/env
resolution, the render-command assembly and the report driver. The actual model
renders spawn the GL viewer in a subprocess and are exercised by the conformance
suite, not here."""
import argparse
import json
import os
import subprocess
import types

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from OpenGLContext.bin import gltf_regression as R  # noqa: E402
from OpenGLContext.loaders.gltf_demos import SceneSpec  # noqa: E402


def _png(path, color, size=(16, 16)):
    Image.new('RGB', size, color).save(path)


class TestCompare:
    def test_identical_images_are_not_a_regression(self, tmp_path):
        a = str(tmp_path / 'a.png')
        b = str(tmp_path / 'b.png')
        _png(a, (120, 130, 140))
        _png(b, (120, 130, 140))
        result, stats = R.compare(a, b, str(tmp_path / 'd.png'), R.DIFF_THRESHOLD)
        assert stats['percent_different'] == 0.0
        assert R.is_regression(result, R.DEFAULT_TOLERANCE) is False

    def test_changed_image_is_a_regression_and_writes_a_diff(self, tmp_path):
        a = str(tmp_path / 'a.png')
        b = str(tmp_path / 'b.png')
        diff = str(tmp_path / 'd.png')
        _png(a, (10, 10, 10))
        _png(b, (200, 200, 200))
        result, stats = R.compare(a, b, diff, R.DIFF_THRESHOLD)
        assert stats['percent_different'] > R.DEFAULT_TOLERANCE
        assert R.is_regression(result, R.DEFAULT_TOLERANCE) is True
        assert os.path.exists(diff)          # a heatmap was saved

    def test_shape_mismatch_is_a_regression(self, tmp_path):
        a = str(tmp_path / 'a.png')
        b = str(tmp_path / 'b.png')
        _png(a, (0, 0, 0), size=(16, 16))
        _png(b, (0, 0, 0), size=(8, 8))
        result, _ = R.compare(a, b, str(tmp_path / 'd.png'), R.DIFF_THRESHOLD)
        assert result.shapes_match is False
        assert R.is_regression(result, R.DEFAULT_TOLERANCE) is True


class TestSelectAndBless:
    def test_only_filters_scenes(self):
        picked = [s.name for s in R.select_scenes(['Duck', 'MetalRoughSpheres'])]
        assert set(picked) == {'Duck', 'MetalRoughSpheres'}

    def test_no_filter_returns_full_roster(self):
        assert len(R.select_scenes(None)) == len(R.select_scenes([])) > 5

    def test_bless_flag_semantics(self):
        # absent -> None (no bless); bare --bless -> [] (bless all); named -> list
        assert R.build_parser().parse_args([]).bless is None
        assert R.build_parser().parse_args(['--bless']).bless == []
        assert R.build_parser().parse_args(['--bless', 'Duck']).bless == ['Duck']

    def test_baseline_root_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv('OPENGLCONTEXT_GLTF_BASELINE', str(tmp_path))
        assert R.default_baseline_root() == str(tmp_path)


class TestReportLocation:
    def test_default_report_lands_under_tests_subdir(self):
        # not inside a virtualenv/site-packages -- a subdirectory of the source
        # tree's tests/ (the report must never write into .venv)
        path = R.default_report_path().replace(os.sep, '/')
        assert '/tests/gltf_regression/' in path
        assert 'site-packages' not in path and '.venv' not in path

    def test_source_root_has_tests_and_package(self):
        root = R._source_root()
        assert root is not None
        assert os.path.isdir(os.path.join(root, 'tests'))
        assert os.path.isfile(os.path.join(root, 'OpenGLContext', '__init__.py'))

    def test_source_root_walks_up_from_a_markerless_cwd(self, tmp_path, monkeypatch):
        # From a directory with no markers the cwd branch walks to the filesystem
        # root and breaks, then the REPO fallback still finds the checkout.
        monkeypatch.chdir(tmp_path)
        assert R._source_root() is not None


class TestParseSize:
    def test_parses_wxh(self):
        assert R._parse_size('1280x720') == (1280, 720)
        assert R._parse_size('900X640') == (900, 640)


class TestEnvironmentResolution:
    def test_studio_keyword_resolves_to_the_hdr_panorama(self):
        spec = SceneSpec('X', background='cube', environment='studio')
        assert R._environment_for(spec) == (R._STUDIO_HDR, '1.0')

    def test_no_environment_keeps_the_procedural_outdoor_cube(self):
        spec = SceneSpec('X', background='cube', environment=None)
        env, ibl = R._environment_for(spec)
        assert ibl == '0.9'                       # the bundled procedural default

    def test_explicit_hdr_name_passes_straight_through(self):
        spec = SceneSpec('X', background='cube', environment='brown_photostudio_02')
        assert R._environment_for(spec) == ('brown_photostudio_02', '1.0')

    def test_procedural_studio_uses_the_dim_neutral_cube(self):
        spec = SceneSpec('X', background='cube', environment='procedural_studio')
        _, ibl = R._environment_for(spec)
        assert ibl == '0.7'


class TestCaptureStats:
    def test_reads_numeric_values_and_none(self):
        stats = R._parse_capture_stats('CAPTURE_STATS load_seconds=1.5 fps=None\n')
        assert stats == {'load_seconds': 1.5, 'fps': None}

    def test_non_numeric_value_is_kept_as_a_string(self):
        stats = R._parse_capture_stats('CAPTURE_STATS gpu=nvidia\n')
        assert stats == {'gpu': 'nvidia'}

    def test_no_stats_line_gives_an_empty_dict(self):
        assert R._parse_capture_stats('nothing here\n') == {}


class TestViewMetadata:
    def _args(self):
        return argparse.Namespace(frames=8, delay=0.5, size=(900, 640))

    def _prov(self):
        return {'git': 'abc123', 'rendered_at': '2026-01-01T00:00:00',
                'gl_renderer': 'TestGPU', 'gl_version': '4.6'}

    def test_auto_framed_scene_records_the_fit_knobs(self):
        spec = SceneSpec('Duck', yaw=-0.6, elevation=0.05, margin=0.9)
        meta = R._view_metadata(spec, None, 'https://x/Duck.glb', self._args(),
                                self._prov(), {'load_seconds': 2.0, 'fps': 30.0})
        assert meta['scene'] == 'Duck' and meta['camera'] is None
        assert meta['load_context'] == 'url' and meta['load_seconds'] == 2.0
        assert meta['framing'] == {'yaw': -0.6, 'elevation': 0.05, 'tilt': 0.0,
                                   'margin': 0.9}
        assert meta['git'] == 'abc123' and meta['gl_renderer'] == 'TestGPU'

    def test_interior_shot_records_eye_and_look_at(self):
        spec = SceneSpec('Room', eye=(1.0, 2.0, 3.0), look_at=(0.0, 0.0, 0.0))
        meta = R._view_metadata(spec, 0, '/local/room.glb', self._args(), self._prov())
        assert meta['load_context'] == 'local'
        assert meta['framing'] == {'eye': [1.0, 2.0, 3.0], 'look_at': [0.0, 0.0, 0.0]}

    def test_cube_scene_records_its_environment(self):
        spec = SceneSpec('Shiny', background='cube', environment='studio')
        meta = R._view_metadata(spec, None, None, self._args(), self._prov())
        assert meta['environment'] == R._STUDIO_HDR and meta['ibl_intensity'] == '1.0'


class TestDefaultOutDir:
    def test_lands_next_to_the_report(self):
        out = R.default_out_dir().replace(os.sep, '/')
        assert out.endswith('/renders')
        assert '/tests/gltf_regression/' in out


class TestRenderView:
    """render_view assembles the viewer command line and reads back its stats; the
    subprocess itself is stubbed so no GL runs here."""

    def _spec(self, **kw):
        return SceneSpec('Duck', yaw=-0.6, elevation=0.05, tilt=0.0, margin=0.9, **kw)

    def _patch(self, monkeypatch, recorder, stdout='CAPTURE_STATS load_seconds=1.0 fps=42\n'):
        def fake_run(cmd, **kw):
            recorder['cmd'] = cmd
            return types.SimpleNamespace(stdout=stdout)
        monkeypatch.setattr(R.subprocess, 'run', fake_run)
        monkeypatch.setattr(R.os.path, 'exists', lambda p: True)

    def test_auto_frame_run_passes_framing_flags_and_reads_stats(self, monkeypatch):
        rec = {}
        self._patch(monkeypatch, rec)
        ok, stats = R.render_view(self._spec(), None, 'm.glb', 'o.png',
                                  (800, 600), 8, 0.5, None)
        assert ok is True and stats == {'load_seconds': 1.0, 'fps': 42.0}
        cmd = rec['cmd']
        assert '--no-cameras' in cmd and '--capture' in cmd and 'o.png' in cmd
        assert '--size' in cmd and '800x600' in cmd

    def test_explicit_eye_and_look_at_are_passed_for_an_interior_shot(self, monkeypatch):
        rec = {}
        self._patch(monkeypatch, rec)
        spec = self._spec(eye=(1.0, 2.0, 3.0), look_at=(0.0, 0.0, 0.0))
        R.render_view(spec, None, 'm.glb', 'o.png', (800, 600), 8, 0.5, None)
        joined = ' '.join(rec['cmd'])
        assert '--eye=' in joined and '--look-at=' in joined

    def test_baked_camera_run_adopts_the_authored_pose(self, monkeypatch):
        rec = {}
        self._patch(monkeypatch, rec)
        R.render_view(self._spec(), 2, 'm.glb', 'o.png', (800, 600), 8, 0.5, None)
        cmd = rec['cmd']
        assert '--camera' in cmd and '2' in cmd and '--no-cameras' not in cmd

    def test_cube_scene_appends_environment_and_ibl(self, monkeypatch):
        rec = {}
        self._patch(monkeypatch, rec)
        R.render_view(self._spec(background='cube', environment='studio'),
                      None, 'm.glb', 'o.png', (800, 600), 8, 0.5, None)
        assert '--environment' in rec['cmd'] and '--ibl-intensity' in rec['cmd']

    def test_animated_scene_pins_the_animation_time(self, monkeypatch):
        rec = {}
        self._patch(monkeypatch, rec)
        R.render_view(self._spec(anim_time=1.0), None, 'm.glb', 'o.png',
                      (800, 600), 8, 0.5, None)
        assert '--anim-time' in rec['cmd']

    def test_timeout_reports_failure(self, monkeypatch):
        def boom(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 120)
        monkeypatch.setattr(R.subprocess, 'run', boom)
        ok, stats = R.render_view(self._spec(), None, 'm.glb', 'o.png',
                                  (800, 600), 8, 0.5, None)
        assert ok is False and stats == {}


class TestResolveModelUrl:
    def test_local_source_that_exists_is_returned_as_a_path(self, monkeypatch, tmp_path):
        p = tmp_path / 'm.glb'
        p.write_bytes(b'x')
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: (str(p), True))
        src, is_url = R.resolve_model_url(SceneSpec('L'))
        assert src == str(p) and is_url is False

    def test_missing_local_source_resolves_to_none(self, monkeypatch):
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: ('/no/such.glb', True))
        src, is_url = R.resolve_model_url(SceneSpec('L'))
        assert src is None and is_url is False

    def test_sample_uses_the_glb_url_when_the_cache_confirms_it(self, monkeypatch):
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: ('Duck', False))
        monkeypatch.setattr(R.gltf, 'sample_model_url', lambda n: 'https://x/%s.glb' % n)
        monkeypatch.setattr(R, '_cached_url_path', lambda url, cache: '/cache/hit')
        src, is_url = R.resolve_model_url(SceneSpec('Duck', source=None))
        assert src == 'https://x/Duck.glb' and is_url is True

    def test_sample_falls_back_to_the_gltf_url_when_no_glb(self, monkeypatch):
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: ('Duck', False))
        monkeypatch.setattr(R.gltf, 'sample_model_url', lambda n: 'https://x/%s.glb' % n)
        def miss(url, cache):
            raise RuntimeError('not cached')
        monkeypatch.setattr(R, '_cached_url_path', miss)
        src, is_url = R.resolve_model_url(SceneSpec('Duck', source=None))
        assert src.endswith('/glTF/Duck.gltf') and is_url is True

    def test_a_scene_named_by_url_is_handed_to_the_viewer_as_that_url(self, monkeypatch):
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: ('https://x/s.glb', False))
        src, is_url = R.resolve_model_url(SceneSpec('S', source='https://x/s.glb'))
        assert src == 'https://x/s.glb' and is_url is True


class TestResolveModel:
    def test_local_source_that_exists(self, monkeypatch, tmp_path):
        p = tmp_path / 'm.glb'
        p.write_bytes(b'x')
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: (str(p), True))
        assert R.resolve_model(SceneSpec('L')) == str(p)

    def test_sample_resolves_via_the_glb_cache(self, monkeypatch):
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: ('Duck', False))
        monkeypatch.setattr(R.gltf, 'sample_model_url', lambda n: 'https://x/%s.glb' % n)
        monkeypatch.setattr(R, '_cached_url_path', lambda url, cache: '/cache/Duck.glb')
        assert R.resolve_model(SceneSpec('Duck', source=None)) == '/cache/Duck.glb'

    def test_sample_mirrors_the_multi_file_gltf_when_the_glb_is_absent(
            self, monkeypatch, tmp_path):
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: ('Duck', False))
        def miss(url, cache):
            raise RuntimeError('no glb')
        monkeypatch.setattr(R, '_cached_url_path', miss)
        monkeypatch.setattr(R, '_MIRROR_DIR', str(tmp_path))
        # the mirrored .gltf has no external buffers/images, so nothing more downloads
        def fake_dl(url, dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'w') as fh:
                json.dump({'buffers': [], 'images': []}, fh)
        monkeypatch.setattr(R, '_dl', fake_dl)
        out = R.resolve_model(SceneSpec('Duck', source=None))
        assert out.endswith(os.path.join('Duck', 'Duck.gltf'))

    def test_a_scene_named_by_url_is_fetched_from_that_url(self, monkeypatch):
        asked = []
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: ('https://x/s.glb', False))
        monkeypatch.setattr(R, '_cached_url_path',
                            lambda url, cache: asked.append(url) or '/cache/s.glb')
        out = R.resolve_model(SceneSpec('S', source='https://x/s.glb'))
        assert out == '/cache/s.glb'
        assert asked == ['https://x/s.glb']

    def test_an_unreachable_url_scene_resolves_to_none_without_mirroring(self, monkeypatch):
        # The Khronos .gltf mirror is for catalogue samples; a URL scene names one
        # file, so a failed fetch is the end of it rather than a second guess.
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: ('https://x/s.glb', False))
        def unreachable(url, cache):
            raise RuntimeError('offline')
        monkeypatch.setattr(R, '_cached_url_path', unreachable)
        monkeypatch.setattr(R, '_dl', lambda url, dst: pytest.fail(
            'mirrored a URL scene as if it were a Khronos sample'))
        assert R.resolve_model(SceneSpec('S', source='https://x/s.glb')) is None


class TestRenderScenes:
    def _args(self, **kw):
        base = dict(bless=None, size=(64, 48), frames=4, delay=0.2)
        base.update(kw)
        return argparse.Namespace(**base)

    def _prov(self):
        return {'git': 'g', 'rendered_at': 't', 'gl_renderer': 'r', 'gl_version': 'v'}

    def test_writes_metadata_and_blesses_the_baseline(self, monkeypatch, tmp_path):
        out_dir = tmp_path / 'out'
        base_dir = tmp_path / 'base'
        monkeypatch.setattr(R, 'resolve_model_url',
                            lambda spec, parth: ('https://x/Duck.glb', True))

        def fake_render(spec, camera, model, out, size, frames, delay, env):
            _png(out, (10, 20, 30))          # leave a render on disk
            return True, {'load_seconds': 1.0}
        monkeypatch.setattr(R, 'render_view', fake_render)
        spec = SceneSpec('Duck', source=None)
        R.render_scenes([spec], str(out_dir), str(base_dir), None,
                        self._args(bless=[]), self._prov())        # bless all
        assert (out_dir / 'Duck.png').exists() and (out_dir / 'Duck.json').exists()
        assert (base_dir / 'Duck.png').exists() and (base_dir / 'Duck.json').exists()
        meta = json.loads((out_dir / 'Duck.json').read_text())
        assert meta['scene'] == 'Duck'

    def test_failed_render_is_reported_and_leaves_no_metadata(
            self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(R, 'resolve_model_url',
                            lambda spec, parth: ('https://x/Duck.glb', True))
        monkeypatch.setattr(R, 'render_view', lambda *a, **k: (False, {}))
        out_dir = tmp_path / 'out'
        R.render_scenes([SceneSpec('Duck', source=None)], str(out_dir),
                        str(tmp_path / 'b'), None, self._args(), self._prov())
        assert 'render failed' in capsys.readouterr().out
        assert not (out_dir / 'Duck.json').exists()

    def test_unavailable_model_is_skipped(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(R, 'resolve_model_url', lambda spec, parth: (None, False))
        called = {}
        monkeypatch.setattr(R, 'render_view',
                            lambda *a, **k: called.setdefault('ran', True))
        R.render_scenes([SceneSpec('Gone', source=None)], str(tmp_path / 'o'),
                        str(tmp_path / 'b'), None, self._args(), self._prov())
        assert 'ran' not in called                      # never tried to render
        assert 'model unavailable' in capsys.readouterr().out


class TestBuildReportAndRun:
    def _stage(self, out_dir, slug, color=(30, 30, 30)):
        os.makedirs(out_dir, exist_ok=True)
        _png(os.path.join(out_dir, slug + '.png'), color)
        with open(os.path.join(out_dir, slug + '.json'), 'w') as fh:
            json.dump({'scene': slug}, fh)

    def test_matching_baseline_is_not_a_regression(self, monkeypatch, tmp_path):
        monkeypatch.setattr(R.gltf, 'cache_reference_screenshot', lambda scene: None)
        out_dir = str(tmp_path / 'out')
        base_dir = str(tmp_path / 'base')
        self._stage(out_dir, 'Duck', (40, 40, 40))
        os.makedirs(base_dir)
        _png(os.path.join(base_dir, 'Duck.png'), (40, 40, 40))       # identical
        report = str(tmp_path / 'report.html')
        n = R.build_report(out_dir, base_dir, report, R.DEFAULT_TOLERANCE,
                           R.DIFF_THRESHOLD)
        assert n == 0 and os.path.exists(report)

    def test_diverging_baseline_counts_as_a_regression(self, monkeypatch, tmp_path):
        monkeypatch.setattr(R.gltf, 'cache_reference_screenshot', lambda scene: None)
        out_dir = str(tmp_path / 'out')
        base_dir = str(tmp_path / 'base')
        self._stage(out_dir, 'Duck', (250, 250, 250))
        os.makedirs(base_dir)
        _png(os.path.join(base_dir, 'Duck.png'), (0, 0, 0))          # wildly different
        report = str(tmp_path / 'report.html')
        n = R.build_report(out_dir, base_dir, report, R.DEFAULT_TOLERANCE,
                           R.DIFF_THRESHOLD)
        assert n == 1

    def test_upstream_screenshot_failure_does_not_break_the_report(
            self, monkeypatch, tmp_path):
        def boom(scene):
            raise RuntimeError('offline')
        monkeypatch.setattr(R.gltf, 'cache_reference_screenshot', boom)
        out_dir = str(tmp_path / 'out')
        base_dir = str(tmp_path / 'base')
        self._stage(out_dir, 'Duck', (40, 40, 40))
        os.makedirs(base_dir)
        _png(os.path.join(base_dir, 'Duck.png'), (40, 40, 40))
        report = str(tmp_path / 'r.html')
        assert R.build_report(out_dir, base_dir, report, R.DEFAULT_TOLERANCE,
                              R.DIFF_THRESHOLD) == 0
        assert os.path.exists(report)

    def test_missing_baseline_is_skipped_not_failed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(R.gltf, 'cache_reference_screenshot', lambda scene: None)
        out_dir = str(tmp_path / 'out')
        self._stage(out_dir, 'Duck')
        report = str(tmp_path / 'report.html')
        n = R.build_report(out_dir, str(tmp_path / 'empty'), report,
                           R.DEFAULT_TOLERANCE, R.DIFF_THRESHOLD)
        assert n == 0                                    # no baseline -> skip, not fail

    def test_stages_external_baseline_and_upstream_into_the_report_bundle(
            self, monkeypatch, tmp_path):
        upstream = tmp_path / 'up.png'
        _png(str(upstream), (5, 6, 7))
        monkeypatch.setattr(R.gltf, 'cache_reference_screenshot',
                            lambda scene: str(upstream))
        out_dir = str(tmp_path / 'out')
        base_dir = str(tmp_path / 'base')
        self._stage(out_dir, 'Duck', (40, 40, 40))
        os.makedirs(base_dir)
        _png(os.path.join(base_dir, 'Duck.png'), (40, 40, 40))
        # report lives in its own dir, so the baseline/upstream are OUTSIDE it and
        # get copied into the render dir to make a self-contained bundle.
        report = str(tmp_path / 'reportdir' / 'r.html')
        R.build_report(out_dir, base_dir, report, R.DEFAULT_TOLERANCE, R.DIFF_THRESHOLD)
        assert os.path.exists(os.path.join(out_dir, 'Duck_baseline.png'))
        assert os.path.exists(os.path.join(out_dir, 'Duck_upstream.png'))

    def test_unreadable_metadata_and_a_missing_render_are_reported_as_errors(
            self, monkeypatch, tmp_path):
        monkeypatch.setattr(R.gltf, 'cache_reference_screenshot', lambda scene: None)
        out_dir = tmp_path / 'out'
        out_dir.mkdir()
        (out_dir / 'Broken.json').write_text('this is not json {')     # unreadable meta
        report = str(tmp_path / 'r.html')                              # + no render png
        n = R.build_report(str(out_dir), str(tmp_path / 'b'), report,
                           R.DEFAULT_TOLERANCE, R.DIFF_THRESHOLD)
        assert n == 0 and os.path.exists(report)                       # error, not regression

    def test_full_run_renders_then_reports(self, monkeypatch, tmp_path):
        monkeypatch.setattr(R.gltf, 'cache_reference_screenshot', lambda scene: None)
        monkeypatch.setattr(R, '_provenance', lambda: {
            'git': 'g', 'rendered_at': 't', 'gl_renderer': 'r', 'gl_version': 'v'})
        out_dir = str(tmp_path / 'out')
        base_dir = str(tmp_path / 'base')

        def fake_render_scenes(scenes, od, br, parth, args, prov):
            self._stage(od, 'Duck', (40, 40, 40))          # produce one render
        monkeypatch.setattr(R, 'render_scenes', fake_render_scenes)
        os.makedirs(base_dir)
        _png(os.path.join(base_dir, 'Duck.png'), (40, 40, 40))
        args = argparse.Namespace(
            baseline_root=base_dir, out_dir=out_dir, parthenon=None,
            report=str(tmp_path / 'r.html'), report_only=False, only=None,
            bless=None, size=(64, 48), frames=4, delay=0.2,
            tolerance=R.DEFAULT_TOLERANCE, diff_threshold=R.DIFF_THRESHOLD)
        assert R.run(args) == 0

    def test_report_only_run_rebuilds_without_rendering(self, monkeypatch, tmp_path):
        monkeypatch.setattr(R.gltf, 'cache_reference_screenshot', lambda scene: None)
        # if rendering were attempted the test would spawn GL; assert it is not.
        monkeypatch.setattr(R, 'render_scenes',
                            lambda *a, **k: pytest.fail('render_scenes ran'))
        out_dir = str(tmp_path / 'out')
        base_dir = str(tmp_path / 'base')
        self._stage(out_dir, 'Duck', (40, 40, 40))
        os.makedirs(base_dir)
        _png(os.path.join(base_dir, 'Duck.png'), (40, 40, 40))
        args = argparse.Namespace(
            baseline_root=base_dir, out_dir=out_dir, parthenon=None,
            report=str(tmp_path / 'r.html'), report_only=True, only=None,
            tolerance=R.DEFAULT_TOLERANCE, diff_threshold=R.DIFF_THRESHOLD)
        assert R.run(args) == 0

    def test_main_report_only_returns_the_regression_count(self, monkeypatch, tmp_path):
        monkeypatch.setattr(R.gltf, 'cache_reference_screenshot', lambda scene: None)
        out_dir = str(tmp_path / 'out')
        base_dir = str(tmp_path / 'base')
        self._stage(out_dir, 'Duck', (255, 255, 255))
        os.makedirs(base_dir)
        _png(os.path.join(base_dir, 'Duck.png'), (0, 0, 0))
        rc = R.main(['--report-only', '--out-dir', out_dir, '--baseline-root', base_dir,
                     '--report', str(tmp_path / 'r.html')])
        assert rc == 1                                   # the divergence is reported


class TestProvenance:
    def test_provenance_stamps_git_time_and_gpu_identity(self):
        prov = R._provenance()
        assert set(prov) >= {'git', 'rendered_at', 'gl_renderer', 'gl_version'}
        assert prov['git']                               # a hash or 'unknown', never empty
        assert 'T' in prov['rendered_at']                # ISO timestamp

    def test_the_gl_identity_is_the_one_the_renders_are_made_in(self):
        """The probe asks for the profile the renders use, not the default one.

        A driver that names the profile in GL_VERSION otherwise stamps every
        baseline with a compatibility context the renders were never made in,
        and a reader comparing two baselines is told the wrong thing about the
        one difference that most changes a frame.
        """
        from OpenGLContext.testing.glcontext import gl_available

        if not gl_available():
            pytest.skip('no GL context can be created in this process')
        version = R._gl_renderer()['gl_version'].lower()
        assert 'compatibility' not in version, version


class TestBaselineDefault:
    def test_falls_back_to_the_reference_images_submodule(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_GLTF_BASELINE', raising=False)
        root = R.default_baseline_root().replace(os.sep, '/')
        assert root.endswith('/tests/reference_images/gltf_baseline')


class TestEnvPrefixFor:
    def test_studio_and_studiobright_resolve_without_error(self):
        # exercised through _environment_for's None path; called directly here for the
        # keyword branches (result is a bundled prefix or None depending on assets).
        assert R._env_prefix_for(SceneSpec('X', environment='studio')) in (None,) or \
            isinstance(R._env_prefix_for(SceneSpec('X', environment='studio')), str)
        assert R._env_prefix_for(SceneSpec('X', environment='studiobright')) in (None,) or \
            isinstance(R._env_prefix_for(SceneSpec('X', environment='studiobright')), str)


class TestFetchHelpers:
    def test_cached_url_path_keys_by_sha1(self, monkeypatch, tmp_path):
        monkeypatch.setattr(R.resolver, '_fetch_url', lambda url, cache: None)
        p = R._cached_url_path('https://x/model.glb', str(tmp_path))
        assert p.startswith(str(tmp_path)) and p.endswith('.glb')

    def test_dl_skips_an_existing_nonempty_file(self, tmp_path):
        dst = tmp_path / 'a.bin'
        dst.write_bytes(b'already here')
        R._dl('https://x/a.bin', str(dst))               # must not re-download
        assert dst.read_bytes() == b'already here'

    def test_dl_downloads_when_absent(self, monkeypatch, tmp_path):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'payload'
        monkeypatch.setattr(R.resolver, 'safe_url', lambda u: u)
        monkeypatch.setattr(R.urllib.request, 'urlopen', lambda url, timeout=0: _Resp())
        dst = tmp_path / 'sub' / 'a.bin'
        R._dl('https://x/a.bin', str(dst))
        assert dst.read_bytes() == b'payload'


class TestResolveModelMirror:
    def test_mirror_downloads_external_buffers_and_images(self, monkeypatch, tmp_path):
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: ('Duck', False))
        def miss(url, cache):
            raise RuntimeError('no glb')
        monkeypatch.setattr(R, '_cached_url_path', miss)
        monkeypatch.setattr(R, '_MIRROR_DIR', str(tmp_path))
        fetched = []

        def fake_dl(url, dst):
            fetched.append(url)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if dst.endswith('.gltf'):
                doc = {'buffers': [{'uri': 'Duck.bin'}],
                       'images': [{'uri': 'tex.png'}, {'uri': 'data:x'}, {}]}
                with open(dst, 'w') as fh:
                    json.dump(doc, fh)
            else:
                with open(dst, 'wb') as fh:
                    fh.write(b'x')
        monkeypatch.setattr(R, '_dl', fake_dl)
        out = R.resolve_model(SceneSpec('Duck', source=None))
        assert out.endswith(os.path.join('Duck', 'Duck.gltf'))
        # the .bin and the non-data image were mirrored; the data: URI was not
        assert any(u.endswith('Duck.bin') for u in fetched)
        assert any(u.endswith('tex.png') for u in fetched)

    def test_mirror_failure_returns_none(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(R.gltf_demos, 'resolve_source',
                            lambda spec, parth=None: ('Duck', False))
        def miss(url, cache):
            raise RuntimeError('no glb')
        monkeypatch.setattr(R, '_cached_url_path', miss)
        monkeypatch.setattr(R, '_MIRROR_DIR', str(tmp_path))
        def boom(url, dst):
            raise RuntimeError('network down')
        monkeypatch.setattr(R, '_dl', boom)
        assert R.resolve_model(SceneSpec('Duck', source=None)) is None
        assert 'resolve FAILED' in capsys.readouterr().out
