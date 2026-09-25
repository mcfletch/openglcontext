"""One application's content: its registry, its store, and where its art is.

Each case writes a registry, opens a store in the test's own directory, and
serves the base pack over HTTP on this machine, so a first run is the whole of
a first run: nothing here, consent asked, the pack fetched, the art found.
"""

import io
import json
import os
import tarfile

import pytest

from OpenGLContext.contentpacks import Application, application, archive
from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb

from tests.unit.test_contentpacks_fetch import served  # noqa: F401 - a fixture


def an_art_pack(served_dir, name='art.tar.gz', marker='cars/hero.glb'):
    """The base pack's archive, holding one file, served from ``served_dir``."""
    path = served_dir / name
    with tarfile.open(path, 'w:gz') as handle:
        payload = b'hero'
        info = tarfile.TarInfo(marker)
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))
    return path


def a_registry(tmp_path, url, sha256='', needs=()):
    packs = [{'key': 'racer/cars', 'title': 'The cars', 'url': url,
              'directory': 'cars', 'archive': 'tar', 'approximate_bytes': 1024,
              'sha256': sha256, 'base': True, 'copyright': 'BSD-3-Clause',
              'marker': 'cars/hero.glb', 'needs': list(needs)},
             {'key': 'racer/track', 'title': 'A track',
              'url': 'https://example.invalid/track.tar.gz',
              'directory': 'track', 'archive': 'tar',
              'approximate_bytes': 1024, 'copyright': 'CC0',
              'marker': 'tileset.json'}]
    path = tmp_path / 'packs.json'
    path.write_text(json.dumps({'namespace': 'racer', 'packs': packs}))
    return str(path)


@pytest.fixture
def game(tmp_path, served):  # noqa: F811 - the fixture
    where, base = served
    built = an_art_pack(where)
    return Application(
        'racer', a_registry(tmp_path, base + '/art.tar.gz',
                            sha256=archive.digest(str(built))),
        base='racer/cars', root=str(tmp_path / 'store'),
        cache_dir=str(tmp_path / 'cache'))


@pytest.fixture(autouse=True)
def no_search(monkeypatch):
    monkeypatch.delenv('OPENGLCONTEXT_CONTENT', raising=False)


class TestTheRegistry:
    def test_it_is_the_shipped_one(self, game) -> None:
        assert [one.key for one in game.registry()] == ['racer/cars',
                                                        'racer/track']

    def test_it_is_read_once_until_asked_again(self, game) -> None:
        first = game.registry()
        assert game.registry() is first
        game.reload()
        assert game.registry() is not first

    def test_added_registries_are_read_where_the_application_asks(
            self, game, tmp_path) -> None:
        added = tmp_path / 'store' / 'registries'
        added.mkdir(parents=True)
        (added / 'more.json').write_text(json.dumps(
            {'namespace': 'others', 'packs': [
                {'key': 'others/hill', 'title': 'Hill',
                 'url': 'https://example.invalid/hill.tar.gz',
                 'directory': 'hill', 'archive': 'tar',
                 'approximate_bytes': 10, 'copyright': 'CC0',
                 'marker': 'x'}]}))
        assert 'others/hill' not in [one.key for one in game.registry()]
        with_added = Application('racer', game.catalog, root=game.root,
                                 added=True)
        assert 'others/hill' in [one.key for one in with_added.registry()]


