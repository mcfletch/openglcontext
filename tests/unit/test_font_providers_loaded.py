"""What a context loads when the first text is drawn: the texture, solid and
bitmap providers the engine draws with, and pygame's only where a program
imports it."""
import subprocess
import sys

LOAD = '''
import sys
from OpenGLContext.scenegraph.text import fontprovider, text
from OpenGLContext.vrmlcontext import VRMLSceneMixin

class Fonts(VRMLSceneMixin):
    def getTTFFiles(self):
        raise ImportError('no registry wanted here')

Fonts.setupFontProviders(Fonts.__new__(Fonts))
%s
print('pygame' in sys.modules)
print(sorted(type(provider).__name__
             for format in fontprovider.FontProvider.PROVIDER_SEARCH_ORDER
             for provider in fontprovider.FontProvider.getProviders(format)))
'''


def loaded(then=''):
    done = subprocess.run([sys.executable, '-c', LOAD % then], capture_output=True, text=True,
                          timeout=120, check=True)
    # pygame prints a notice of its own as it is imported
    return done.stdout.splitlines()[-2:]


def test_the_providers_a_context_loads_do_not_import_pygame():
    imported, providers = loaded()
    assert imported == 'False'
    assert '_PillowTextProvider' in providers
    assert '_PyGameFontProvider' not in providers


def test_the_providers_a_context_loads_do_not_import_gluts():
    _imported, providers = loaded()
    assert '_GLUTFontProvider' not in providers


def test_a_program_that_imports_the_glut_provider_has_it():
    _imported, providers = loaded('from OpenGLContext.scenegraph.text import glutfont')
    assert '_GLUTFontProvider' in providers


def test_the_texture_provider_is_the_first_asked():
    from OpenGLContext.scenegraph.text import fontprovider, pillowfont
    assert fontprovider.FontProvider.PROVIDER_SEARCH_ORDER[0] == pillowfont.PillowTextProvider.format


def test_a_program_that_imports_the_pygame_provider_has_it():
    import pytest
    pytest.importorskip('pygame')
    imported, providers = loaded('from OpenGLContext.scenegraph.text import pygamefont')
    assert imported == 'True'
    assert '_PyGameFontProvider' in providers
