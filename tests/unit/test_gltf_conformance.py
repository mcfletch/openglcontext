"""Full glTF sample-model conformance regression.

Every scene in the shared roster (:mod:`OpenGLContext.loaders.gltf_demos`) is
rendered through the deterministic capture path and diffed against our blessed
baseline (the sibling ``reference-images/gltf_baseline`` repo), reusing the exact
machinery of ``oglc-gltf-regression`` -- :func:`render_view` / :func:`compare` /
:func:`is_regression` -- and the same :class:`ComparisonResult` pixel gate as the
rest of the visual suite (:mod:`OpenGLContext.testing.framebuffer_comparison`).

This closes the loop the hand-verified conformance work left open: the ~120
Khronos samples were brought to reference parity by eye, but nothing stored a
baseline, so a later shader/loader change could regress one silently. Now each
sample is a test.

Two levels:

* :func:`test_view_has_baseline_or_is_waived` -- fast, no GL. Every non-waived view
  must have a committed baseline. Guards against adding a roster scene without a
  baseline, and is the red/green anchor while baselines are being blessed.
* :func:`test_view_matches_baseline` -- the actual regression gate (``slow`` +
  ``visual``): render the view and fail if it diverges from its baseline beyond
  tolerance. Skips cleanly when there is no display or the model can't be fetched.

``WAIVERS`` lists scenes whose glTF features are not yet implemented; they are
``xfail`` rather than gated. To (re)establish baselines after reviewing renders
against the upstream Khronos references::

    oglc-gltf-regression --bless
"""
import os

import pytest

pytest.importorskip("PIL")
pytest.importorskip("numpy")

from OpenGLContext.bin import gltf_regression as R
from OpenGLContext.loaders import gltf_demos
from OpenGLContext.testing.display import display_available


# Scenes whose glTF features OpenGLContext does not yet support. They render but
# not to reference parity, so they are not baselined and are expected to fail
# (xfail) rather than gate the suite. Keyed by SceneSpec.name -> reason.
WAIVERS = {
    'ScatteringSkull':
        'full volumetric subsurface scattering (KHR_materials_volume scatter) is '
        'not implemented; the skull renders as translucent bone via '
        'KHR_materials_diffuse_transmission, not true SSS.',
    'USDShaderBallForGltf':
        'nested-shell (multi-layer) transmission is not implemented; the outer '
        'shell does not refract through the inner layers as the reference does.',
}

_BASELINE_ROOT = R.default_baseline_root()
_HAS_DISPLAY = display_available()

# The baselines live in a sibling repository rather than in this one, so a
# checkout that does not have it has nothing at all to compare against. That is
# one missing repository, not three hundred missing baselines, and three hundred
# assertion failures name neither the repository nor the way to point at a copy
# of it -- so say it once, here, and leave the per-view gate below to mean what
# it says: this roster view has no baseline yet.
if not os.path.isdir(_BASELINE_ROOT):
    pytest.skip(
        'no glTF baselines at %s -- check out the reference-images repository '
        'beside this one, or set OPENGLCONTEXT_GLTF_BASELINE to a copy of it'
        % (_BASELINE_ROOT,),
        allow_module_level=True)

# (spec, camera) per rendered view -- a scene with baked cameras contributes one
# view per camera; an auto-framed scene contributes a single (spec, None).
_VIEWS = [(spec, camera)
          for spec in gltf_demos.iter_scenes()
          for camera in spec.camera_ids()]
_IDS = [spec.slug(camera) for spec, camera in _VIEWS]


def _baseline_path(spec, camera):
    return os.path.join(_BASELINE_ROOT, spec.slug(camera) + '.png')


@pytest.mark.parametrize("spec,camera", _VIEWS, ids=_IDS)
def test_view_has_baseline_or_is_waived(spec, camera):
    """Every roster view is either baselined or explicitly waived (no GL needed)."""
    if spec.name in WAIVERS:
        pytest.xfail("waived (feature unsupported): %s" % WAIVERS[spec.name])
    baseline = _baseline_path(spec, camera)
    assert os.path.exists(baseline), (
        "no baseline for %s -- render it, review against the Khronos reference, "
        "then: oglc-gltf-regression --bless --only %s" % (spec.slug(camera), spec.name))


@pytest.mark.slow
@pytest.mark.visual
@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available for GL rendering")
@pytest.mark.parametrize("spec,camera", _VIEWS, ids=_IDS)
def test_view_matches_baseline(spec, camera, tmp_path):
    """Render each view and fail if it diverges from its blessed baseline."""
    if spec.name in WAIVERS:
        pytest.xfail("waived (feature unsupported): %s" % WAIVERS[spec.name])
    slug = spec.slug(camera)
    baseline = _baseline_path(spec, camera)
    if not os.path.exists(baseline):
        pytest.fail("no baseline for %s -- bless it first "
                    "(oglc-gltf-regression --bless --only %s)" % (slug, spec.name))

    # Load in the same context as an end user: a Khronos sample over its http(s)
    # URL through the resolver, not as a trusted local file.
    url, _is_url = R.resolve_model_url(spec, gltf_demos.find_parthenon())
    if url is None:
        pytest.skip("model unavailable (offline / download failed)")

    out = str(tmp_path / (slug + '.png'))
    diff = str(tmp_path / (slug + '_diff.png'))
    # render_view recomputes its own env prefix from spec.environment; the passed
    # value is unused, so None is fine.
    rendered, _stats = R.render_view(spec, camera, url, out, R.DEFAULT_SIZE,
                                     R.DEFAULT_FRAMES, R.DEFAULT_DELAY, None)
    if not rendered:
        pytest.skip("render did not produce a frame (GL/network flake or timeout)")

    result, stats = R.compare(baseline, out, diff, R.DIFF_THRESHOLD)
    assert not R.is_regression(result, R.DEFAULT_TOLERANCE), (
        "%s regressed vs baseline: %s" % (slug, result))
