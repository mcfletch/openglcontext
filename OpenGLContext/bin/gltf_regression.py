#! /usr/bin/env python
"""Render every glTF demo and diff it against a verified baseline (``oglc-gltf-regression``).

The conformance work was verified by hand: capture a demo, eyeball it against the
Khronos reference, move on. Nothing stored a baseline, so nothing caught a
*regression* when the next shader or loader change landed. This command closes
that loop.

For every scene in the shared roster (`OpenGLContext.loaders.gltf_demos`) and each
of its viewpoints it:

1. renders the model through the ``oglc-gltf`` viewer in its own hidden GL context
   (one process per view -- the robust way to render a batch),
2. compares the new render against **our reference** -- the verified baseline in
   ``tests/reference_images`` submodule -- and flags a regression when they
   diverge beyond tolerance,
3. fetches (and disk-caches) the **upstream Khronos reference** screenshot as a
   tertiary sanity check, and
4. writes an HTML report with *our-reference | new | diff | upstream* side by
   side, click-to-zoom, and an expand-all control. The report links the on-disk
   renders by path (it is not self-contained), keeping it small.

    oglc-gltf-regression --bless        # establish/refresh baselines (after review)
    oglc-gltf-regression                # exit non-zero if anything regressed
    oglc-gltf-regression --only MetalRoughSpheres --only Duck

Downloaded ``.glb`` files and reference screenshots are cached under the shared
glTF cache, so reruns only re-render.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from typing import Any, cast

from OpenGLContext import renderoptions
from OpenGLContext.loaders import gltf
from OpenGLContext.loaders import resolver
from OpenGLContext.loaders import gltf_demos

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))          # this package's parent dir


def _source_root() -> str | None:
    """Locate the openglcontext source checkout (dir with OpenGLContext/ + tests/).

    Searched from the current directory upward, then this file's location. When
    the package is pip-installed into a virtualenv, ``__file__`` points at
    ``site-packages`` -- deriving output paths from it drops the report inside the
    venv. The working tree is what we want, so prefer it.
    """
    def markers(d: str) -> bool:
        return (os.path.isdir(os.path.join(d, 'tests')) and
                os.path.isfile(os.path.join(d, 'OpenGLContext', '__init__.py')))

    for start in (os.getcwd(), REPO):
        d = start
        while True:
            for cand in (d, os.path.join(d, 'openglcontext')):
                if markers(cand):
                    return cand
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return None


def default_report_path() -> str:
    """Default report location: a subdirectory of the source tree's tests/."""
    root = _source_root() or REPO
    return os.path.join(root, 'tests', 'gltf_regression', 'gltf_regression_report.html')

# Render/capture defaults. Six frames + a short settle is the combination the
# conformance-capture harness proved reliable for back-to-back hidden captures.
DEFAULT_SIZE = (900, 640)
# Canonical capture params -- both the baseline bless and the conformance test
# render with these, so a re-render matches its baseline (a mismatch in frame count
# / settle delay shifts settle-sensitive scenes -- Parthenon, heavy/animated models
# -- past tolerance). Keep bless and test on the SAME values.
DEFAULT_FRAMES = 8
DEFAULT_DELAY = 0.5
# Regression tolerance: percent of pixels allowed to differ by more than
# DIFF_THRESHOLD per channel (the project's documented visual-regression default).
DEFAULT_TOLERANCE = 2.0
DIFF_THRESHOLD = 8


def default_baseline_root() -> str:
    """Where verified 'our reference' baselines live.

    ``tests/reference_images`` is a submodule of this repository holding every
    image a regression test compares against, so a clone taken with
    ``--recurse-submodules`` can run them; the glTF baselines are its
    ``gltf_baseline`` folder. ``OPENGLCONTEXT_GLTF_BASELINE`` points somewhere
    else, for a working copy kept outside the checkout.
    """
    env = os.environ.get('OPENGLCONTEXT_GLTF_BASELINE', '').strip()
    if env:
        return env
    return os.path.join(REPO, 'tests', 'reference_images', 'gltf_baseline')


