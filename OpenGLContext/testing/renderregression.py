"""What a render regression command needs: provenance, comparison and the report

``oglc-gltf-regression`` and ``oglc-x3d-regression`` each render a roster of
scenes, one process per view, into a directory of ``<slug>.png`` renders with
a ``<slug>.json`` record beside each, and compare them with a baseline
directory of the same layout. This module holds the parts they share:

- :func:`provenance`, the git revision, time and GPU stamped into each record;
- :func:`compare` and :func:`is_regression`, the per-pixel comparison and the
  rule a render fails by;
- :func:`render_failure`, why a drawing process failed, and
  :func:`write_failure`, the record of a render that failed;
- :func:`promote`, the renders a run drew made baselines, after review;
- :func:`build_report`, the HTML report of whatever renders the directory
  holds, with the baseline, the render, the difference and, where the format
  publishes one, an upstream reference side by side, and :func:`exit_status`,
  what a run's command exits with.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Collection
from typing import Any, NamedTuple, Optional

from OpenGLContext import atomicfiles, renderoptions

__all__ = [
    'BACKENDS', 'DEFAULT_TOLERANCE', 'DIFF_THRESHOLD', 'source_root', 'gl_renderer',
    'provenance', 'capture_environment', 'parse_size', 'add_arguments',
    'compare', 'is_regression', 'ReportCounts', 'render_failure', 'write_failure',
    'promote', 'build_report',
    'exit_status',
]

#: Percent of pixels a render may have differing from its baseline by more than
#: DIFF_THRESHOLD in a channel (the project's documented visual-regression default).
DEFAULT_TOLERANCE = 2.0
DIFF_THRESHOLD = 8

#: The directory holding the OpenGLContext package.
PACKAGE_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def source_root() -> Optional[str]:
    """The openglcontext source checkout (a directory with OpenGLContext/ and tests/)

    Searched from the current directory upward, then from this package's
    location. Installed into a virtualenv, the package's own location is
    ``site-packages``, and output derived from it would land inside the venv,
    so the working tree is preferred.
    """
    def markers(candidate: str) -> bool:
        return (os.path.isdir(os.path.join(candidate, 'tests')) and
                os.path.isfile(os.path.join(candidate, 'OpenGLContext', '__init__.py')))

    for start in (os.getcwd(), PACKAGE_PARENT):
        folder = start
        while True:
            for candidate in (folder, os.path.join(folder, 'openglcontext')):
                if markers(candidate):
                    return candidate
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
    return None


#: Run in a subprocess, because it opens a window and the command is about to
#: open its own.
_PROVENANCE_PROGRAM = """\
from OpenGLContext.testing.glcontext import hidden_window
from OpenGL.GL import glGetString, GL_RENDERER, GL_VERSION

with hidden_window('provenance', size=(8, 8), profile='core'):
    print((glGetString(GL_RENDERER) or b'').decode())
    print((glGetString(GL_VERSION) or b'').decode())
