"""``scripts/x3d_xite_references.py``: X_ITE's renders of the X3D corpus.

The script runs under ``uv run`` with Playwright and is not part of the
engine; these tests load it by path and exercise what needs no browser. One
test draws a document in X_ITE where Playwright and its Chromium are present.
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request

import pytest

from OpenGLContext.bin import x3d_regression

SCRIPT = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, 'scripts',
                      'x3d_xite_references.py')


@pytest.fixture(scope='module')
def tool():
    spec = importlib.util.spec_from_file_location('_x3d_xite_references', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def tarball(tmp_path, members):
    path = tmp_path / 'x_ite.tgz'
    with tarfile.open(path, 'w:gz') as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return str(path)


def write_corpus(root, archive, documents):
    examples = os.path.join(root, archive, 'www.web3d.org', 'x3d', 'content', 'examples', archive)
    for name, text in documents.items():
        path = os.path.join(examples, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as stream:
            stream.write(text)


class TestTheRoster:
    def test_the_documents_and_names_of_oglc_x3d_regression(self, tool, tmp_path):
        root = str(tmp_path)
        write_corpus(root, 'ConformanceNist', {'Geometry/Box/a.x3d': '<X3D/>',
                                               'Geometry/Box/empty.x3d': '',
                                               'Geometry/Box/a.wrl': '#VRML'})
        write_corpus(root, 'Vrml2Sourcebook', {'Chapter01/b.x3d': '<X3D/>'})
        archives = ('ConformanceNist', 'Vrml2Sourcebook')
        for only in (None, ['Box']):
            ours = [(d.name, d.slug, d.path, d.root)
                    for d in tool.find_documents(root, archives, only)]
            theirs = [(s.name, s.slug, s.path, s.root)
                      for s in x3d_regression.find_scenes(root, archives, only)]
            assert ours == theirs and ours
        assert [d.slug for d in tool.find_documents(root, archives)] == [
            'ConformanceNist.Geometry.Box.a', 'Vrml2Sourcebook.Chapter01.b']

    def test_written_where_oglc_x3d_regression_reads_them(self, tool):
        assert os.path.realpath(tool.default_out_dir()) == os.path.realpath(
            x3d_regression.default_reference_root())

    def test_the_same_size_and_archives(self, tool):
        assert tool.DEFAULT_SIZE == x3d_regression.DEFAULT_SIZE
        assert tool.DEFAULT_ARCHIVES == x3d_regression.DEFAULT_ARCHIVES


class TestUnpacking:
    def test_the_distribution_folder(self, tool, tmp_path):
        source = tarball(tmp_path, {'package/dist/x_ite.min.js': b'js',
                                    'package/dist/assets/a.js': b'a',
                                    'package/README.md': b'no'})
        dist = tool.unpack(source, str(tmp_path / 'out'))
        assert sorted(os.listdir(dist)) == ['assets', 'x_ite.min.js']

    def test_a_member_leaving_it_is_refused(self, tool, tmp_path):
        source = tarball(tmp_path, {'package/dist/../../../escaped.js': b'x'})
        with pytest.raises(ValueError):
            tool.unpack(source, str(tmp_path / 'out'))


def test_the_harness_names_the_size(tool):
    page = tool.harness_page((792, 465))
    assert 'x_ite/x_ite.min.js' in page and 'width:792px' in page and 'height:465px' in page


class TestTheServer:
    def get(self, server, path):
        with urllib.request.urlopen('%s/%s' % (server.url, path), timeout=5) as response:
            return response.read()

    def test_the_page_x_ite_and_the_documents(self, tool, tmp_path):
        (tmp_path / 'dist').mkdir()
        (tmp_path / 'dist' / 'x_ite.min.js').write_bytes(b'x_ite')
        (tmp_path / 'corpus' / 'A').mkdir(parents=True)
        (tmp_path / 'corpus' / 'A' / 'scene.x3d').write_bytes(b'<X3D/>')
        with tool.SceneServer(str(tmp_path / 'corpus'), str(tmp_path / 'dist'), (40, 30)) as server:
            assert self.get(server, 'x_ite/x_ite.min.js') == b'x_ite'
            assert self.get(server, 'scene/A/scene.x3d') == b'<X3D/>'
            assert b'x3d-canvas' in self.get(server, 'harness.html')
            assert server.url.startswith('http://127.0.0.1:')

    def test_nothing_outside_them(self, tool, tmp_path):
        (tmp_path / 'dist').mkdir()
        (tmp_path / 'corpus').mkdir()
        (tmp_path / 'secret.txt').write_text('no')
        with tool.SceneServer(str(tmp_path / 'corpus'), str(tmp_path / 'dist'), (40, 30)) as server:
            for path in ('scene/../secret.txt', 'scene/%2e%2e/secret.txt', 'other/secret.txt',
                         'scene//etc/passwd'):
                with pytest.raises(urllib.error.HTTPError):
                    self.get(server, path)


def test_only_the_local_server_is_reached(tool):
    base = 'http://127.0.0.1:4242'
    assert tool.is_local(base + '/scene/a.x3d', base)
    assert tool.is_local(base, base)
    for url in ('https://www.web3d.org/x3d/content/examples/vts.jpg',
                'http://127.0.0.1:4243/scene/a.x3d', 'http://127.0.0.1:42420/x',
                'http://127.0.0.1:4242.example.com/', 'data:text/plain,x'):
        assert not tool.is_local(url, base), url


def test_documents_with_references_are_not_drawn_again(tool, tmp_path, monkeypatch):
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'A.done.png').write_bytes(b'png')
    documents = [tool.Document('A/done', 'p', 'r'), tool.Document('A/new', 'p', 'r')]
    drawn = []
    monkeypatch.setattr(tool, 'distribution', lambda: str(tmp_path))

    class Renderer:
        version = 'test'

        def __init__(self, documents, dist, size):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def render(self, relative, path):
            drawn.append(path)
            return {'ok': True, 'errors': [], 'seconds': 0.0}

    monkeypatch.setattr(tool, 'Renderer', Renderer)
    assert tool.render_all(documents, str(out), (8, 8), jobs=2) == 1
    assert drawn == [str(out / 'A.new.png')]
    assert (out / 'A.new.json').exists()
    assert tool.render_all(documents, str(out), (8, 8), jobs=2, refresh=True) == 2


def test_a_document_rendered_by_x_ite(tmp_path):
    """One real render, through ``uv run`` as the script is used: a red box on black"""
    uv = shutil.which('uv') or os.path.join(os.path.dirname(sys.executable), 'uv')
    if not os.path.exists(uv):
        pytest.skip('uv runs the script, and is not installed')
    import numpy as np  # noqa: PLC0415 kept with its use
    from PIL import Image  # noqa: PLC0415 kept with its use
    corpus, out = str(tmp_path / 'corpus'), tmp_path / 'out'
    write_corpus(corpus, 'Tiny', {'red.x3d': (
        '<X3D profile="Interchange" version="3.3"><Scene><Shape><Appearance>'
        '<Material diffuseColor="1 0 0" emissiveColor="1 0 0"/></Appearance><Box/>'
        '</Shape></Scene></X3D>')})
    proc = subprocess.run(
        [uv, 'run', '--quiet', '--script', SCRIPT, '--corpus', corpus, '--archive', 'Tiny',
         '--out', str(out), '--size', '96x64', '--jobs', '1'],
        capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    record = json.loads((out / 'Tiny.red.json').read_text())
    assert record['ok'] and record['scene'] == 'Tiny/red', record
    pixels = np.asarray(Image.open(out / 'Tiny.red.png').convert('RGB')).astype(int)
    assert pixels.shape == (64, 96, 3)
    assert pixels[32, 48, 0] > 150 and pixels[32, 48, 1] < 80
    assert pixels[2, 2].sum() < 30
