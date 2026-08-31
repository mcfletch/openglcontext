"""What the script suite picks up out of the tests directory.

A leading underscore marks a module that is imported by a demo rather than run as
one -- a font helper, a texture generator, a subprocess driver. Launching one as a
script renders nothing, so the collector leaves them alone.
"""
import sys

from OpenGLContext.testing.paths import tests_root

# test_all_scripts stays in the tests root, beside the demos it collects.
sys.path.insert(0, str(tests_root(__file__)))


class TestUnderscoreModulesAreNotScripts:
    def test_collection_skips_underscore_names(self, tmp_path, monkeypatch):
        import test_all_scripts as tas

        for name in ('demo.py', '_helper.py', '__init__.py'):
            (tmp_path / name).write_text('')
        monkeypatch.setattr(tas, 'TESTS_DIR', tmp_path)

        assert [p.name for p in tas.get_all_test_scripts()] == ['demo.py']

    def test_no_underscore_script_is_collected_from_the_tests_directory(self):
        import test_all_scripts as tas

        collected = [p.name for p in tas.get_all_test_scripts()]
        assert [name for name in collected if name.startswith('_')] == []
