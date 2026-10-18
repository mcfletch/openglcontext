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


def test_a_distribution_is_cached_once_unpacked(tmp_path, tool):
    assert tool.cached_distribution(str(tmp_path)) is None
    dist = tmp_path / 'openglcontext-tools' / 'x_ite' / tool.VERSION / 'dist'
    dist.mkdir(parents=True)
    (dist / 'x_ite.min.js').write_text('')
    assert tool.cached_distribution(str(tmp_path)) == str(dist)
    assert tool.distribution(str(tmp_path)) == str(dist)


def tarball(tmp_path, members):
    path = tmp_path / 'x_ite.tgz'
    with tarfile.open(path, 'w:gz') as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return str(path)


def write_corpus(root, archive, documents):
    examples = os.path.join(root, 'www.web3d.org', 'x3d', 'content', 'examples', archive)
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

    def test_drawn_at_the_world_time_oglc_x3d_regression_reads(self, tool):
        assert tool.WORLD_START == x3d_regression.WORLD_START
        assert tool.CAPTURE_FPS == x3d_regression.CAPTURE_FPS
        assert tool.CAPTURE_FRAMES == x3d_regression.DEFAULT_FRAMES
        assert tool.capture_time() == x3d_regression.capture_time(x3d_regression.DEFAULT_FRAMES)
        assert tool.capture_time(3) == x3d_regression.capture_time(3)


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

    def test_an_unpack_cut_short_leaves_nothing_taken_for_complete(self, tool, tmp_path):
        source = tarball(tmp_path, {'package/dist/x_ite.min.js': b'js',
                                    'package/dist/../../../escaped.js': b'x'})
        with pytest.raises(ValueError):
            tool.unpack(source, str(tmp_path / 'out'))
        assert not (tmp_path / 'out' / 'dist').exists()
        assert os.listdir(tmp_path / 'out') == []

    def test_an_unpack_over_one_already_there(self, tool, tmp_path):
        source = tarball(tmp_path, {'package/dist/x_ite.min.js': b'js'})
        tool.unpack(source, str(tmp_path / 'out'))
        dist = tool.unpack(source, str(tmp_path / 'out'))
        assert sorted(os.listdir(tmp_path / 'out')) == ['dist']
        assert os.listdir(dist) == ['x_ite.min.js']


def test_the_harness_names_the_size(tool):
    page = tool.harness_page((792, 465))
    assert 'x_ite/x_ite.min.js' in page and 'width:792px' in page and 'height:465px' in page


def test_the_harness_puts_the_page_on_the_capture_clock_before_x_ite(tool):
    page = tool.harness_page((792, 465))
    assert page.index('window.Date = CaptureDate') < page.index('x_ite/x_ite.min.js')
    assert 'start: %r' % (tool.WORLD_START * 1000.0) in page
    assert 'step: 1000 / %d' % tool.CAPTURE_FPS in page
    assert 'async function settle(frames, timeout)' in page


def test_the_harness_leaves_a_viewpoints_roll_as_the_document_gives_it(tool):
    page = tool.harness_page((792, 465))
    option = "setBrowserOption('StraightenHorizon', false)"
    assert option in page
    assert page.index(option) < page.index("canvas.setAttribute('src'")


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


    def test_a_request_naming_another_host(self, tool, tmp_path):
        (tmp_path / 'dist').mkdir()
        (tmp_path / 'corpus').mkdir()
        with tool.SceneServer(str(tmp_path / 'corpus'), str(tmp_path / 'dist'), (40, 30)) as server:
            request = urllib.request.Request(server.url + '/harness.html',
                                             headers={'Host': 'rebound.example'})
            with pytest.raises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(request, timeout=5)
            assert refused.value.code == 403

    def test_a_nul_byte_is_not_found(self, tool, tmp_path):
        (tmp_path / 'dist').mkdir()
        (tmp_path / 'corpus').mkdir()
        with tool.SceneServer(str(tmp_path / 'corpus'), str(tmp_path / 'dist'), (40, 30)) as server:
            with pytest.raises(urllib.error.HTTPError) as missing:
                self.get(server, 'scene/a%00b.x3d')
            assert missing.value.code == 404


