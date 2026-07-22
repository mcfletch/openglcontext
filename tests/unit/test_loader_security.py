"""Security tests for the resource loader (no network, no GL).

The VRML/OBJ loader follows external references (ImageTexture urls, OBJ
``mtllib``, ``Inline`` scenes, shader fragments) that are attacker-controlled for
any document from an untrusted source. Resolution is delegated to
``resolver.Resolver`` via ``loader._resolver_for(baseURL)``, which enforces:

  * a document loaded from a local file may only reference files under its own
    directory (no ``../../etc/passwd``, no absolute paths, no ``file://`` escape),
  * a document fetched over http(s) may only reference same-origin http(s) URIs
    (blocks ``file://`` reads and link-local metadata SSRF).

``Resolver.resolve(uri)`` applies the policy without any network/disk access, so
the SSRF/cross-origin cases here never touch the network; ``_Loader.__call__``
exercises the full resolve+fetch path for the local cases.
"""
import os

import pytest

from OpenGLContext.loaders.loader import _resolver_for, _Loader
from OpenGLContext.loaders.resolver import Resolver


class TestLocalContainment:
    def test_sibling_file_allowed(self, tmp_path):
        base = tmp_path / 'scene.wrl'
        base.write_text('#VRML')
        tex = tmp_path / 'tex.png'
        tex.write_bytes(b'PNG')
        target = _resolver_for(str(base)).resolve('tex.png')
        assert os.path.realpath(target) == os.path.realpath(str(tex))

    def test_sibling_file_from_subdirectory_base(self, tmp_path):
        # Regression: a scene loaded via a path with a directory component (e.g.
        # ``wrls/scene.wrl``) must resolve ``./tex.png`` to the scene's own
        # directory, not double the directory prefix.
        sub = tmp_path / 'wrls'
        sub.mkdir()
        base = sub / 'scene.wrl'
        base.write_text('#VRML')
        tex = sub / 'tex.png'
        tex.write_bytes(b'PNG')
        target = _resolver_for(str(base)).resolve('./tex.png')
        assert os.path.realpath(target) == os.path.realpath(str(tex))

    def test_parent_traversal_blocked(self, tmp_path):
        base = tmp_path / 'sub' / 'scene.wrl'
        base.parent.mkdir()
        base.write_text('#VRML')
        with pytest.raises(IOError):
            _resolver_for(str(base)).resolve('../../etc/passwd')

    def test_absolute_path_escape_blocked(self, tmp_path):
        base = tmp_path / 'scene.wrl'
        base.write_text('#VRML')
        with pytest.raises(IOError):
            _resolver_for(str(base)).resolve('/etc/passwd')

    def test_file_scheme_escape_blocked(self, tmp_path):
        base = tmp_path / 'scene.wrl'
        base.write_text('#VRML')
        with pytest.raises(IOError):
            _resolver_for(str(base)).resolve('file:///etc/passwd')

    def test_remote_ref_from_local_base_blocked(self, tmp_path):
        base = tmp_path / 'scene.wrl'
        base.write_text('#VRML')
        with pytest.raises(IOError):
            _resolver_for(str(base)).resolve('http://169.254.169.254/latest/meta-data/')


class TestRemoteSameOrigin:
    def test_same_origin_allowed(self):
        target = _resolver_for('http://example.com/models/scene.wrl').resolve('../a/tex.png')
        assert target == 'http://example.com/a/tex.png'

    def test_cross_origin_blocked(self):
        with pytest.raises(IOError):
            _resolver_for('http://example.com/models/scene.wrl').resolve(
                'http://evil.example.net/x.png')

    def test_link_local_metadata_blocked(self):
        with pytest.raises(IOError):
            _resolver_for('http://example.com/models/scene.wrl').resolve(
                'http://169.254.169.254/latest/meta-data/')

    def test_file_scheme_from_remote_base_blocked(self):
        with pytest.raises(IOError):
            _resolver_for('http://example.com/models/scene.wrl').resolve('file:///etc/passwd')


class TestLoaderCallEnforcesPolicy:
    def test_call_opens_contained_texture(self, tmp_path):
        base = tmp_path / 'scene.wrl'
        base.write_text('#VRML')
        tex = tmp_path / 'tex.png'
        tex.write_bytes(b'PNGDATA')
        resolvedURL, filename, file, headers = _Loader()('tex.png', baseURL=str(base))
        try:
            assert file.read() == b'PNGDATA'
        finally:
            file.close()

    def test_call_resolves_reference_relative_to_loaded_file(self, tmp_path, monkeypatch):
        # End-to-end for the reported bug: load a scene by a cwd-relative path with
        # a directory component, then resolve a sibling texture through the base
        # URL the loader assigned. The texture must be found next to the .wrl.
        sub = tmp_path / 'wrls'
        sub.mkdir()
        (sub / 'scene.wrl').write_text('#VRML')
        (sub / 'tex.png').write_bytes(b'PNGDATA')
        monkeypatch.chdir(tmp_path)
        loader = _Loader()
        baseURL, file, filename, headers = loader.get('wrls/scene.wrl')
        file.close()
        assert os.path.isabs(baseURL)
        resolvedURL, texname, texfile, headers = loader('./tex.png', baseURL=baseURL)
        try:
            assert texfile.read() == b'PNGDATA'
        finally:
            texfile.close()

    def test_call_blocks_traversal(self, tmp_path):
        secret = tmp_path / 'secret.txt'
        secret.write_text('top secret')
        # ``scene.wrl`` lives one level down, so ``../secret.txt`` escapes its
        # directory and must be refused.
        deep = tmp_path / 'sub' / 'scene.wrl'
        deep.parent.mkdir()
        deep.write_text('#VRML')
        with pytest.raises(IOError):
            _Loader()('../secret.txt', baseURL=str(deep))


class TestLocalFetchSizeCap:
    def test_oversized_local_file_rejected_before_read(self, tmp_path, monkeypatch):
        # A confined-but-huge local sibling must be rejected on its size on disk,
        # before it is opened and slurped into RAM past the cap.
        big = tmp_path / 'big.bin'
        big.write_bytes(b'x' * 5000)
        resolver = Resolver(base_dir=str(tmp_path), max_resource_bytes=1000)

        import builtins
        real_open = builtins.open
        opened = {'n': 0}

        def guard(path, *args, **kwargs):
            try:
                if os.path.realpath(str(path)) == os.path.realpath(str(big)):
                    opened['n'] += 1
            except TypeError:
                pass
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, 'open', guard)
        with pytest.raises(ValueError):
            resolver.fetch('big.bin')
        assert opened['n'] == 0, "oversized local file was opened before the size check"

    def test_within_cap_local_file_fetched(self, tmp_path):
        small = tmp_path / 'small.bin'
        small.write_bytes(b'PNGDATA')
        resolver = Resolver(base_dir=str(tmp_path), max_resource_bytes=1000)
        assert resolver.fetch('small.bin') == b'PNGDATA'