def _env_prefix(name: str = 'pimbackground_') -> str | None:
    """Path prefix of a bundled environment cubemap face set, or None.

    ``pimbackground_`` is the default outdoor set; ``studio_`` is the neutral
    studio set the Khronos material references use (bright grey backdrop +
    softboxes) for metals/glass/anisotropy.
    """
    import OpenGLContext
    prefix = os.path.join(os.path.dirname(OpenGLContext.__file__),
                          'resources', 'environment', name)
    return prefix if os.path.exists(prefix + 'UP.jpg') else None


def _env_prefix_for(spec: gltf_demos.SceneSpec) -> str | None:
    """The env-cubemap prefix a scene should reflect, honouring ``spec.environment``."""
    env = getattr(spec, 'environment', None)
    if env == 'studio':
        return _env_prefix('studio_') or _env_prefix()
    if env == 'studiobright':   # near-white studio for showcase metals/glass
        return _env_prefix('studiobright_') or _env_prefix('studio_') or _env_prefix()
    return _env_prefix()


# The procedural studio cube is smooth and low-detail, so even a mirror metal
# reflects it softly -- unlike the Khronos references, which are shot against a
# real HDR studio. Map the studio keywords to a CC0 Poly Haven HDR panorama the
# viewer loads as both the IBL probe and the skybox, so metals get sharp, detailed
# reflections. Non-keyword ``environment`` values are treated as an explicit HDR
# (a Poly Haven catalogue name or an .hdr URL/path) and passed straight through.
_STUDIO_HDR = 'brown_photostudio_02'
_PROCEDURAL_ENVS = (None, 'studio', 'studiobright')


def _environment_for(spec: gltf_demos.SceneSpec) -> tuple[Any, str]:
    """Return ``(--environment value, --ibl-intensity)`` for a cube-background scene.

    ``'studio'``/``'studiobright'`` resolve to the HDR studio panorama; ``None``
    keeps the bundled procedural outdoor cube; any other value is an explicit HDR
    source (catalogue name or URL) reflected and drawn as the skybox.
    """
    env = getattr(spec, 'environment', None)
    if env in ('studio', 'studiobright'):
        return _STUDIO_HDR, '1.0'
    if env == 'procedural_studio':
        # The bundled neutral-grey procedural studio (dim, even). For a *subtle*
        # effect whose colour a bright HDR would tonemap to white -- dielectric
        # thin-film iridescence -- against which the pale tint actually reads, as
        # in the Khronos neutral-grey reference.
        return (_env_prefix('studio_') or _env_prefix()), '0.7'
    if env is None:
        return _env_prefix_for(spec), '0.9'
    return env, '1.0'


# --------------------------------------------------------------------------- #
# Model resolution (cached): local path the viewer can load.
# --------------------------------------------------------------------------- #
_MIRROR_DIR = os.path.join(resolver._default_cache_dir(), 'gltf_mirror')


def _cached_url_path(url: str, cache_dir: str) -> str:
    """Fetch ``url`` into the sha1-keyed cache and return its local path."""
    resolver._fetch_url(url, cache_dir)
    key = hashlib.sha1(url.encode('utf-8')).hexdigest() + os.path.splitext(url)[1]
    return os.path.join(cache_dir, key)


def _dl(url: str, dst: str) -> None:
    """Download ``url`` to ``dst`` (once), preserving the on-disk layout so a
    ``.gltf``'s relative buffer/image URIs resolve when the viewer loads it."""
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with urllib.request.urlopen(resolver.safe_url(url), timeout=60) as r, \
            open(dst, 'wb') as f:
        f.write(r.read())


