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
import json
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

# Scenes whose frame legitimately differs between drivers by more than the
# general tolerance, and what each is held to instead. Keyed by SceneSpec.name
# -> (percent, reason). The frame is still compared: what these buy is room for
# a difference the GL specification leaves to the implementation, not room for
# a wrong render, which differs across far more of the frame than any figure
# here.
TOLERANCES = {
    'CommercialRefrigerator': (
        5.0,
        'roughness-blurred transmission reads a nine-level mip chain of the '
        'backdrop, and glGenerateMipmap of a non-power-of-two frame is '
        'implementation-defined -- 900x640 halves to an odd 225 at level two '
        'and each driver chooses what to do with the odd column. The '
        'difference is confined to what is seen through the frosted door, and '
        'compounds with the mip level the shader reaches at high roughness. '
        'Generating the chain ourselves would settle it and is the durable fix.'
    ),
    'GlassBrokenWindow': (
        5.0,
        'the same transmission mip chain, seen through the cracked pane. Every '
        'pixel outside the glass is identical between an NVIDIA RTX 3060 Ti '
        '(which blessed the baseline) and an Intel UHD 630, and inside it 4% '
        'differ by a mean of 1.75/255 -- the fracture lines, where the '
        'roughness is highest and the shader reaches furthest up the chain. '
        'The durable fix is the one named above, and settles both.'
    ),
}


def _tolerance_for(spec):
    """How much of this scene's frame may differ from its baseline."""
    entry = TOLERANCES.get(spec.name)
    return entry[0] if entry else R.DEFAULT_TOLERANCE

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


def _recorded(spec, camera):
    """What the sidecar says this baseline was rendered with, or ``{}``.

    ``oglc-gltf-regression --bless`` writes one JSON file beside each image
    holding the parameters of the render and the driver that made it.
    """
    path = os.path.splitext(_baseline_path(spec, camera))[0] + '.json'
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def stale_reason(spec, camera, recorded):
    """Why this baseline is not a picture of this view, or ``None``.

    A baseline is a picture of one scene under one set of parameters.  Change
    the parameters -- pin an animation to a different second, move the camera,
    reframe -- and the committed image is a picture of a view that no longer
    exists, so the comparison against it is not a regression gate but a
    guaranteed failure whose message says only that pixels differ.

    Reading the parameters back out of the sidecar turns that into what it is:
    a baseline that needs re-blessing, named as such, and caught without
    rendering anything.
    """
    problems = []
    if recorded.get('anim_time') != spec.anim_time:
        problems.append('the animation was pinned at %r and the roster now asks '
                        'for %r' % (recorded.get('anim_time'), spec.anim_time))
    framing = recorded.get('framing') or {}
    # A scene with an explicit eye/look_at is framed by those instead, and the
    # sidecar records them under their own keys.
    if spec.eye is None or spec.look_at is None:
        for key, wanted in (('yaw', spec.yaw), ('elevation', spec.elevation),
                            ('tilt', spec.tilt), ('margin', spec.margin)):
            if key in framing and float(framing[key]) != float(wanted):
                problems.append('%s was %r and the roster now asks for %r'
                                % (key, framing[key], wanted))
    size = tuple(recorded.get('size') or ())
    if size and size != tuple(R.DEFAULT_SIZE):
        problems.append('it was rendered at %dx%d and the suite renders at %dx%d'
                        % (size + tuple(R.DEFAULT_SIZE)))
    return '; '.join(problems) or None


@pytest.mark.parametrize("spec,camera", _VIEWS, ids=_IDS)
def test_view_has_baseline_or_is_waived(spec, camera):
    """Every roster view is either baselined or explicitly waived (no GL needed)."""
    if spec.name in WAIVERS:
        pytest.xfail("waived (feature unsupported): %s" % WAIVERS[spec.name])
    baseline = _baseline_path(spec, camera)
    assert os.path.exists(baseline), (
        "no baseline for %s -- render it, review against the Khronos reference, "
        "then: oglc-gltf-regression --bless --only %s" % (spec.slug(camera), spec.name))


@pytest.mark.parametrize("spec,camera", _VIEWS, ids=_IDS)
def test_baseline_was_rendered_for_this_view(spec, camera):
    """The committed image is of the view the roster now describes (no GL needed).

    The companion to the test above, and the same kind of anchor: that one
    catches a view with no baseline, this one catches a baseline whose view has
    moved out from under it.
    """
    if spec.name in WAIVERS:
        pytest.xfail("waived (feature unsupported): %s" % WAIVERS[spec.name])
    recorded = _recorded(spec, camera)
    if not recorded:
        pytest.skip('no sidecar beside this baseline to read')
    reason = stale_reason(spec, camera, recorded)
    assert reason is None, (
        "the %s baseline is of a different view: %s. Re-render it, review "
        "against the Khronos reference, then: oglc-gltf-regression --bless "
        "--only %s" % (spec.slug(camera), reason, spec.name))


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
    # Before rendering rather than after: comparing a frame against a baseline
    # of another view can only fail, and two minutes of rendering buys a
    # pixel count in place of the reason.
    reason = stale_reason(spec, camera, _recorded(spec, camera))
    if reason is not None:
        pytest.fail("the %s baseline is of a different view: %s. Re-bless it "
                    "(oglc-gltf-regression --bless --only %s)"
                    % (slug, reason, spec.name))

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
    assert not R.is_regression(result, _tolerance_for(spec)), (
        "%s regressed vs baseline: %s" % (slug, result))