def test_only_the_local_server_is_reached(tool):
    base = 'http://127.0.0.1:4242'
    assert tool.is_local(base + '/scene/a.x3d', base)
    assert tool.is_local(base, base)
    for url in ('https://www.web3d.org/x3d/content/examples/vts.jpg',
                'http://127.0.0.1:4243/scene/a.x3d', 'http://127.0.0.1:42420/x',
                'http://127.0.0.1:4242.example.com/', 'data:text/plain,x'):
        assert not tool.is_local(url, base), url


@pytest.fixture
def stand_in(tool, tmp_path, monkeypatch):
    """The tool with a renderer that draws nothing, failing the documents
    named in its `failing`; `drawn` and `installs` record what it was asked"""

    class Renderer:
        version = 'test'
        drawn: list = []
        installs: list = []
        failing: set = set()
        #: Documents whose first draw loses the driver.
        losing: set = set()
        alive = True

        def __init__(self, documents, dist, size):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def render(self, relative, path):
            Renderer.drawn.append(path)
            name = os.path.basename(path)
            if name in Renderer.losing:
                Renderer.losing.discard(name)
                Renderer.alive = False
                return {'ok': False, 'errors': ['driver gone'], 'seconds': 0.0}
            return {'ok': name not in Renderer.failing, 'errors': [], 'seconds': 0.0}

        def connected(self):
            alive, Renderer.alive = Renderer.alive, True
            return alive

    monkeypatch.setattr(tool, 'distribution', lambda: str(tmp_path))
    monkeypatch.setattr(tool, 'ensure_browser', lambda: Renderer.installs.append(True))
    monkeypatch.setattr(tool, 'Renderer', Renderer)
    monkeypatch.setattr(tool, 'ISOLATED', False)
    return Renderer


def test_documents_with_references_are_not_drawn_again(tool, tmp_path, stand_in):
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'A.done.png').write_bytes(b'png')
    documents = [tool.Document('A/done', 'p', 'r'), tool.Document('A/new', 'p', 'r')]
    assert tool.render_all(documents, str(out), (8, 8), jobs=2) == tool.Outcome(1, [])
    assert stand_in.drawn == [str(out / 'A.new.png')]
    assert (out / 'A.new.json').exists()
    assert tool.render_all(documents, str(out), (8, 8), jobs=2, refresh=True).drawn == 2


def test_nothing_is_installed_when_nothing_is_drawn(tool, tmp_path, stand_in):
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'A.done.png').write_bytes(b'png')
    assert tool.render_all([tool.Document('A/done', 'p', 'r')], str(out), (8, 8), jobs=1) \
        == tool.Outcome(0, [])
    assert stand_in.installs == []
    tool.render_all([tool.Document('A/new', 'p', 'r')], str(out), (8, 8), jobs=1)
    assert stand_in.installs == [True]


def test_a_failed_render_fails_the_run(tool, tmp_path, stand_in, capsys):
    corpus = str(tmp_path / 'corpus')
    write_corpus(corpus, 'Tiny', {'good.x3d': '<X3D/>', 'bad.x3d': '<X3D/>'})
    stand_in.failing = {'Tiny.bad.png'}
    out = str(tmp_path / 'out')
    status = tool.main(['--corpus', corpus, '--archive', 'Tiny', '--out', out])
    printed = capsys.readouterr().out
    assert status == 1
    assert 'FAIL  Tiny/bad' in printed and 'OK    Tiny/good' in printed
    assert '1 of 2 documents failed' in printed
    stand_in.failing = set()
    assert tool.main(['--corpus', corpus, '--archive', 'Tiny', '--out', out, '--refresh']) == 0


def test_chunks_are_one_folders_documents_at_most_so_many(tool):
    documents = [tool.Document('A/%d' % index, 'p', 'one') for index in range(5)]
    documents.append(tool.Document('B/x', 'p', 'two'))
    found = tool.chunks(documents, 2)
    assert [len(chunk) for chunk in found] == [2, 2, 1, 1]
    assert all(len({document.root for document in chunk}) == 1 for chunk in found)


