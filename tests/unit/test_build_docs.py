"""``build-docs.py``: the environment Sphinx is started in.

Sphinx calls ``setlocale(LC_ALL, '')`` at start-up and exits on the
``locale.Error`` that raises, so a shell whose ``LANG`` or ``LC_ALL`` names a
locale this machine has not installed cannot build the site unless the script
replaces it.
"""
import importlib.util
import locale
from pathlib import Path

import pytest

from OpenGLContext.testing.paths import tests_root

SCRIPT = tests_root(__file__).parent / 'build-docs.py'

pytestmark = pytest.mark.skipif(not SCRIPT.is_file(),
                                reason='build-docs.py not in this checkout')


@pytest.fixture(scope='module')
def build_docs():
    """``build-docs.py``, which is a script rather than a module."""
    spec = importlib.util.spec_from_file_location('build_docs', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheLocaleSphinxRunsUnder:
    """Sphinx exits where ``setlocale(LC_ALL, '')`` raises, and runs where it does not."""

    def test_an_installed_locale_is_left_alone(self, build_docs, monkeypatch):
        monkeypatch.setenv('LC_ALL', 'C')
        assert build_docs.sphinx_environment()['LC_ALL'] == 'C'

    def test_a_locale_that_is_not_installed_is_replaced(self, build_docs, monkeypatch):
        monkeypatch.setenv('LC_ALL', 'xx_NOWHERE.UTF-8')
        assert build_docs.sphinx_environment()['LC_ALL'] == build_docs.SPHINX_LOCALE

    def test_a_lang_that_is_not_installed_is_outranked(self, build_docs, monkeypatch):
        monkeypatch.delenv('LC_ALL', raising=False)
        monkeypatch.setenv('LANG', 'xx_NOWHERE.UTF-8')
        assert build_docs.sphinx_environment()['LC_ALL'] == build_docs.SPHINX_LOCALE

    def test_the_probe_leaves_this_process_as_it_was(self, build_docs, monkeypatch):
        before = locale.setlocale(locale.LC_ALL)
        monkeypatch.setenv('LC_ALL', 'xx_NOWHERE.UTF-8')
        build_docs.sphinx_environment()
        assert locale.setlocale(locale.LC_ALL) == before

    def test_sphinx_is_started_in_that_environment(self, build_docs, monkeypatch, tmp_path):
        started = {}

        def check_call(_command, **kwargs):
            started.update(kwargs)

        monkeypatch.setenv('LC_ALL', 'xx_NOWHERE.UTF-8')
        monkeypatch.setattr(build_docs.subprocess, 'check_call', check_call)
        build_docs.build_html(str(tmp_path), 'html', warnings_are_errors=False)
        assert started['env']['LC_ALL'] == build_docs.SPHINX_LOCALE


class TestTheOutputOfAnEarlierBuild:
    """Sphinx writes over the pages it builds and leaves every other file, so a
    page whose source has gone would otherwise be published from the last build
    that had it."""

    @pytest.fixture
    def sphinx(self, build_docs, monkeypatch):
        """The files in the output directory as Sphinx starts."""
        found = {}

        def check_call(command, **_kwargs):
            output = Path(command[-1])
            found['files'] = sorted(
                path.relative_to(output).as_posix()
                for path in (output.rglob('*') if output.is_dir() else ())
            )
            output.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(build_docs.subprocess, 'check_call', check_call)
        return found

    def test_a_page_whose_source_has_gone_is_not_kept(self, build_docs, sphinx, tmp_path):
        (tmp_path / 'tutorials').mkdir()
        (tmp_path / 'tutorials' / 'shader_1.html').write_text('old', encoding='utf8')
        (tmp_path / '.buildinfo').write_text('', encoding='utf8')
        build_docs.build_html(str(tmp_path), 'html', warnings_are_errors=False)
        assert sphinx['files'] == []

    def test_a_directory_no_build_wrote_is_refused(self, build_docs, sphinx, tmp_path):
        (tmp_path / 'notes.txt').write_text('mine', encoding='utf8')
        with pytest.raises(build_docs.Failed, match='no build'):
            build_docs.build_html(str(tmp_path), 'html', warnings_are_errors=False)
        assert (tmp_path / 'notes.txt').read_text(encoding='utf8') == 'mine'
        assert sphinx == {}

    def test_an_empty_or_missing_directory_is_built_into(
        self, build_docs, sphinx, tmp_path
    ):
        build_docs.build_html(str(tmp_path / 'html'), 'html', warnings_are_errors=False)
        assert sphinx['files'] == []
