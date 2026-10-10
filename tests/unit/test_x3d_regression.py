"""``oglc-x3d-regression``: Web3D's examples rendered and compared with baselines.

A corpus here is a directory laid out as `vrml.x3d.corpus` extracts Web3D's
archives, written into a temporary directory, so nothing is downloaded.
"""
import json
import os

import numpy as np
import pytest
from PIL import Image

from OpenGLContext.bin import x3d_regression as R

DOCUMENT = '''<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Interchange" version="3.3"><Scene>
  %s
  <Shape><Appearance><Material diffuseColor="1 0 0" emissiveColor="1 0 0"/></Appearance>
    <Box/></Shape>
</Scene></X3D>
'''


def write_corpus(root, documents):
    """`documents`: relative path under ConformanceNist -> the Scene's extra content"""
    for relative, extra in documents.items():
        path = os.path.join(root, 'www.web3d.org', 'x3d', 'content', 'examples',
                            'ConformanceNist', relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as stream:
            stream.write(DOCUMENT % extra if extra is not None else '')
    return root


class TestTheRoster:
    def test_each_document_once_by_its_place_in_its_archive(self, tmp_path):
        root = write_corpus(str(tmp_path), {
            'Geometry/Box/default_box.x3d': '', 'Geometry/Box/texture.x3d': '',
            'Lighting/empty.x3d': None,
        })
        found = R.find_scenes(root, ['ConformanceNist'])
        assert [scene.name for scene in found] == [
            'ConformanceNist/Geometry/Box/default_box', 'ConformanceNist/Geometry/Box/texture']
        assert found[0].slug == 'ConformanceNist.Geometry.Box.default_box'
        assert found[0].path.endswith('default_box.x3d')
        # Every archive's folder: a scene may name another archive's files
        assert found[0].root == os.path.join(root, 'www.web3d.org', 'x3d', 'content', 'examples')

    def test_only_narrows_by_part_of_the_name(self, tmp_path):
        root = write_corpus(str(tmp_path), {'Geometry/Box/a.x3d': '', 'Geometry/Cone/b.x3d': ''})
        assert [scene.name for scene in R.find_scenes(root, ['ConformanceNist'], ['Cone'])] == [
            'ConformanceNist/Geometry/Cone/b']

    def test_an_archive_not_fetched_is_none(self, tmp_path):
        assert R.find_scenes(str(tmp_path), ['Savage']) == []


class TestWeb3DsRender:
    def renders(self, tmp_path):
        folder = tmp_path / '_viewpoints'
        folder.mkdir()
        for name in ('Default_viewpoint', 'Top_view', 'TOP'):
            (folder / ('scene.x3d._VP_%s.png' % name)).write_bytes(b'png')
        return str(tmp_path / 'scene.x3d')

    def test_the_bound_viewpoint_by_description(self, tmp_path):
        found = R.upstream_render(self.renders(tmp_path), {'description': 'Top view', 'DEF': 'X'})
        assert found.endswith('_VP_Top_view.png')

    def test_else_by_its_name(self, tmp_path):
        found = R.upstream_render(self.renders(tmp_path), {'description': '', 'DEF': 'TOP'})
        assert found.endswith('_VP_TOP.png')

    def test_a_document_without_one(self, tmp_path):
        assert R.upstream_render(self.renders(tmp_path), None).endswith('_VP_Default_viewpoint.png')

    def test_none_published(self, tmp_path):
        assert R.upstream_render(str(tmp_path / 'other.x3d'), None) is None


class TestTheChildsReport:
    def test_read_from_its_line(self):
        out = 'noise\nX3D_RENDER {"problems": ["error x"], "viewpoint": null}\n'
        assert R.parse_render_report(out) == {'problems': ['error x'], 'viewpoint': None}

    def test_none_without_one(self):
        assert R.parse_render_report('nothing\n') == {}


class TestTheRendersOutcome:
    REPORT = 'X3D_RENDER {"problems": [], "viewpoint": null}\n'

    def test_written_by_a_process_that_exited_cleanly(self):
        assert R.render_outcome(0, self.REPORT, '', True) == (
            True, {'problems': [], 'viewpoint': None, 'returncode': 0})

    def test_a_process_killed_after_writing_its_image_failed(self):
        ok, report = R.render_outcome(-11, self.REPORT, 'Fatal Python error\n', True)
        assert not ok
        assert report['returncode'] == -11
        assert report['error'] == 'killed by SIGSEGV: Fatal Python error'

    def test_a_process_that_exited_with_an_error_failed(self):
        ok, report = R.render_outcome(1, '', 'Traceback\nValueError: no\n', True)
        assert not ok
        assert report['error'] == 'exit status 1: ValueError: no'

    def test_no_image_is_a_failure_whatever_the_status(self):
        ok, report = R.render_outcome(0, '', '', False)
        assert not ok
        assert report['error'] == 'no render'


def test_a_document_is_rendered_as_authored(tmp_path):
    """One real render: a red box seen from X3D's default viewpoint, through a child process"""
    from OpenGLContext.testing.glcontext import gl_available  # noqa: PLC0415 kept with its use
    if not gl_available():
        pytest.skip('no GL context on this machine')
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/red.x3d': ''})
    scene = R.find_scenes(root, ['ConformanceNist'])[0]
    out = str(tmp_path / 'red.png')
    ok, report = R.render_scene(scene, out, size=(96, 64), frames=3)
    assert ok, report
    pixels = np.asarray(Image.open(out).convert('RGB')).astype(int)
    assert pixels.shape == (64, 96, 3)
    assert pixels[32, 48, 0] > 150 and pixels[32, 48, 1] < 80
    assert pixels[2, 2].sum() < 30, 'a document with no Background is black'
    assert report['viewpoint'] is None
    assert report['problems'] == []


@pytest.mark.parametrize('where, url', [
    (('ConformanceNist',), '../../blue.png'),
    (('X3dForWebAuthors', 'Chapter03Grouping'), '../../../X3dForWebAuthors/Chapter03Grouping/blue.png'),
], ids=['its archive', 'another archive'])
def test_a_document_may_name_an_image_above_its_folder(tmp_path, where, url):
    """Web3D's examples share images across folders and across archives: the
    folder of every archive's examples is a content root"""
    from OpenGLContext.testing.glcontext import gl_available  # noqa: PLC0415 kept with its use
    if not gl_available():
        pytest.skip('no GL context on this machine')
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/textured.x3d': ''})
    scene = R.find_scenes(root, ['ConformanceNist'])[0]
    os.makedirs(os.path.join(scene.root, *where), exist_ok=True)
    Image.new('RGB', (4, 4), (0, 0, 255)).save(os.path.join(scene.root, *where, 'blue.png'))
    with open(scene.path, 'w') as stream:
        stream.write(DOCUMENT.replace(
            '<Material diffuseColor="1 0 0" emissiveColor="1 0 0"/>',
            '<ImageTexture url=\'"%s"\'/>' % url) % '')
    out = str(tmp_path / 'blue.png')
    ok, report = R.render_scene(scene, out, size=(96, 64), frames=3)
    assert ok, report
    centre = np.asarray(Image.open(out).convert('RGB')).astype(int)[32, 48]
    assert centre[2] > 150 and centre[0] < 80, centre


def test_a_run_renders_records_blesses_and_reports(monkeypatch, tmp_path):
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/a.x3d': '', 'Geometry/Box/b.x3d': ''})

    def fake_render(scene, out, size, frames, timeout=R.RENDER_TIMEOUT, renderer='pbr', backend='glfw'):
        Image.new('RGB', size, (200, 0, 0)).save(out)
        return True, {'problems': ['warning: something'], 'viewpoint': None}

    monkeypatch.setattr(R, 'render_scene', fake_render)
    monkeypatch.setattr(R.renderregression, 'gl_renderer',
                        lambda *_backend: {'gl_renderer': 'test', 'gl_version': '0'})
    baselines, out_dir = str(tmp_path / 'baselines'), str(tmp_path / 'renders')
    report = str(tmp_path / 'report.html')
    arguments = ['--corpus', root, '--baseline-root', baselines, '--out-dir', out_dir,
                 '--report', report, '--size', '32x24', '--jobs', '2', '--reference', 'web3d']
    assert R.main(arguments) == 0
    assert not os.path.exists(baselines)
    assert R.main(arguments + ['--bless']) == 0
    assert sorted(os.listdir(baselines)) == [
        'ConformanceNist.Geometry.Box.a.json', 'ConformanceNist.Geometry.Box.a.png',
        'ConformanceNist.Geometry.Box.b.json', 'ConformanceNist.Geometry.Box.b.png']
    with open(os.path.join(out_dir, 'ConformanceNist.Geometry.Box.a.json')) as stream:
        record = json.load(stream)
    assert record['scene'] == 'ConformanceNist/Geometry/Box/a'
    assert record['problems'] == ['warning: something']
    assert record['gl_renderer'] == 'test'
    assert os.path.exists(report)

    def different(scene, out, size, frames, timeout=R.RENDER_TIMEOUT, renderer='pbr', backend='glfw'):
        Image.new('RGB', size, (0, 0, 200)).save(out)
        return True, {'problems': [], 'viewpoint': None}

    monkeypatch.setattr(R, 'render_scene', different)
    assert R.main(arguments + ['--only', 'Box/a']) == 1


def test_a_failed_render_fails_the_run(monkeypatch, tmp_path, capsys):
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/a.x3d': ''})

    def crashed(scene, out, size, frames, timeout=R.RENDER_TIMEOUT, renderer='pbr', backend='glfw'):
        return False, {'error': 'killed by SIGSEGV', 'returncode': -11}

    monkeypatch.setattr(R, 'render_scene', crashed)
    monkeypatch.setattr(R.renderregression, 'gl_renderer',
                        lambda *_backend: {'gl_renderer': 'test', 'gl_version': '0'})
    out_dir = str(tmp_path / 'renders')
    assert R.main(['--corpus', root, '--baseline-root', str(tmp_path / 'b'),
                   '--out-dir', out_dir, '--report', str(tmp_path / 'r.html')]) == 1
    with open(os.path.join(out_dir, 'ConformanceNist.Geometry.Box.a.json')) as stream:
        record = json.load(stream)
    assert record['error'] == 'killed by SIGSEGV'
    assert record['returncode'] == -11
    assert '1 render(s) failed' in capsys.readouterr().out


def test_one_documents_failure_leaves_the_others_drawn(monkeypatch, tmp_path):
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/a.x3d': '', 'Geometry/Box/b.x3d': ''})
    monkeypatch.setattr(R, 'render_scene', _fake_render)
    monkeypatch.setattr(R.renderregression, 'gl_renderer',
                        lambda *_backend: {'gl_renderer': 'test', 'gl_version': '0'})
    real = R._reference

    def failing(scene, report, args, rendered):
        if scene.name.endswith('/a'):
            raise OSError('disk full')
        return real(scene, report, args, rendered)
    monkeypatch.setattr(R, '_reference', failing)
    out_dir = str(tmp_path / 'renders')
    assert R.main(['--corpus', root, '--baseline-root', str(tmp_path / 'b'), '--out-dir', out_dir,
                   '--report', str(tmp_path / 'r.html'), '--size', '32x24', '--jobs', '1',
                   '--reference', 'web3d']) == 1
    with open(os.path.join(out_dir, 'ConformanceNist.Geometry.Box.a.json')) as stream:
        assert 'disk full' in json.load(stream)['error']
    assert os.path.exists(os.path.join(out_dir, 'ConformanceNist.Geometry.Box.b.json'))


def test_only_the_documents_drawn_are_counted(monkeypatch, tmp_path):
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/a.x3d': '', 'Geometry/Box/b.x3d': ''})
    monkeypatch.setattr(R, 'render_scene', _fake_render)
    monkeypatch.setattr(R.renderregression, 'gl_renderer',
                        lambda *_backend: {'gl_renderer': 'test', 'gl_version': '0'})
    baselines = str(tmp_path / 'baselines')
    arguments = ['--corpus', root, '--baseline-root', baselines,
                 '--out-dir', str(tmp_path / 'renders'), '--report', str(tmp_path / 'r.html'),
                 '--size', '32x24', '--reference', 'web3d']
    assert R.main(arguments) == 0
    assert R.main(arguments + ['--bless']) == 0
    Image.new('RGB', (32, 24), (0, 0, 200)).save(
        os.path.join(baselines, 'ConformanceNist.Geometry.Box.b.png'))
    assert R.main(arguments + ['--only', 'Box/a']) == 0
    assert R.main(arguments + ['--report-only']) == 1


def test_bless_promotes_what_was_drawn_and_reviewed(monkeypatch, tmp_path, capsys):
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/a.x3d': '', 'Geometry/Box/b.x3d': ''})
    drawn = []

    def counting(scene, out, size, frames, timeout=R.RENDER_TIMEOUT, renderer='pbr', backend='glfw'):
        drawn.append(scene.name)
        return _fake_render(scene, out, size, frames)
    monkeypatch.setattr(R, 'render_scene', counting)
    monkeypatch.setattr(R.renderregression, 'gl_renderer',
                        lambda *_backend: {'gl_renderer': 'test', 'gl_version': '0'})
    baselines, out_dir = str(tmp_path / 'b'), str(tmp_path / 'renders')
    arguments = ['--corpus', root, '--baseline-root', baselines, '--out-dir', out_dir,
                 '--report', str(tmp_path / 'r.html'), '--size', '32x24', '--reference', 'web3d']
    assert R.main(arguments + ['--bless']) == 1
    assert 'Nothing to bless' in capsys.readouterr().out
    R.main(arguments)
    reviewed = Image.open(os.path.join(out_dir, 'ConformanceNist.Geometry.Box.a.png')).tobytes()
    count = len(drawn)
    assert R.main(arguments + ['--bless', 'Box/a']) == 0
    assert len(drawn) == count, 'blessing draws nothing'
    assert sorted(os.listdir(baselines)) == ['ConformanceNist.Geometry.Box.a.json',
                                             'ConformanceNist.Geometry.Box.a.png']
    with Image.open(os.path.join(baselines, 'ConformanceNist.Geometry.Box.a.png')) as image:
        assert image.tobytes() == reviewed


def test_no_corpus_says_how_to_fetch_one(tmp_path, capsys):
    assert R.main(['--corpus', str(tmp_path), '--out-dir', str(tmp_path / 'o'),
                   '--report', str(tmp_path / 'r.html')]) == 2
    assert '--fetch' in capsys.readouterr().out


def _fake_render(scene, out, size, frames, timeout=R.RENDER_TIMEOUT, renderer='pbr', backend='glfw'):
    Image.new('RGB', size, (200, 0, 0)).save(out)
    return True, {'problems': [], 'viewpoint': None}


def _run_with_references(monkeypatch, tmp_path, references):
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/a.x3d': ''})
    monkeypatch.setattr(R, 'render_scene', _fake_render)
    monkeypatch.setattr(R.renderregression, 'gl_renderer',
                        lambda *_backend: {'gl_renderer': 'test', 'gl_version': '0'})
    out_dir = str(tmp_path / 'renders')
    R.main(['--corpus', root, '--baseline-root', str(tmp_path / 'b'), '--out-dir', out_dir,
            '--report', str(tmp_path / 'r.html'), '--size', '32x24',
            '--reference-root', references])
    with open(os.path.join(out_dir, 'ConformanceNist.Geometry.Box.a.json')) as stream:
        return json.load(stream)


def test_x_ites_render_is_the_reference(monkeypatch, tmp_path):
    references = tmp_path / 'x3d_xite'
    references.mkdir()
    Image.new('RGB', (32, 24), (0, 0, 200)).save(references / 'ConformanceNist.Geometry.Box.a.png')
    (references / 'ConformanceNist.Geometry.Box.a.json').write_text(
        json.dumps({'ok': True, 'errors': ['x_ite said something'], 'x_ite': '16.4.3'}))
    record = _run_with_references(monkeypatch, tmp_path, str(references))
    assert record['reference'] == 'X_ITE 16.4.3'
    assert record['upstream'] == str(references / 'ConformanceNist.Geometry.Box.a.png')
    assert record['reference_errors'] == ['x_ite said something']
    assert record['reference_difference'] == pytest.approx(100.0)


def test_without_x_ite_web3ds_render_is_the_reference(monkeypatch, tmp_path):
    record = _run_with_references(monkeypatch, tmp_path, str(tmp_path / 'none'))
    assert record['reference'] == 'Web3D'


def test_the_references_are_in_the_reference_images():
    assert R.default_reference_root().endswith(
        os.path.join('tests', 'reference_images', 'x3d_xite'))


def render_document(tmp_path, scene_xml, **options):
    """`scene_xml` drawn as a corpus document through a child process; its pixels"""
    from OpenGLContext.testing.glcontext import gl_available  # noqa: PLC0415 kept with its use
    if not gl_available():
        pytest.skip('no GL context on this machine')
    root = write_corpus(str(tmp_path / 'corpus'), {'Time/doc.x3d': ''})
    scene = R.find_scenes(root, ['ConformanceNist'])[0]
    with open(scene.path, 'w') as stream:
        stream.write('<X3D profile="Immersive" version="3.3"><Scene>%s</Scene></X3D>' % scene_xml)
    out = str(tmp_path / ('%s.png' % options.get('renderer', 'pbr')))
    ok, report = R.render_scene(scene, out, size=(96, 64), frames=3, **options)
    assert ok, report
    return np.asarray(Image.open(out).convert('RGB')).astype(int)


def test_a_time_sensor_started_at_zero_has_finished_when_the_world_is_drawn(tmp_path):
    """X3D's times are seconds since 1970: a non-looping TimeSensor with
    startTime 0 ended long before the world is loaded, so it never runs"""
    pixels = render_document(tmp_path, '''
      <TimeSensor DEF="Clock" startTime="0" cycleInterval="1"/>
      <ColorInterpolator DEF="Paint" key="0 1" keyValue="0 1 0 0 1 0"/>
      <Shape><Appearance><Material DEF="Skin" diffuseColor="0 0 0" emissiveColor="1 0 0"/>
        </Appearance><Box/></Shape>
      <ROUTE fromNode="Clock" fromField="fraction_changed" toNode="Paint" toField="set_fraction"/>
      <ROUTE fromNode="Paint" fromField="value_changed" toNode="Skin" toField="emissiveColor"/>
    ''')
    centre = pixels[32, 48]
    assert centre[0] > 150 and centre[1] < 80, centre


def stepped_clock_document(when, step):
    """A box whose emissive red is 0 until `when` less half a `step`, 1 from
    `when` and half a `step`, and half way between at `when`: a looping
    TimeSensor of one second, started at 0, read at world time `when`"""
    fraction = when % 1.0
    keys = '0 %r %r 1' % (fraction - step / 2, fraction + step / 2)
    return '''
      <TimeSensor DEF="Clock" startTime="0" cycleInterval="1" loop="true"/>
      <ColorInterpolator DEF="Paint" key="%s" keyValue="0 0 0 0 0 0 1 0 0 1 0 0"/>
      <Shape><Appearance><Material DEF="Skin" diffuseColor="0 0 0" emissiveColor="0 0 0"/>
        </Appearance><Box/></Shape>
      <ROUTE fromNode="Clock" fromField="fraction_changed" toNode="Paint" toField="set_fraction"/>
      <ROUTE fromNode="Paint" fromField="value_changed" toNode="Skin" toField="emissiveColor"/>
    ''' % keys


def test_the_frame_captured_is_drawn_at_the_capture_time(tmp_path):
    """A run of three frames reads the frame drawn at ``capture_time(3)``:
    the box is half red there, black a frame earlier and red a frame later"""
    step = 1.0 / R.CAPTURE_FPS
    assert R.capture_time(3) == R.WORLD_START + 4 * step
    pixels = render_document(tmp_path, stepped_clock_document(R.capture_time(3), step))
    red = pixels[32, 48, 0]
    assert 40 < red < 220, pixels[32, 48]


LIT = '''
  <NavigationInfo headlight="false"/>
  <DirectionalLight direction="-0.3 -0.4 -1" intensity="1"/>
  <Shape><Appearance><PhysicalMaterial baseColor="0.8 0.6 0.2" metallic="1"
    roughness="0.3"/></Appearance><Sphere/></Shape>
'''


def test_the_renderer_a_document_is_drawn_with(tmp_path):
    """The PBR pass by default, or the VRML97 pass: a PhysicalMaterial, which
    the PBR pass shades by its BRDF, comes out differently in the two"""
    assert R.build_parser().parse_args([]).renderer == 'pbr'
    pbr = render_document(tmp_path, LIT)
    phong = render_document(tmp_path, LIT, renderer='vrml97')
    assert pbr[32, 48].sum() > 60 and phong[32, 48].sum() > 60
    assert np.abs(pbr - phong).max() > 30


def test_documents_drawn_at_a_time(monkeypatch):
    monkeypatch.setattr(os, 'cpu_count', lambda: 64)
    assert R.default_jobs() == R.MAX_DEFAULT_JOBS
    monkeypatch.setattr(os, 'cpu_count', lambda: 3)
    assert R.default_jobs() == 3
    monkeypatch.setattr(os, 'cpu_count', lambda: None)
    assert R.default_jobs() == 1


def test_the_backend_a_document_is_drawn_on():
    args = R.build_parser().parse_args(['--backend', 'egl'])
    assert args.backend == 'egl'
    assert R._render_environment('out.png', 4, 'pbr', args.backend)['OPENGLCONTEXT_BACKEND'] == 'egl'
    assert R.build_parser().parse_args([]).backend == 'glfw'


def test_the_reference_column_is_named_for_its_reference(tmp_path):
    out_dir = tmp_path / 'renders'
    out_dir.mkdir()
    reference = tmp_path / 'xite.png'
    Image.new('RGB', (8, 8)).save(reference)
    Image.new('RGB', (8, 8)).save(out_dir / 'A.b.png')
    (out_dir / 'A.b.json').write_text(json.dumps(
        {'scene': 'A/b', 'reference': 'X_ITE 16.4.3', 'upstream': str(reference)}))
    report = tmp_path / 'report.html'
    R.build_report(str(out_dir), str(tmp_path / 'baselines'), str(report), 2.0, 5)
    html = report.read_text()
    assert '<h4>X_ITE 16.4.3</h4>' in html and 'Khronos' not in html