def resolve_model(spec: gltf_demos.SceneSpec, parthenon: str | None = None) -> str | None:
    """Return a local, loadable path for a scene's model (or None if unavailable).

    Khronos samples resolve to the cached ``.glb``; a sample published only as
    ``.gltf`` (EnvironmentTest, IridescenceMetallicSpheres, TextureTransformTest)
    is mirrored -- the ``.gltf`` plus its external buffers/images -- into the
    cache so the viewer can load it. A local ``source`` (Parthenon) is used
    as-is, and a scene named by URL is fetched into the cache.
    """
    source, is_local = gltf_demos.resolve_source(spec, parthenon)
    if is_local:
        return source if source and os.path.exists(source) else None
    cache_dir = resolver._default_cache_dir()
    if resolver.is_url(source):
        # One published file, so a failed fetch is the end of it: the .gltf
        # mirror below only makes sense for the catalogue's directory layout.
        try:
            return _cached_url_path(cast(str, source), cache_dir)
        except Exception as err:
            print('  resolve FAILED %s: %s' % (spec.name, err))
            return None

    name = cast(str, source)          # a non-local scene resolves to a sample name
    glb_url = gltf.sample_model_url(name)
    try:
        return _cached_url_path(glb_url, cache_dir)
    except Exception:
        pass
    # Fall back to the external .gltf: mirror it plus its referenced URIs.
    base = '%s/%s' % (gltf.SAMPLE_MODELS_BASE, name)
    gdir = os.path.join(_MIRROR_DIR, name)
    local_gltf = os.path.join(gdir, '%s.gltf' % name)
    try:
        _dl('%s/glTF/%s.gltf' % (base, name), local_gltf)
        doc = json.load(open(local_gltf))
        for coll in ('buffers', 'images'):
            for item in doc.get(coll, []):
                uri = item.get('uri')
                if not uri or uri.startswith('data:'):
                    continue
                rel = urllib.parse.unquote(uri)
                _dl('%s/glTF/%s' % (base, uri), os.path.join(gdir, rel))
        return local_gltf
    except Exception as err:
        print('  resolve FAILED %s: %s' % (name, err))
        return None


# --------------------------------------------------------------------------- #
# Render one view through the viewer CLI (its own hidden GL context).
# --------------------------------------------------------------------------- #
def render_view(spec: gltf_demos.SceneSpec, camera: int | None, model: str, out: str,
                size: tuple[int, int], frames: int, delay: float,
                env_prefix: str | None) -> tuple[bool, dict[str, Any]]:
    """Render one scene/camera to ``out``. Returns ``(ok, stats)`` where ``stats``
    holds the viewer-reported ``load_seconds``/``fps`` for the run (empty on failure)."""
    w, h = size
    common = ['--no-physics', '--no-shadows', '--capture', out,
              '--frames', str(frames), '--capture-delay', repr(delay),
              '--size', '%dx%d' % (w, h), '--background', spec.capture_background]
    if camera is None:
        args = [model, '--no-cameras', '--no-rotate',
                '--yaw', repr(spec.yaw), '--elevation', repr(spec.elevation),
                '--tilt', repr(spec.tilt), '--margin', repr(spec.margin)] + common
        if spec.eye is not None and spec.look_at is not None:
            # ``=`` form so a negative coordinate isn't parsed as another option.
            args += ['--eye=%s' % ','.join(repr(v) for v in spec.eye),
                     '--look-at=%s' % ','.join(repr(v) for v in spec.look_at)]
    else:
        # Baked camera: adopt the authored pose, don't re-frame or spin.
        args = [model, '--camera', str(camera), '--no-rotate'] + common
    if spec.capture_background == 'cube':
        env_arg, ibl = _environment_for(spec)
        if env_arg:
            args += ['--environment', env_arg, '--ibl-intensity', ibl]
    # Pin animated models to a fixed time so the captured pose is reproducible
    # (otherwise the frame lands at whatever animation time the settle reached).
    if spec.anim_time is not None:
        args += ['--anim-time', repr(float(spec.anim_time))]

    # Started from a *clean* rendering environment rather than from whatever
    # this process happens to be carrying: a baseline comparison whose result
    # depends on which variables were set before it is not a baseline.  See
    # `renderoptions.clean_environment`.
    env = renderoptions.clean_environment(
        OPENGLCONTEXT_HIDDEN='1', OPENGLCONTEXT_NO_VSYNC='1',
        OPENGLCONTEXT_PROFILE='core', OPENGLCONTEXT_BACKEND='glfw',
        OPENGLCONTEXT_SHADOW_CASCADES='3',
        OPENGLCONTEXT_BLOOM='1' if getattr(spec, 'bloom', False) else '0',
        OPENGLCONTEXT_DISABLE_FPS_DISPLAY='1')
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'OpenGLContext.bin.view'] + args,
            timeout=120, capture_output=True, text=True,
            cwd=_source_root() or REPO, env=env)
    except subprocess.TimeoutExpired:
        print('  render TIMEOUT')
        return False, {}
    stats = _parse_capture_stats(proc.stdout)
    return os.path.exists(out), stats