def test_a_lost_driver_leaves_its_documents_to_another_browser(tool, tmp_path, stand_in):
    out = tmp_path / 'out'
    documents = [tool.Document('A/%d' % index, 'p', 'r') for index in range(4)]
    stand_in.losing = {'A.1.png'}
    outcome = tool.render_all(documents, str(out), (8, 8), jobs=1)
    assert outcome == tool.Outcome(4, [])
    assert stand_in.drawn.count(str(out / 'A.1.png')) == 2
    assert stand_in.drawn.count(str(out / 'A.0.png')) == 1


def test_a_record_from_before_the_run_is_not_counted(tool, tmp_path):
    document = tool.Document('A/old', 'p', 'r')
    record = tmp_path / 'A.old.json'
    record.write_text('{"ok": true}')
    assert tool.drawn_since(document, str(tmp_path), 0.0) is True
    assert tool.drawn_since(document, str(tmp_path), os.path.getmtime(record) + 1) is None
    assert tool.drawn_since(tool.Document('A/none', 'p', 'r'), str(tmp_path), 0.0) is None


def test_browsers_at_a_time_leave_room_for_swiftshader(tool, monkeypatch):
    monkeypatch.setattr(os, 'cpu_count', lambda: 32)
    assert tool.default_jobs() == 8
    monkeypatch.setattr(os, 'cpu_count', lambda: 2)
    assert tool.default_jobs() == 1
    monkeypatch.setattr(os, 'cpu_count', lambda: None)
    assert tool.default_jobs() == 1


#: What ``uv run`` resolves the script's dependencies from.
PACKAGE_INDEX = 'https://pypi.org/simple/playwright/'


@pytest.mark.network
@pytest.mark.slow
def test_a_document_rendered_by_x_ite(tmp_path, tool):
    """Real renders, through ``uv run`` as the script is used: a red box on
    black, and a box half red at the capture time

    The run fetches Playwright, its Chromium and X_ITE where they are not cached.
    """
    from OpenGLContext.testing.network import unreachable  # noqa: PLC0415 kept with its use
    uv = shutil.which('uv') or os.path.join(os.path.dirname(sys.executable), 'uv')
    if not os.path.exists(uv):
        pytest.skip('uv runs the script, and is not installed')
    needed = [PACKAGE_INDEX] + ([] if tool.cached_distribution() else [tool.TARBALL_URL])
    for url in needed:
        reason = unreachable(url)
        if reason:
            pytest.skip(reason)
    import numpy as np  # noqa: PLC0415 kept with its use
    from PIL import Image  # noqa: PLC0415 kept with its use
    from tests.unit.test_x3d_regression import stepped_clock_document  # noqa: PLC0415 kept with its use
    corpus, out = str(tmp_path / 'corpus'), tmp_path / 'out'
    clocked = stepped_clock_document(tool.capture_time(), 1.0 / tool.CAPTURE_FPS)
    write_corpus(corpus, 'Tiny', {'red.x3d': (
        '<X3D profile="Interchange" version="3.3"><Scene><Shape><Appearance>'
        '<Material diffuseColor="1 0 0" emissiveColor="1 0 0"/></Appearance><Box/>'
        '</Shape></Scene></X3D>'), 'clocked.x3d': (
        '<X3D profile="Immersive" version="3.3"><Scene>%s</Scene></X3D>' % clocked)})
    proc = subprocess.run(
        [uv, 'run', '--quiet', '--script', SCRIPT, '--corpus', corpus, '--archive', 'Tiny',
         '--out', str(out), '--size', '96x64', '--jobs', '1'],
        capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    record = json.loads((out / 'Tiny.red.json').read_text())
    assert record['ok'] and record['scene'] == 'Tiny/red', record
    assert record['world_time'] == pytest.approx(tool.capture_time(), abs=1e-3)
    pixels = np.asarray(Image.open(out / 'Tiny.red.png').convert('RGB')).astype(int)
    assert pixels.shape == (64, 96, 3)
    assert pixels[32, 48, 0] > 150 and pixels[32, 48, 1] < 80
    assert pixels[2, 2].sum() < 30
    clocked = np.asarray(Image.open(out / 'Tiny.clocked.png').convert('RGB')).astype(int)
    assert 40 < clocked[32, 48, 0] < 220, 'drawn at capture_time(), as oglc-x3d-regression draws'
