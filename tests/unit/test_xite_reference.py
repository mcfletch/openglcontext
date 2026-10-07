"""Reference renders of X3D documents from X_ITE, Web3D's JavaScript X3D browser.

``OpenGLContext.testing.xite`` serves a document and X_ITE (MIT) from a local
server to a headless Chromium (Playwright, the ``x3d-reference`` extra) and
keeps a screenshot of each, beside the corpus, for ``oglc-x3d-regression`` to
show beside our render.
"""
import io
import os
import tarfile
import urllib.error
import urllib.request

import pytest

from OpenGLContext.testing import xite


def tarball(tmp_path, members):
    path = tmp_path / 'x_ite.tgz'
    with tarfile.open(path, 'w:gz') as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return str(path)


class TestUnpacking:
    def test_the_distribution_folder(self, tmp_path):
        source = tarball(tmp_path, {'package/dist/x_ite.min.js': b'js',
                                    'package/dist/assets/a.js': b'a',
                                    'package/README.md': b'no'})
        dist = xite.unpack(source, str(tmp_path / 'out'))
        assert sorted(os.listdir(dist)) == ['assets', 'x_ite.min.js']

    def test_a_member_leaving_it_is_refused(self, tmp_path):
        source = tarball(tmp_path, {'package/dist/../../../escaped.js': b'x'})
        with pytest.raises(ValueError):
            xite.unpack(source, str(tmp_path / 'out'))


def test_the_harness_names_the_size():
    page = xite.harness_page((792, 465))
    assert 'x_ite/x_ite.min.js' in page and 'width:792px' in page and 'height:465px' in page


def test_a_reference_is_kept_by_version_and_slug(tmp_path):
    found = xite.reference_path(str(tmp_path), 'ConformanceNist.Geometry.Box.texture')
    assert found == os.path.join(str(tmp_path), '_x_ite', xite.VERSION,
                                 'ConformanceNist.Geometry.Box.texture.png')


class TestTheServer:
    def get(self, server, path):
        with urllib.request.urlopen('%s/%s' % (server.url, path), timeout=5) as response:
            return response.read()

    def test_the_page_x_ite_and_the_documents(self, tmp_path):
        (tmp_path / 'dist').mkdir()
        (tmp_path / 'dist' / 'x_ite.min.js').write_bytes(b'x_ite')
        (tmp_path / 'corpus' / 'A').mkdir(parents=True)
        (tmp_path / 'corpus' / 'A' / 'scene.x3d').write_bytes(b'<X3D/>')
        with xite.SceneServer(str(tmp_path / 'corpus'), str(tmp_path / 'dist'), (40, 30)) as server:
            assert self.get(server, 'x_ite/x_ite.min.js') == b'x_ite'
            assert self.get(server, 'scene/A/scene.x3d') == b'<X3D/>'
            assert b'x3d-canvas' in self.get(server, 'harness.html')
            assert server.url.startswith('http://127.0.0.1:')

    def test_nothing_outside_them(self, tmp_path):
        (tmp_path / 'dist').mkdir()
        (tmp_path / 'corpus').mkdir()
        (tmp_path / 'secret.txt').write_text('no')
        with xite.SceneServer(str(tmp_path / 'corpus'), str(tmp_path / 'dist'), (40, 30)) as server:
            for path in ('scene/../secret.txt', 'scene/%2e%2e/secret.txt', 'other/secret.txt'):
                with pytest.raises(urllib.error.HTTPError):
                    self.get(server, path)


def test_a_document_rendered_by_x_ite(tmp_path):
    """One real render: a red box on black, as X_ITE draws it"""
    pytest.importorskip('playwright', reason='the x3d-reference extra is not installed')
    if not xite.browser_available():
        pytest.skip('Playwright has no Chromium on this machine')
    import numpy as np  # noqa: PLC0415 kept with its use
    from PIL import Image  # noqa: PLC0415 kept with its use
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    (corpus / 'red.x3d').write_text(
        '<X3D profile="Interchange" version="3.3"><Scene><Shape><Appearance>'
        '<Material diffuseColor="1 0 0" emissiveColor="1 0 0"/></Appearance><Box/>'
        '</Shape></Scene></X3D>')
    out = str(tmp_path / 'red.png')
    with xite.ReferenceRenderer(str(corpus), xite.distribution(), (96, 64)) as renderer:
        report = renderer.render('red.x3d', out)
    assert report['ok'], report
    pixels = np.asarray(Image.open(out).convert('RGB')).astype(int)
    assert pixels.shape == (64, 96, 3)
    assert pixels[32, 48, 0] > 150 and pixels[32, 48, 1] < 80
    assert pixels[2, 2].sum() < 30