def _parse_capture_stats(stdout: str | None) -> dict[str, Any]:
    """Pull ``load_seconds``/``fps`` from the viewer's ``CAPTURE_STATS`` line."""
    stats: dict[str, Any] = {}
    for line in (stdout or '').splitlines():
        if line.startswith('CAPTURE_STATS'):
            for tok in line.split()[1:]:
                key, _, val = tok.partition('=')
                try:
                    stats[key] = float(val) if val not in ('', 'None') else None
                except ValueError:
                    stats[key] = val or None
    return stats


# --------------------------------------------------------------------------- #
# Compare new render vs baseline.
# --------------------------------------------------------------------------- #
def compare(baseline_path: str, new_path: str, diff_out: str,
            threshold: int) -> tuple[Any, dict[str, Any]]:
    """Compare two PNGs. Returns (ComparisonResult, stats_dict) or (None, None)."""
    import numpy as np
    from PIL import Image
    from OpenGLContext.testing.framebuffer_comparison import ComparisonResult

    base = np.asarray(Image.open(baseline_path).convert('RGB'))
    new = np.asarray(Image.open(new_path).convert('RGB'))
    result = ComparisonResult(base, new, threshold)
    if result.diff_image is not None:
        Image.fromarray(result.diff_image, 'RGB').save(diff_out)
    stats = {
        'shapes_match': 'Yes' if result.shapes_match else 'No',
        'max_diff': result.max_diff,
        'mean_diff': result.mean_diff,
        'percent_different': result.percent_different,
        'pixels_different': result.pixels_different,
        'total_pixels': result.total_pixels,
    }
    return result, stats


def is_regression(result: Any, tolerance: float) -> bool:
    """A regression is a shape change or more than ``tolerance`` percent of pixels
    differing beyond the per-channel threshold."""
    if not result.shapes_match:
        return True
    return result.percent_different > tolerance


# --------------------------------------------------------------------------- #
# Driver.
# --------------------------------------------------------------------------- #
def select_scenes(only: list[str] | None) -> list[gltf_demos.SceneSpec]:
    """The scenes to run: all, or the subset named in ``only`` (case-sensitive)."""
    if not only:
        return list(gltf_demos.iter_scenes())
    wanted = set(only)
    return [s for s in gltf_demos.iter_scenes() if s.name in wanted]


#: Asked in a subprocess, because it opens a window and this command is about
#: to open its own.
_PROVENANCE_PROGRAM = """\
from OpenGLContext.testing.glcontext import hidden_window
from OpenGL.GL import glGetString, GL_RENDERER, GL_VERSION

with hidden_window('provenance', size=(8, 8), profile='core'):
    print((glGetString(GL_RENDERER) or b'').decode())
    print((glGetString(GL_VERSION) or b'').decode())
"""


def _gl_renderer() -> dict[str, str]:
    """The GPU's GL_RENDERER/GL_VERSION, queried in a throwaway hidden context.

    The context asks for the same core profile ``render_view`` pins, because a
    driver that names the profile in GL_VERSION would otherwise stamp every
    baseline with one the renders were never made in.
    """
    try:
        out = subprocess.run(
            [sys.executable, '-c', _PROVENANCE_PROGRAM],
            capture_output=True, text=True, timeout=30,
            env=dict(os.environ, OPENGLCONTEXT_HIDDEN='1', OPENGLCONTEXT_BACKEND='glfw'),
        ).stdout.splitlines()
        return {'gl_renderer': (out[0].strip() if out else '') or 'unknown',
                'gl_version': out[1].strip() if len(out) > 1 else ''}
    except Exception:
        return {'gl_renderer': 'unknown', 'gl_version': ''}


