"""Packaging hygiene: what the distribution must and must not carry.

AI-workflow docs (top-level CLAUDE.md and plans/) stay out of the sdist. The
classifiers advertise the Python versions actually supported, and the Python
floor aligns with the numpy floor (numpy 2.1 dropped 3.9, so >=3.10). Data the
package reads at runtime -- shaders, and the environment cube maps the demo
backgrounds use -- has to be declared as package data, or a pip install has the
modules and none of the files they open.
"""
import tomllib

import pytest

from OpenGLContext.testing.paths import tests_root
ROOT = tests_root(__file__).parent


def _project():
    with open(ROOT / 'pyproject.toml', 'rb') as f:
        return tomllib.load(f)['project']


class TestClassifiersAndPython:
    def test_python_314_classifier_present(self):
        assert any('3.14' in c for c in _project()['classifiers'])

    def test_requires_python_aligned_with_numpy(self):
        # numpy>=2.0 resolves to 2.1+ on new installs, which dropped 3.9
        assert _project()['requires-python'] == '>=3.10'

    def test_no_stale_39_classifier(self):
        assert not any(c.rstrip().endswith(':: 3.9') for c in _project()['classifiers'])


class TestSdistPrunesDevDocs:
    def test_manifest_prunes_plans_and_claude(self):
        manifest = (ROOT / 'MANIFEST.in').read_text()
        assert 'prune plans' in manifest
        assert 'exclude CLAUDE.md' in manifest


def _pyproject():
    with open(ROOT / 'pyproject.toml', 'rb') as f:
        return tomllib.load(f)


class TestBuildSystemAndReadme:
    def test_setuptools_supports_pep639(self):
        # the SPDX `license = "BSD-3-Clause"` string is a PEP 639 expression, only
        # accepted by setuptools >= 77 (61-76 reject it)
        reqs = _pyproject()['build-system']['requires']
        assert any(r.replace(' ', '').startswith('setuptools>=77') for r in reqs)

    def test_readme_is_the_readme_not_the_license(self):
        # The long-description must be the readme, not license.txt
        assert _pyproject()['project']['readme'] == 'README.md'
        assert (ROOT / 'README.md').exists()

    def test_license_file_named_explicitly(self):
        # The lowercase license.txt doesn't match setuptools'
        # case-sensitive default LICEN[CS]E* glob, so it must be listed explicitly
        # or it drops out of the wheel/sdist metadata.
        project = _pyproject()['project']
        assert project.get('license-files') == ['license.txt']
        assert (ROOT / 'license.txt').exists()


class TestRuntimeDataIsDeclaredAsPackageData:
    """Files the package opens by path have to be listed, or they do not ship."""

    def _patterns(self):
        return _pyproject()['tool']['setuptools']['package-data']['OpenGLContext']

    def test_the_shaders_are_declared(self):
        for pattern in ('shaders/*.vert', 'shaders/*.frag', 'shaders/*.glsl'):
            assert pattern in self._patterns()

    def test_the_environment_cubemaps_are_declared(self):
        # bin/gltf_demo.default_env_prefix opens these by path for the `cube`
        # background; undeclared, every install silently takes the None branch.
        assert 'resources/environment/*.jpg' in self._patterns()

    def test_every_declared_pattern_matches_something(self):
        import glob
        package = ROOT / 'OpenGLContext'
        for pattern in self._patterns():
            assert glob.glob(str(package / pattern)), pattern

    def test_the_cubemap_face_sets_are_complete(self):
        # A face set is six faces; five renders a cube with a hole in it.
        d = ROOT / 'OpenGLContext' / 'resources' / 'environment'
        for prefix in ('pimbackground_', 'studio_', 'studiobright_'):
            for face in ('RT', 'LF', 'UP', 'DN', 'FR', 'BK'):
                assert (d / (prefix + face + '.jpg')).exists(), prefix + face


class TestGeneratedArtifactsPruned:
    def test_generated_regression_images_absent(self):
        # Generated diff/result/reference/debug outputs must not be
        # committed; only the canonical {name}.png baseline is kept.
        d = ROOT / 'tests' / 'reference_images'
        for generated in ('teapot_regression_diff.png', 'teapot_regression_result.png',
                          'teapot_regression_reference.png', 'debug_test.png'):
            assert not (d / generated).exists(), generated
        assert (d / 'teapot_regression.png').exists()   # canonical baseline kept

    def test_gitignore_covers_test_outputs(self):
        gi = (ROOT / '.gitignore').read_text()
        for pattern in ('*_diff.png', 'regression_output', '.coverage',
                        '*.sock', 'benchmark_results'):
            assert pattern in gi, pattern


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
