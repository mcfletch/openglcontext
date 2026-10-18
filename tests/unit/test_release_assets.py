"""The engine's own ``release-assets.py``: what goes into the gallery pack.

The script is loaded from the checkout and driven with ``--world``, which packs
a glB already built and needs neither Blender nor openglcontext-editor. The
registry it writes is pointed into the test's own directory.
"""

import importlib.util
import os
import subprocess
import tarfile

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))


@pytest.fixture
def script(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        'release_assets', os.path.join(HERE, 'release-assets.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'CATALOG', str(tmp_path / 'packs.json'))
    return module


def git(where, *arguments):
    done = subprocess.run(['git', '-C', str(where), *arguments],
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def a_clone(tmp_path):
    """The directory the shipped registry is written into, as a repository.

    The registry is written only where its archives can be tagged.
    """
    git(tmp_path, 'init')
    git(tmp_path, 'config', 'user.name', 'Test')
    git(tmp_path, 'config', 'user.email', 'test@example.com')
    (tmp_path / 'source.txt').write_text('source')
    git(tmp_path, 'add', 'source.txt')
    git(tmp_path, 'commit', '-m', 'source')


def a_world(tmp_path, credits=True):
    where = tmp_path / 'built'
    where.mkdir()
    (where / 'world.glb').write_bytes(b'glTF' + b'\0' * 64)
    if credits:
        (where / 'CREDITS.txt').write_text('Marble Bust 01, CC0')
    return str(where / 'world.glb')


def members(path):
    with tarfile.open(path) as handle:
        return sorted(handle.getnames())


class TestWhatThePackHolds:
    def test_a_file_an_earlier_build_left_is_not_packed(self, script,
                                                        tmp_path):
        into = tmp_path / 'dist'
        (into / 'gallery').mkdir(parents=True)
        (into / 'gallery' / 'from-last-time.txt').write_text('stale')
        assert script.main(['--world', a_world(tmp_path),
                            '--into', str(into)]) == 0
        assert members(into / 'gallery-world.tar.gz') == [
            'CREDITS.txt', 'gallery.glb']

    def test_a_world_without_its_credits_is_refused(self, script, tmp_path,
                                                    capsys):
        """The registry promises the attribution is inside the pack."""
        into = tmp_path / 'dist'
        assert script.main(['--world', a_world(tmp_path, credits=False),
                            '--into', str(into)]) == 2
        assert 'CREDITS.txt' in capsys.readouterr().err
        assert not (into / 'gallery-world.tar.gz').exists()
        assert not (tmp_path / 'packs.json').exists()


class TestWhereTheRegistryIsWritten:
    """The shipped registry names what a release carries, so only a run that
    publishes (or says it means to) rewrites it."""

    def test_a_build_writes_its_registry_beside_the_archive(self, script,
                                                            tmp_path):
        into = tmp_path / 'dist'
        assert script.main(['--world', a_world(tmp_path),
                            '--into', str(into)]) == 0
        assert (into / 'packs.json').is_file()
        assert not (tmp_path / 'packs.json').exists()

    def test_asking_for_it_writes_the_shipped_one(self, script, tmp_path):
        a_clone(tmp_path)
        into = tmp_path / 'dist'
        assert script.main(['--world', a_world(tmp_path), '--into', str(into),
                            '--write-registry']) == 0
        assert (tmp_path / 'packs.json').read_text() == \
            (into / 'packs.json').read_text()

    def test_the_gallery_pack_is_tagged_apart_from_the_textures(
            self, script, tmp_path):
        a_clone(tmp_path)
        script.main(['--only', 'gallery', '--world', a_world(tmp_path),
                     '--into', str(tmp_path / 'dist'), '--write-registry'])
        assert git(tmp_path, 'tag', '--list', 'content-*') == \
            'content-gallery-world-v1'

    def test_building_one_pack_keeps_the_entries_of_the_other_in_the_shipped_registry(
            self, script, tmp_path):
        """The textures and the gallery are published separately; publishing one must not
        drop the other from the registry the engine ships."""
        import json
        a_clone(tmp_path)
        (tmp_path / 'packs.json').write_text(json.dumps({
            'namespace': 'openglcontext',
            'packs': [{'key': 'openglcontext/textures', 'title': 'CC0 PBR textures',
                       'url': 'https://example.invalid/textures.tar.gz',
                       'directory': 'textures', 'archive': 'tar', 'approximate_bytes': 1,
                       'sha256': '0' * 64, 'copyright': 'CC0', 'marker': 'CREDITS.txt',
                       'notes': ''}]}))
        assert script.main(['--only', 'gallery', '--world', a_world(tmp_path),
                            '--into', str(tmp_path / 'dist'), '--write-registry']) == 0
        keys = [pack['key'] for pack in json.loads((tmp_path / 'packs.json').read_text())['packs']]
        assert sorted(keys) == ['openglcontext/gallery', 'openglcontext/textures']