def _provenance() -> dict[str, str]:
    """Git hash (+``-dirty``), timestamp and GPU identity, stamped into every
    render's metadata so a baseline records exactly how (and on what) it was made."""
    import datetime
    root = _source_root() or REPO
    git = 'unknown'
    try:
        rev = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=root,
                             capture_output=True, text=True)
        dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=root,
                               capture_output=True, text=True)
        if rev.returncode == 0 and rev.stdout.strip():
            git = rev.stdout.strip() + ('-dirty' if dirty.stdout.strip() else '')
    except Exception:
        pass
    prov = {'git': git,
            'rendered_at': datetime.datetime.now().isoformat(timespec='seconds')}
    prov.update(_gl_renderer())
    return prov


def _view_metadata(spec: gltf_demos.SceneSpec, camera: int | None, url: str | None,
                   args: argparse.Namespace, provenance: dict[str, str],
                   stats: dict[str, Any] | None = None) -> dict[str, Any]:
    """The per-view render metadata recorded to a sidecar JSON and shown in the
    report: what was rendered, how it was framed/lit, and the run provenance.

    ``url`` is the ORIGINAL source the viewer loaded -- the remote http(s) URL for a
    Khronos sample (loaded as an untrusted resource through the resolver), not a
    local cache path -- so the record reflects the real load context. ``stats``
    carries the viewer-reported load time / fps for this render."""
    env_arg = ibl = None
    if spec.capture_background == 'cube':
        env_arg, ibl = _environment_for(spec)
    stats = stats or {}
    return {
        'scene': spec.name,
        'slug': spec.slug(camera),
        'camera': camera,
        'url': url,
        'load_context': 'url' if isinstance(url, str) and url.startswith(('http://', 'https://')) else 'local',
        'load_seconds': stats.get('load_seconds'),
        'fps': stats.get('fps'),
        'background': spec.capture_background,
        'environment': env_arg,
        'ibl_intensity': ibl,
        'framing': ({'eye': list(spec.eye), 'look_at': list(spec.look_at)}
                    if spec.eye is not None and spec.look_at is not None
                    else {'yaw': spec.yaw, 'elevation': spec.elevation,
                          'tilt': spec.tilt, 'margin': spec.margin}),
        'anim_time': spec.anim_time,
        'frames': args.frames,
        'delay': args.delay,
        'size': list(args.size),
        'git': provenance['git'],
        'rendered_at': provenance['rendered_at'],
        'gl_renderer': provenance['gl_renderer'],
        'gl_version': provenance['gl_version'],
    }


def default_out_dir() -> str:
    """Persistent directory of the latest per-view renders/metadata/diffs. Kept
    across runs so re-rendering one scene (``--only``) leaves the others intact;
    the report is assembled from whatever it holds."""
    return os.path.join(os.path.dirname(default_report_path()), 'renders')


def resolve_model_url(spec: gltf_demos.SceneSpec,
                      parthenon: str | None = None) -> tuple[str | None, bool]:
    """The source the viewer should load, and whether it is a URL.

    A Khronos sample resolves to its **http(s) URL** so the viewer loads it through
    the security-hardened resolver -- an untrusted remote resource, exactly as an
    end user would -- rather than as a trusted local file. The ``.glb`` variant is
    used when it exists (probed via the shared cache), else the multi-file ``.gltf``
    URL, whose external buffers/images the resolver fetches same-origin. A scene
    that names its own URL is handed over as it stands, and the local Parthenon
    build stays a path. Returns ``(source, is_url)`` or ``(None, False)``.
    """
    source, is_local = gltf_demos.resolve_source(spec, parthenon)
    if is_local:
        return (source if source and os.path.exists(source) else None), False
    if resolver.is_url(source):
        return source, True
    name = cast(str, source)          # a non-local scene resolves to a sample name
    glb_url = gltf.sample_model_url(name)
    try:
        _cached_url_path(glb_url, resolver._default_cache_dir())   # confirm it exists
        return glb_url, True
    except Exception:
        return '%s/%s/glTF/%s.gltf' % (gltf.SAMPLE_MODELS_BASE, name, name), True