class TestWhereTheArtIs:
    def test_the_fallback_until_the_pack_is_here(self, game,
                                                 tmp_path) -> None:
        game.fallback = str(tmp_path)
        assert game.base_directory() == str(tmp_path)

    def test_the_pack_once_it_is(self, game) -> None:
        assert game.ensure_base()
        assert game.base_directory() == game.store().directory_for(
            game.base_pack())

    def test_neither_says_what_is_missing_and_how_to_get_it(self,
                                                            game) -> None:
        game.fallback = '/no/such/directory'
        with pytest.raises(application.NotInstalled) as raised:
            game.base_directory()
        assert 'The cars' in str(raised.value)
        assert 'OPENGLCONTEXT_CONTENT' in str(raised.value)

    def test_the_library_reads_from_the_pack_fetched_after_it_was_made(
            self, game, tmp_path) -> None:
        """What a first run does: the art is named before it arrives."""
        game.fallback = str(tmp_path / 'wheel')
        (tmp_path / 'wheel').mkdir()
        library = game.library()
        assert library.load('cars/hero.glb') is None
        assert game.ensure_base()
        root = game.base_directory()
        write_glb([SceneNode(name='hero')],
                  path=os.path.join(root, 'cars', 'hero.glb'))
        assert library.root == root
        assert library.load('cars/hero.glb') is not None

    def test_it_is_one_library(self, game) -> None:
        assert game.library() is game.library()


class TestAFirstRun:
    def test_it_needs_the_base_pack(self, game) -> None:
        assert [one.key for one in game.needed_to_start()] == ['racer/cars']

    def test_consent_is_asked_with_what_would_be_fetched(self, game) -> None:
        asked = []
        assert game.ensure_base(
            consent=lambda packs: asked.append([p.key for p in packs]) or True)
        assert asked == [['racer/cars']]
        assert game.needed_to_start() == []

    def test_declining_fetches_nothing(self, game) -> None:
        assert not game.ensure_base(consent=lambda packs: False)
        assert game.needed_to_start() != []

    def test_a_later_run_asks_nothing(self, game) -> None:
        game.ensure_base()
        asked = []
        assert game.ensure_base(consent=lambda packs: asked.append(1) or True)
        assert asked == []

    def test_a_download_that_fails_raises_an_ioerror(self, tmp_path,
                                                     served) -> None:  # noqa: F811
        _, base = served
        game = Application('racer', a_registry(tmp_path, base + '/gone.tar.gz',
                                              sha256='0' * 64),
                           base='racer/cars', root=str(tmp_path / 'store'),
                           cache_dir=str(tmp_path / 'cache'))
        with pytest.raises(IOError):
            game.ensure_base()

    def test_the_job_fetches_it_off_the_frame_loop(self, game) -> None:
        job = game.base_job()
        assert [one.key for one in job.packs] == ['racer/cars']
        job.start()
        job._thread.join(timeout=30)
        job.poll()
        assert job.finished and job.failed is None
        assert game.needed_to_start() == []


class TestOnTheConsole:
    def test_it_lists_the_packs_and_asks(self, game) -> None:
        said = io.StringIO()
        consent = application.ask_on_console(stream=said,
                                             answer=lambda prompt: 'y')
        assert consent(game.needed_to_start())
        text = said.getvalue()
        assert 'The cars' in text and 'BSD-3-Clause' in text

    @pytest.mark.parametrize('answer', ['', 'n', 'no', 'maybe'])
    def test_anything_but_yes_declines(self, game, answer) -> None:
        consent = application.ask_on_console(stream=io.StringIO(),
                                             answer=lambda prompt: answer)
        assert not consent(game.needed_to_start())

    def test_the_end_of_input_declines(self, game) -> None:
        def closed(prompt):
            raise EOFError
        consent = application.ask_on_console(stream=io.StringIO(),
                                             answer=closed)
        assert not consent(game.needed_to_start())

    def test_a_script_says_yes_in_advance(self, game) -> None:
        def never(prompt):
            raise AssertionError('asked')
        consent = application.ask_on_console(assume_yes=True,
                                             stream=io.StringIO(), answer=never)
        assert consent(game.needed_to_start())

    def test_progress_is_a_line_every_few_per_cent(self) -> None:
        said = io.StringIO()
        progress = application.console_progress(stream=said, step=25)
        for done in range(0, 101):
            progress(done, 100)
        progress(5, None)
        assert said.getvalue().count('%') == 5

    def test_the_reply_is_read_with_input_when_it_is_asked(
            self, game, monkeypatch) -> None:
        consent = application.ask_on_console(stream=io.StringIO())
        monkeypatch.setattr('builtins.input', lambda prompt: 'yes')
        assert consent(game.needed_to_start())
