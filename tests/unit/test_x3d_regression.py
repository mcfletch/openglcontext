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
        path = os.path.join(root, 'ConformanceNist', 'www.web3d.org', 'x3d', 'content',
                            'examples', 'ConformanceNist', relative)
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
        assert found[0].root.endswith(os.path.join('examples', 'ConformanceNist'))

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


def test_a_document_may_name_an_image_above_its_folder(tmp_path):
    """Web3D's examples share images across folders: the archive is a content root"""
    from OpenGLContext.testing.glcontext import gl_available  # noqa: PLC0415 kept with its use
    if not gl_available():
        pytest.skip('no GL context on this machine')
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/textured.x3d': ''})
    scene = R.find_scenes(root, ['ConformanceNist'])[0]
    Image.new('RGB', (4, 4), (0, 0, 255)).save(os.path.join(scene.root, 'blue.png'))
    with open(scene.path, 'w') as stream:
        stream.write(DOCUMENT.replace(
            '<Material diffuseColor="1 0 0" emissiveColor="1 0 0"/>',
            '<ImageTexture url=\'"../../blue.png"\'/>') % '')
    out = str(tmp_path / 'blue.png')
    ok, report = R.render_scene(scene, out, size=(96, 64), frames=3)
    assert ok, report
    centre = np.asarray(Image.open(out).convert('RGB')).astype(int)[32, 48]
    assert centre[2] > 150 and centre[0] < 80, centre


def test_a_run_renders_records_blesses_and_reports(monkeypatch, tmp_path):
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/a.x3d': '', 'Geometry/Box/b.x3d': ''})

    def fake_render(scene, out, size, frames, timeout=R.RENDER_TIMEOUT):
        Image.new('RGB', size, (200, 0, 0)).save(out)
        return True, {'problems': ['warning: something'], 'viewpoint': None}

    monkeypatch.setattr(R, 'render_scene', fake_render)
    monkeypatch.setattr(R.renderregression, 'gl_renderer',
                        lambda: {'gl_renderer': 'test', 'gl_version': '0'})
    baselines, out_dir = str(tmp_path / 'baselines'), str(tmp_path / 'renders')
    report = str(tmp_path / 'report.html')
    arguments = ['--corpus', root, '--baseline-root', baselines, '--out-dir', out_dir,
                 '--report', report, '--size', '32x24', '--jobs', '2', '--reference', 'web3d']
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

    def different(scene, out, size, frames, timeout=R.RENDER_TIMEOUT):
        Image.new('RGB', size, (0, 0, 200)).save(out)
        return True, {'problems': [], 'viewpoint': None}

    monkeypatch.setattr(R, 'render_scene', different)
    assert R.main(arguments + ['--only', 'Box/a']) == 1


def test_no_corpus_says_how_to_fetch_one(tmp_path, capsys):
    assert R.main(['--corpus', str(tmp_path), '--out-dir', str(tmp_path / 'o'),
                   '--report', str(tmp_path / 'r.html')]) == 2
    assert '--fetch' in capsys.readouterr().out


class FakeReferences:
    """Stands in for xite.ReferenceRenderer: a blue frame for every document"""

    made = []

    def __init__(self, documents, dist, size):
        self.size = size

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def render(self, relative, out):
        FakeReferences.made.append(relative)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        Image.new('RGB', self.size, (0, 0, 200)).save(out)
        return {'ok': True, 'errors': ['x_ite said something'], 'seconds': 0.1}


def test_x_ites_render_is_the_reference(monkeypatch, tmp_path):
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/a.x3d': ''})

    def fake_render(scene, out, size, frames, timeout=R.RENDER_TIMEOUT):
        Image.new('RGB', size, (200, 0, 0)).save(out)
        return True, {'problems': [], 'viewpoint': None}

    monkeypatch.setattr(R, 'render_scene', fake_render)
    monkeypatch.setattr(R.renderregression, 'gl_renderer',
                        lambda: {'gl_renderer': 'test', 'gl_version': '0'})
    monkeypatch.setattr(R.xite, 'ReferenceRenderer', FakeReferences)
    monkeypatch.setattr(R.xite, 'distribution', lambda: str(tmp_path))
    monkeypatch.setattr(R, 'references_available', lambda: True)
    FakeReferences.made = []
    out_dir = str(tmp_path / 'renders')
    arguments = ['--corpus', root, '--baseline-root', str(tmp_path / 'b'), '--out-dir', out_dir,
                 '--report', str(tmp_path / 'r.html'), '--size', '32x24', '--reference', 'x_ite']
    R.main(arguments)
    with open(os.path.join(out_dir, 'ConformanceNist.Geometry.Box.a.json')) as stream:
        record = json.load(stream)
    assert record['reference'] == 'X_ITE %s' % R.xite.VERSION
    assert record['upstream'].endswith(os.path.join('_x_ite', R.xite.VERSION,
                                                    'ConformanceNist.Geometry.Box.a.png'))
    assert record['reference_errors'] == ['x_ite said something']
    assert record['reference_difference'] == pytest.approx(100.0)
    assert FakeReferences.made == ['Geometry/Box/a.x3d']
    R.main(arguments)
    assert FakeReferences.made == ['Geometry/Box/a.x3d'], 'kept, not drawn again'
    R.main(arguments + ['--refresh-references'])
    assert len(FakeReferences.made) == 2


def test_without_x_ite_web3ds_render_is_the_reference(monkeypatch, tmp_path, capsys):
    root = write_corpus(str(tmp_path / 'corpus'), {'Geometry/Box/a.x3d': ''})

    def fake_render(scene, out, size, frames, timeout=R.RENDER_TIMEOUT):
        Image.new('RGB', size, (200, 0, 0)).save(out)
        return True, {'problems': [], 'viewpoint': None}

    monkeypatch.setattr(R, 'render_scene', fake_render)
    monkeypatch.setattr(R.renderregression, 'gl_renderer',
                        lambda: {'gl_renderer': 'test', 'gl_version': '0'})
    monkeypatch.setattr(R, 'references_available', lambda: False)
    out_dir = str(tmp_path / 'renders')
    R.main(['--corpus', root, '--baseline-root', str(tmp_path / 'b'), '--out-dir', out_dir,
            '--report', str(tmp_path / 'r.html'), '--size', '32x24', '--reference', 'x_ite'])
    with open(os.path.join(out_dir, 'ConformanceNist.Geometry.Box.a.json')) as stream:
        assert json.load(stream)['reference'] == 'Web3D'
    assert 'x3d-reference' in capsys.readouterr().out