def render_scenes(scenes: list[gltf_demos.SceneSpec], out_dir: str, baseline_root: str,
                  parthenon: str | None, args: argparse.Namespace,
                  provenance: dict[str, str]) -> None:
    """Render each selected view to ``out_dir`` (``<slug>.png`` + ``<slug>.json``),
    blessing to ``baseline_root`` when asked. Overwrites only the rendered views, so
    prior renders of other scenes survive for the report."""
    import shutil
    bless_names = None if args.bless in (None, []) else set(args.bless)
    bless_all = args.bless == []
    os.makedirs(out_dir, exist_ok=True)
    if args.bless is not None:
        os.makedirs(baseline_root, exist_ok=True)
    for spec in scenes:
        url, _is_url = resolve_model_url(spec, parthenon)
        for camera in spec.camera_ids():
            slug = spec.slug(camera)
            new_path = os.path.join(out_dir, slug + '.png')
            if url is None:
                print('  ERROR %s (model unavailable)' % slug)
                continue
            ok, stats = render_view(spec, camera, url, new_path, args.size,
                                    args.frames, args.delay, None)
            if not ok:
                print('  FAIL  %s (render failed)' % slug)
                continue
            metadata = _view_metadata(spec, camera, url, args, provenance, stats)
            do_bless = bless_all or (bless_names and spec.name in bless_names)
            try:
                with open(os.path.join(out_dir, slug + '.json'), 'w') as fh:
                    json.dump(metadata, fh, indent=2)
                if do_bless:
                    shutil.copyfile(new_path, os.path.join(baseline_root, slug + '.png'))
                    with open(os.path.join(baseline_root, slug + '.json'), 'w') as fh:
                        json.dump(metadata, fh, indent=2)
            except OSError:
                pass
            print('  %-5s %s' % ('BLESS' if do_bless else 'OK', slug))


def build_report(out_dir: str, baseline_root: str, report_path: str, tolerance: float,
                 diff_threshold: int) -> int:
    """Assemble the HTML report from whatever renders are present in ``out_dir``
    (each ``<slug>.json`` + ``<slug>.png``), diffed against the baseline. Decoupled
    from rendering, so re-rendering one scene then rebuilding keeps every other row.
    Returns the regression count."""
    import shutil
    from OpenGLContext.testing.report_generator import TestReportGenerator
    gen = TestReportGenerator(title='glTF Demo Regression -- our reference vs new')
    report_dir = os.path.dirname(os.path.abspath(report_path))

    def stage(src: str | None, name: str) -> str | None:
        """Return an image for the report to link, guaranteeing it lives under the
        report directory. The result and diff already do; the baseline and Khronos
        upstream live in other trees, so copy those in under ``name`` -- then the
        report (which links images relative to itself) copies elsewhere as one
        self-contained bundle. Missing sources return None."""
        if not (src and os.path.exists(src)):
            return None
        if os.path.abspath(src).startswith(report_dir + os.sep):
            return src
        dst = os.path.join(out_dir, name)
        try:
            shutil.copyfile(src, dst)
            return dst
        except OSError:
            return src

    regressions = 0
    slugs = sorted(f[:-5] for f in os.listdir(out_dir) if f.endswith('.json'))
    for slug in slugs:
        try:
            meta = json.load(open(os.path.join(out_dir, slug + '.json')))
        except Exception:
            meta = {}
        scene = meta.get('scene', slug.split('__')[0])
        new_path = os.path.join(out_dir, slug + '.png')
        baseline_path = os.path.join(baseline_root, slug + '.png')
        diff_path = os.path.join(out_dir, slug + '_diff.png')
        upstream_path = None
        try:
            upstream_path = gltf.cache_reference_screenshot(scene)
        except Exception:
            pass
        status, stats, stderr = 'pass', None, ''
        if not os.path.exists(new_path):
            status, stderr = 'error', 'no render on disk'
        elif not os.path.exists(baseline_path):
            status, stderr = 'skip', 'no baseline -- bless after reviewing'
        else:
            result, stats = compare(baseline_path, new_path, diff_path, diff_threshold)
            if is_regression(result, tolerance):
                status, regressions = 'fail', regressions + 1
                stderr = 'REGRESSION: %s' % result
            else:
                stderr = str(result)
        gen.add_test({
            'test_name': '%s -- %s' % (slug, meta.get('description', '')),
            'status': status,
            'reference_image': stage(baseline_path, slug + '_baseline.png'),
            'result_image': new_path if os.path.exists(new_path) else None,
            'diff_image': diff_path if (stats and os.path.exists(diff_path)) else None,
            'upstream_image': stage(upstream_path, slug + '_upstream.png'),
            'comparison_stats': stats,
            'metadata': meta,
            'stderr': stderr,
            'duration': 0.0,
        })
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    # Link the renders rather than base64-embedding them: a run covers dozens of
    # views x four images, and embedding balloons the single HTML to hundreds of
    # MB. save() links each image relative to the report; with every image staged
    # under out_dir, the report plus its render directory copy elsewhere as one
    # self-contained bundle (as tests/report.html links its images).
    gen.save(report_path, embed_images=False)
    return regressions


