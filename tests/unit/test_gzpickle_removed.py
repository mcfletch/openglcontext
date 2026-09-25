"""Regression: the pickle-based scene loader is removed (no GL).

`loaders/gzpickle.py` did `pickle.load` on `.pkl`/`.pkl.gz` scene data -- arbitrary
code execution if ever pointed at untrusted input -- and `loaders/vrml2pklgz.py`
was its only user (a standalone converter that *wrote* such files). Neither was
registered as a loader for any extension. Both are deleted; these tests pin that
the modules are gone and that nothing re-exposes a pickle-loading code path.
"""
import importlib

import pytest


def test_gzpickle_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('OpenGLContext.loaders.gzpickle')


def test_vrml2pklgz_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('OpenGLContext.loaders.vrml2pklgz')


def test_the_loaders_still_load_and_none_takes_a_pickle():
    from OpenGLContext.loaders.loader import Loader
    from OpenGLContext.loaders.obj import OBJHandler

    assert isinstance(Loader.findHandler('scene.obj'), OBJHandler)
    assert Loader.findHandler('scene.wrl') is not None
    assert Loader.findHandler('scene.pkl') is None
    assert Loader.findHandler('scene.pkl.gz') is None
