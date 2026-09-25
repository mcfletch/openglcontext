"""The engine's own ``release-assets.py``: what goes into the gallery pack.

The script is loaded from the checkout and driven with ``--world``, which packs
a glB already built and needs neither Blender nor openglcontext-editor. The
registry it writes is pointed into the test's own directory.
"""

import importlib.util
import os
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
        into = tmp_path / 'dist'
        assert script.main(['--world', a_world(tmp_path), '--into', str(into),
                            '--write-registry']) == 0
        assert (tmp_path / 'packs.json').read_text() == \
            (into / 'packs.json').read_text()