def run(args: argparse.Namespace) -> int:
    baseline_root = args.baseline_root or default_baseline_root()
    out_dir = args.out_dir or default_out_dir()
    os.makedirs(out_dir, exist_ok=True)
    parthenon = args.parthenon or gltf_demos.find_parthenon()
    report = args.report or default_report_path()

    if not getattr(args, 'report_only', False):
        provenance = _provenance()
        print('Baselines: %s' % baseline_root)
        print('Renders:   %s' % out_dir)
        print('Provenance: git %s, %s, %s' % (
            provenance['git'], provenance['rendered_at'], provenance['gl_renderer']))
        render_scenes(select_scenes(args.only), out_dir, baseline_root,
                      parthenon, args, provenance)

    regressions = build_report(out_dir, baseline_root, report,
                               args.tolerance, args.diff_threshold)
    print('\nReport: %s' % report)
    if regressions:
        print('%d regression(s) detected.' % regressions)
    return 1 if regressions else 0


def _parse_size(text: str) -> tuple[int, int]:
    w, _, h = text.lower().partition('x')
    return (int(w), int(h))


def build_parser(prog: str = 'oglc-gltf-regression') -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--bless', nargs='*', metavar='NAME', default=None,
                   help='promote the new renders to baselines (after review). With '
                        'no NAME, blesses every scene run this pass; otherwise only '
                        'the named scenes.')
    p.add_argument('--only', action='append', metavar='NAME',
                   help='render only this scene (repeatable)')
    p.add_argument('--baseline-root', metavar='DIR',
                   help='baseline directory (default: '
                        'tests/reference_images/gltf_baseline or '
                        '$OPENGLCONTEXT_GLTF_BASELINE)')
    p.add_argument('--parthenon', metavar='GLB',
                   help='path to a local Parthenon .glb (default: auto-detect sibling)')
    p.add_argument('--report', metavar='HTML', help='report output path')
    p.add_argument('--out-dir', metavar='DIR',
                   help='persistent directory of per-view renders/metadata/diffs '
                        '(default: tests/gltf_regression/renders)')
    p.add_argument('--report-only', action='store_true',
                   help='rebuild the report from the existing renders directory '
                        'without rendering anything')
    p.add_argument('--size', type=_parse_size, default=DEFAULT_SIZE, metavar='WxH',
                   help='render size (default %dx%d)' % DEFAULT_SIZE)
    p.add_argument('--frames', type=int, default=DEFAULT_FRAMES,
                   help='frames to render before capture (default %d)' % DEFAULT_FRAMES)
    p.add_argument('--delay', type=float, default=DEFAULT_DELAY,
                   help='settle seconds before capture (default %.2f)' % DEFAULT_DELAY)
    p.add_argument('--tolerance', type=float, default=DEFAULT_TOLERANCE, metavar='PCT',
                   help='percent of pixels allowed to differ (default %.1f)' % DEFAULT_TOLERANCE)
    p.add_argument('--diff-threshold', type=int, default=DIFF_THRESHOLD, metavar='N',
                   help='per-channel delta a pixel must exceed to count as different '
                        '(default %d)' % DIFF_THRESHOLD)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == '__main__':  # pragma: no cover - CLI entry point
    sys.exit(main())
