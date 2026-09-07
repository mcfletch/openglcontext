"""The demos' packaging: the commands it names as strings still resolve.

A frozen bundle and a Debian package each declare their command as text -- a
``module:attribute`` in `entry.py`, a `[project.scripts]` line in the deb
project -- so a renamed module or a renamed ``main`` breaks neither a test nor
an import, only a build that nobody runs until a release.  These resolve them.

The builds themselves are not run here: a bundle takes minutes and 130 MB and a
package fetches an interpreter.  What they need from the engine that this suite
*does* hold is in `test_packaging.py`, `test_appdir.py` and `test_deb.py`.

See `OpenGLContext/demos/packaging/README.md`.
"""
import importlib
import os
import runpy
import tomllib

import pytest

import OpenGLContext

PACKAGING = os.path.join(os.path.dirname(OpenGLContext.__file__),
                         'demos', 'packaging')


def commands(directory):
    """The ``{name: 'module:attribute'}`` table an entry script declares"""
    return runpy.run_path(os.path.join(directory, 'entry.py'))['COMMANDS']


def scripts(directory):
    """The ``[project.scripts]`` of the distribution a package is built from"""
    with open(os.path.join(directory, 'deb-project', 'pyproject.toml'), 'rb') as source:
        return tomllib.load(source)['project']['scripts']


def resolve(target):
    """The callable a ``module:attribute`` string names"""
    module, _, attribute = target.partition(':')
    return getattr(importlib.import_module(module), attribute)


class TestTheFrozenBundle:
    def test_every_command_names_something_callable(self):
        for name, target in commands(PACKAGING).items():
            assert callable(resolve(target)), '%s -> %s' % (name, target)

    def test_the_freezer_is_told_about_them(self):
        """They are named as strings, so nothing following imports finds them."""
        declared = runpy.run_path(os.path.join(PACKAGING, 'entry.py'))
        for target in declared['COMMANDS'].values():
            assert target.partition(':')[0] in declared['MODULES']

    def test_the_demo_it_names_is_the_one_that_is_there(self):
        assert 'OpenGLContext.demos.tk_viewer:main' in commands(PACKAGING).values()


class TestTheDebianPackage:
    def test_every_script_names_something_callable(self):
        for name, target in scripts(PACKAGING).items():
            assert callable(resolve(target)), '%s -> %s' % (name, target)

    def test_the_package_and_the_bundle_offer_the_same_commands(self):
        """Two ways of delivering one application, not two applications."""
        assert set(scripts(PACKAGING)) == set(commands(PACKAGING))

    def test_they_run_the_same_thing(self):
        assert scripts(PACKAGING) == commands(PACKAGING)

    def test_the_build_script_keeps_tk_out_of_the_pruning(self):
        """Tk is part of CPython, so a package built without saying so installs
        and then fails to start.  It is one word in a shell script and there is
        no test anywhere else that would notice it going."""
        with open(os.path.join(PACKAGING, 'build-deb.sh')) as script:
            assert '--backend tk' in script.read()


class TestTheProjectIsBuildable:
    def test_the_deb_project_declares_what_it_needs(self):
        with open(os.path.join(PACKAGING, 'deb-project', 'pyproject.toml'),
                  'rb') as source:
            project = tomllib.load(source)['project']
        assert project['name']
        assert 'OpenGLContext' in project['dependencies']

    def test_it_is_metadata_rather_than_a_second_copy_of_the_demo(self):
        """The module belongs to the engine; what this distribution adds is a
        console script for a package to install."""
        assert not [
            name for name in os.listdir(os.path.join(PACKAGING, 'deb-project'))
            if name.endswith('.py')
        ]


@pytest.mark.parametrize('name', ['viewer-demos.spec', 'build-deb.sh',
                                  'entry.py', 'README.md'])
def test_the_packaging_directory_is_whole(name):
    assert os.path.exists(os.path.join(PACKAGING, name))
