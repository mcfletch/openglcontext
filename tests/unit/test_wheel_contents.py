"""What the wheel carries of the files the engine opens by path at run time.

A source checkout has every file in the package directory; a wheel has the ones
``[tool.setuptools.package-data]`` names. A shader whose extension is not named
is present in every test run and absent from every install.
"""
import fnmatch
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'OpenGLContext'
SHADERS = sorted(path.name for path in (PACKAGE / 'shaders').iterdir() if path.is_file())


def package_data():
    with (ROOT / 'pyproject.toml').open('rb') as handle:
        return tomllib.load(handle)['tool']['setuptools']['package-data']['OpenGLContext']


@pytest.mark.parametrize('name', SHADERS)
def test_every_shader_file_is_in_the_wheel(name):
    relative = f'shaders/{name}'
    assert any(fnmatch.fnmatch(relative, pattern) for pattern in package_data()), (
        f'{relative} is opened at run time and no package-data pattern names it')


def test_the_shaders_directory_holds_shaders():
    """The parametrised cases above are no check at all if the directory is found empty."""
    assert len(SHADERS) > 20