"""


#: The window systems a run can draw on: a hidden GLFW window, or none at all.
BACKENDS = ('glfw', 'offscreen', 'egl', 'wgl')


def gl_renderer(backend: str = 'glfw') -> dict[str, str]:
    """The GPU's GL_RENDERER and GL_VERSION, asked in a throwaway context on
    `backend`, the window system the renders are drawn on

    The context is the core profile the renders are made in, since a driver
    that names the profile in GL_VERSION would otherwise stamp every baseline
    with one the renders were never made in.
    """
    try:
        out = subprocess.run(
            [sys.executable, '-c', _PROVENANCE_PROGRAM],
            capture_output=True, text=True, timeout=30,
            env=dict(renderoptions.environment(), OPENGLCONTEXT_HIDDEN='1',
                     OPENGLCONTEXT_BACKEND=backend),
        ).stdout.splitlines()
        return {'gl_renderer': (out[0].strip() if out else '') or 'unknown',
                'gl_version': out[1].strip() if len(out) > 1 else ''}
    except Exception:
        return {'gl_renderer': 'unknown', 'gl_version': ''}


def provenance(renderer: Callable[[], dict[str, str]] = gl_renderer) -> dict[str, str]:
    """The git revision (``-dirty`` where the tree has changes), the time and
    the GPU's identity, stamped into each render's record"""
    root = source_root() or PACKAGE_PARENT
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
    found = {'git': git,
             'rendered_at': datetime.datetime.now().isoformat(timespec='seconds')}
    found.update(renderer())
    return found


def capture_environment(backend: str = 'glfw', **settings: str) -> dict[str, str]:
    """A drawing process's environment: a clean one, hidden, in the core
    profile on `backend`, with three shadow cascades and no frame counter,
    and `settings` over that"""
    pinned = dict(
        OPENGLCONTEXT_HIDDEN='1', OPENGLCONTEXT_NO_VSYNC='1',
        OPENGLCONTEXT_PROFILE='core', OPENGLCONTEXT_BACKEND=backend,
        OPENGLCONTEXT_SHADOW_CASCADES='3', OPENGLCONTEXT_DISABLE_FPS_DISPLAY='1')
    pinned.update(settings)
    return renderoptions.clean_environment(None, **pinned)


def parse_size(text: str) -> tuple[int, int]:
    """``WxH`` as (width, height)"""
    width, _, height = text.lower().partition('x')
    return (int(width), int(height))


def add_arguments(parser: argparse.ArgumentParser, *, names: str, baselines: str,
                  renders: str, size: tuple[int, int], frames: int,
                  frames_help: str) -> None:
    """The options both regression commands take

    names -- what `--only` and `--bless` match, said for the help: "whose
        name contains PART", say
    baselines, renders -- the default baseline and render directories, for the help
    """
    parser.add_argument('--only', action='append', metavar='PART',
                        help='draw only the ones %s (repeatable)' % names)
    parser.add_argument('--bless', nargs='*', metavar='PART', default=None,
                        help='make the renders already drawn, as the report shows them, the '
                             'baselines: every one, or those %s; nothing is drawn' % names)
    parser.add_argument('--baseline-root', metavar='DIR',
                        help='the baselines (default: %s)' % baselines)
    parser.add_argument('--out-dir', metavar='DIR',
                        help='the renders, records and differences (default: %s)' % renders)
    parser.add_argument('--report', metavar='HTML', help='where the report is written')
    parser.add_argument('--report-only', action='store_true',
                        help='rebuild the report from the renders already drawn')
    parser.add_argument('--size', type=parse_size, default=size, metavar='WxH',
                        help='render size (default %dx%d)' % size)
    parser.add_argument('--frames', type=int, default=frames,
                        help='%s (default %d)' % (frames_help, frames))
    parser.add_argument('--backend', choices=BACKENDS, default='glfw',
                        help="the window system drawn on: a hidden GLFW window (default), "
                             "or none (offscreen, egl, wgl)")
    parser.add_argument('--tolerance', type=float, default=DEFAULT_TOLERANCE, metavar='PCT',
                        help='percent of pixels that may differ (default %.1f)'
                             % DEFAULT_TOLERANCE)
    parser.add_argument('--diff-threshold', type=int, default=DIFF_THRESHOLD, metavar='N',
                        help='per-channel difference a pixel must exceed to count '
                             '(default %d)' % DIFF_THRESHOLD)


def compare(baseline_path: str, new_path: str, diff_out: str,
            threshold: int) -> tuple[Any, dict[str, Any]]:
    """Compare two PNGs: the ComparisonResult and its statistics, writing the
    difference image to `diff_out`"""
    import numpy as np  # noqa: PLC0415 only when comparing
    from PIL import Image  # noqa: PLC0415 only when comparing
    from OpenGLContext.testing.framebuffer_comparison import ComparisonResult  # noqa: PLC0415 only when comparing

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
    """Whether a comparison fails: a change of shape, or more than `tolerance`
    percent of pixels differing beyond the per-channel threshold"""
    if not result.shapes_match:
        return True
    return bool(result.percent_different > tolerance)


class ReportCounts(NamedTuple):
    """The rows of a report that fail a run"""

    regressions: int
    """Renders that differ from their baselines past the tolerance."""
    errors: int
    """Renders that failed: no image, or a drawing process that did not exit cleanly."""


def render_failure(returncode: int, stderr: Optional[str], written: bool) -> Optional[str]:
    """Why a drawing process failed; None where it wrote its image and exited with status 0

    The signal that killed it, or its exit status, with the last line it
    wrote to stderr; that line alone where it exited cleanly and wrote nothing.
    """
    last = (stderr or '').strip().splitlines()[-1:]
    if returncode < 0:
        try:
            how = 'killed by %s' % signal.Signals(-returncode).name
        except ValueError:
            how = 'killed by signal %d' % -returncode
        return ': '.join([how] + last)
    if returncode:
        return ': '.join(['exit status %d' % returncode] + last)
    if not written:
        return last[0] if last else 'no render'
    return None


def write_failure(out_dir: str, slug: str, record: dict[str, Any]) -> None:
    """Write the ``<slug>.json`` of a render that failed; `record` carries ``error``"""
    atomicfiles.write_text(os.path.join(out_dir, slug + '.json'), json.dumps(record, indent=2))


def promote(out_dir: str, baseline_root: str,
            chosen: Callable[[str, dict[str, Any]], bool]) -> list[str]:
    """Make the renders in `out_dir` that `chosen(slug, record)` picks the
    baselines in `baseline_root`, with their records; the slugs promoted

    These are the renders the report shows, so what is blessed is what was
    reviewed. A row whose render failed, or that has no image, is left.
    """
    promoted: list[str] = []
    if not os.path.isdir(out_dir):
        return promoted
    for slug in sorted(name[:-5] for name in os.listdir(out_dir) if name.endswith('.json')):
        record_path = os.path.join(out_dir, slug + '.json')
        image = os.path.join(out_dir, slug + '.png')
        try:
            with open(record_path) as stream:
                record = json.load(stream)
        except (OSError, ValueError):
            continue
        if record.get('error') or not os.path.exists(image) or not chosen(slug, record):
            continue
        os.makedirs(baseline_root, exist_ok=True)
        atomicfiles.copy_file(image, os.path.join(baseline_root, slug + '.png'))
        atomicfiles.copy_file(record_path, os.path.join(baseline_root, slug + '.json'))
        promoted.append(slug)
    return promoted


def _current_copy(src: str, dst: str) -> bool:
    """Whether `dst` is a copy of `src` as it is now: its size, and no older"""
    try:
        source, copy = os.stat(src), os.stat(dst)
    except OSError:
        return False
    return copy.st_size == source.st_size and copy.st_mtime_ns >= source.st_mtime_ns


def build_report(out_dir: str, baseline_root: str, report_path: str, tolerance: float,
                 diff_threshold: int, title: str,
                 upstream: Callable[[dict[str, Any], str], Optional[str]] = lambda _meta, _slug: None,
                 describe: Callable[[dict[str, Any]], str] = lambda meta: meta.get('description', ''),
                 drawn: Optional[Collection[str]] = None,
                 upstream_label: Callable[[dict[str, Any]], str] = lambda _meta: 'Upstream',
                 ) -> ReportCounts:
    """Write the HTML report of the renders in `out_dir`; the rows that fail

    Each ``<slug>.json`` in `out_dir` is a row: its ``<slug>.png`` against the
    baseline of that name in `baseline_root`, with the difference image, and
    the image `upstream` gives for the row's record and slug (None for none),
    headed by what `upstream_label` gives for the record. A row
    whose record has an ``error``, or with no render, is an error, and one with
    no baseline is skipped until blessed. Where `drawn` names the slugs this run
    drew, every other row is shown as not drawn and counts for nothing. Images
    from other trees are copied in beside the renders, so the report and its
    render directory move as one.
    """
    from OpenGLContext.testing.report_generator import TestReportGenerator  # noqa: PLC0415 only when reporting
    gen = TestReportGenerator(title=title)
    report_dir = os.path.dirname(os.path.abspath(report_path))

    def stage(src: Optional[str], name: str) -> Optional[str]:
        if not (src and os.path.exists(src)):
            return None
        if os.path.abspath(src).startswith(report_dir + os.sep):
            return src
        dst = os.path.join(out_dir, name)
        if _current_copy(src, dst):
            return dst
        try:
            atomicfiles.copy_file(src, dst)
            return dst
        except OSError:
            return src

    regressions = errors = 0
    slugs = sorted(name[:-5] for name in os.listdir(out_dir) if name.endswith('.json'))
    for slug in slugs:
        try:
            with open(os.path.join(out_dir, slug + '.json')) as stream:
                meta = json.load(stream)
        except Exception:
            meta = {}
        new_path = os.path.join(out_dir, slug + '.png')
        baseline_path = os.path.join(baseline_root, slug + '.png')
        diff_path = os.path.join(out_dir, slug + '_diff.png')
        try:
            upstream_path = upstream(meta, slug)
        except Exception:
            upstream_path = None
        status, stats, stderr = 'pass', None, ''
        if drawn is not None and slug not in drawn:
            status, stderr = 'skip', 'not drawn in this run'
        elif meta.get('error') or not os.path.exists(new_path):
            status, errors = 'error', errors + 1
            stderr = str(meta.get('error') or 'no render on disk')
        elif not os.path.exists(baseline_path):
            status, stderr = 'skip', 'no baseline -- bless after reviewing'
        else:
            result, stats = compare(baseline_path, new_path, diff_path, diff_threshold)
            if is_regression(result, tolerance):
                status, regressions = 'fail', regressions + 1
                stderr = 'REGRESSION: %s' % result
            else:
                stderr = str(result)
        if meta.get('problems'):
            stderr = '\n'.join([stderr] + list(meta['problems'])).strip()
        gen.add_test({
            'test_name': '%s -- %s' % (slug, describe(meta)),
            'status': status,
            'reference_image': stage(baseline_path, slug + '_baseline.png'),
            'result_image': new_path if os.path.exists(new_path) else None,
            'diff_image': diff_path if (stats and os.path.exists(diff_path)) else None,
            'upstream_image': stage(upstream_path, slug + '_upstream.png'),
            'upstream_label': upstream_label(meta),
            'comparison_stats': stats,
            'metadata': meta,
            'stderr': stderr,
            'duration': 0.0,
        })
    os.makedirs(report_dir, exist_ok=True)
    # Linked rather than embedded: a run is hundreds of views of four images
    # each, which embedded would make one HTML file of hundreds of megabytes.
    gen.save(report_path, embed_images=False)
    return ReportCounts(regressions, errors)


def exit_status(counts: ReportCounts, report_path: str) -> int:
    """Print where the report is and what failed; 1 where anything did, else 0"""
    print('\nReport: %s' % report_path)
    if counts.regressions:
        print('%d regression(s) detected.' % counts.regressions)
    if counts.errors:
        print('%d render(s) failed.' % counts.errors)
    return 1 if counts.regressions or counts.errors else 0
