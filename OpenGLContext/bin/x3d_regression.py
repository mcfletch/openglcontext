#! /usr/bin/env python
"""Render Web3D's X3D examples and compare them with baselines (``oglc-x3d-regression``)

Every ``.x3d`` document in the chosen archives of Web3D's example corpus
(`vrml.x3d.corpus`) is drawn as its author wrote it: in a plain Context, from
its bound viewpoint or X3D's default one, against its own Background or
black, and after the textures and Inlines it names have arrived. Each render
is compared with **our reference** -- the blessed baseline in the
``tests/reference_images`` submodule -- and the report shows a reference render
beside them: X_ITE's, from the ``x3d_xite`` folder of the same submodule
(``scripts/x3d_xite_references.py`` draws them), else Web3D's own render of the
same viewpoint, published with each example. Each row says how much ours
differs from the reference; that figure is for the reader of the report and
fails no run.

    oglc-x3d-regression --fetch          # download the corpus with its images, once
    oglc-x3d-regression                  # exit non-zero if a render regressed or failed
    oglc-x3d-regression --bless          # the renders reviewed in the report become baselines
    oglc-x3d-regression --only Geometry/Box --jobs 8

Each document is drawn in a process of its own, and ``--jobs`` runs that
many at a time. Only the XML encoding is drawn: the corpus tests in pyvrml97
hold the other encodings to the same scene graph. Scripts are not run, so a
scene a Script builds is drawn as the document leaves it.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional

from OpenGLContext import atomicfiles, renderoptions
from OpenGLContext.testing import renderregression

__all__ = [
    'Scene', 'find_scenes', 'upstream_render', 'render_scene', 'parse_render_report',
    'build_report', 'run', 'main',
]

#: The size of the renders Web3D publishes, so each sits beside its own.
DEFAULT_SIZE = (792, 465)
#: Frames drawn once the document's loads have arrived, on the capture clock.
DEFAULT_FRAMES = 8
#: Seconds a document's loads are waited for before it is drawn without them.
LOAD_WAIT = 30.0
#: Seconds one document's process is given.
RENDER_TIMEOUT = 120.0
#: The archives drawn where none are named.
DEFAULT_ARCHIVES = ('ConformanceNist', 'Vrml2Sourcebook')
#: The most problems a document's record keeps.
MAX_PROBLEMS = 20
#: The world time, in seconds since 1970, a document's first frame is drawn at
#: (2000-01-01): a TimeSensor with startTime 0 has run its cycle long before.
WORLD_START = 946684800.0
#: Begins the line the drawing process reports on.
REPORT_MARK = 'X3D_RENDER '
#: The per-channel difference a pixel must exceed to count as differing from
#: the reference: wider than DIFF_THRESHOLD, as another renderer shades otherwise.
REFERENCE_THRESHOLD = 32


@dataclass(frozen=True)
class Scene:
    """One document of the corpus"""

    #: The archive and the path under the archive's examples, without ``.x3d``.
    name: str
    #: The document's file.
    path: str
    #: The folder of every archive's examples: its content root, as a scene may
    #: name files of its own archive and of others.
    root: str

    @property
    def slug(self) -> str:
        """The name its render and baseline files take"""
        return self.name.replace('/', '.')


def default_baseline_root() -> str:
    """Where the blessed baselines live: ``OPENGLCONTEXT_X3D_BASELINE``, else the
    ``x3d_baseline`` folder of the ``tests/reference_images`` submodule"""
    named = renderoptions.env_text('OPENGLCONTEXT_X3D_BASELINE')
    if named:
        return named
    root = renderregression.source_root() or renderregression.PACKAGE_PARENT
    return os.path.join(root, 'tests', 'reference_images', 'x3d_baseline')


def default_reference_root() -> str:
    """Where X_ITE's renders are kept: the ``x3d_xite`` folder of the
    ``tests/reference_images`` submodule"""
    root = renderregression.source_root() or renderregression.PACKAGE_PARENT
    return os.path.join(root, 'tests', 'reference_images', 'x3d_xite')


def default_report_path() -> str:
    root = renderregression.source_root() or renderregression.PACKAGE_PARENT
    return os.path.join(root, 'tests', 'x3d_regression', 'x3d_regression_report.html')


def default_out_dir() -> str:
    """The renders, records and differences of the latest run of each document"""
    return os.path.join(os.path.dirname(default_report_path()), 'renders')


def find_scenes(root: str, archives: Sequence[str],
                only: Optional[Sequence[str]] = None) -> list[Scene]:
    """The non-empty documents of `archives` in the corpus at `root`, by name;
    with `only`, those whose name contains one of its strings"""
    from vrml.x3d import corpus  # noqa: PLC0415 only when looking
    found = []
    for archive in archives:
        examples = corpus.examples(archive, root)
        for folder, _dirs, names in os.walk(examples):
            for name in names:
                path = os.path.join(folder, name)
                if not name.endswith('.x3d') or os.path.getsize(path) == 0:
                    continue
                relative = os.path.relpath(path, examples)[:-len('.x3d')].replace(os.sep, '/')
                scene = Scene('%s/%s' % (archive, relative), path, os.path.dirname(examples))
                if not only or any(part in scene.name for part in only):
                    found.append(scene)
    return sorted(found, key=lambda scene: scene.name)


def upstream_render(document: str, viewpoint: Optional[dict[str, Any]]) -> Optional[str]:
    """Web3D's render of `document` from the viewpoint it opened on; None if unpublished

    `viewpoint` holds the bound viewpoint's ``description`` and ``DEF``, and is
    None for a document with none, which Web3D names ``Default_viewpoint``.
    """
    from vrml.x3d import corpus  # noqa: PLC0415 only when looking
    renders = corpus.viewpoint_renders(document)
    if viewpoint is None:
        return renders.get('Default_viewpoint')
    for key in ('description', 'DEF'):
        name = corpus.render_name(viewpoint.get(key) or '')
        if name and name in renders:
            return renders[name]
    return None


def parse_render_report(stdout: Optional[str]) -> dict[str, Any]:
    """What the drawing process reported, from its :data:`REPORT_MARK` line"""
    for line in (stdout or '').splitlines():
        if line.startswith(REPORT_MARK):
            found: dict[str, Any] = json.loads(line[len(REPORT_MARK):])
            return found
    return {}


def render_outcome(returncode: int, stdout: Optional[str], stderr: Optional[str],
                   written: bool) -> tuple[bool, dict[str, Any]]:
    """Whether a drawing process succeeded, and what it reported

    It succeeded where it wrote its image and exited with status 0. The
    report is its :data:`REPORT_MARK` line with its ``returncode``, and an
    ``error`` where it failed (:func:`~OpenGLContext.testing.renderregression.render_failure`).
    """
    report = parse_render_report(stdout)
    report['returncode'] = returncode
    error = renderregression.render_failure(returncode, stderr, written)
    if error is not None:
        report['error'] = error
    return error is None, report


def render_scene(scene: Scene, out: str, size: tuple[int, int], frames: int,
                 timeout: float = RENDER_TIMEOUT,
                 renderer: str = 'pbr') -> tuple[bool, dict[str, Any]]:
    """Draw `scene` to the PNG `out` in a process of its own, with `renderer`
    (``pbr`` or ``vrml97``); whether it succeeded (:func:`render_outcome`),
    and what the process reported"""
    if os.path.exists(out):
        os.remove(out)
    env = _render_environment(out, frames, renderer)
    command = [sys.executable, '-m', 'OpenGLContext.bin.x3d_regression', '--render', scene.path,
               '--root', scene.root, '--size', '%dx%d' % size]
    try:
        proc = subprocess.run(command, timeout=timeout, capture_output=True, text=True,
                              cwd=os.path.dirname(scene.path), env=env)
    except subprocess.TimeoutExpired:
        return False, {'error': 'timed out after %.0f seconds' % timeout}
    return render_outcome(proc.returncode, proc.stdout, proc.stderr, os.path.exists(out))


def _render_environment(out: str, frames: int, renderer: str = 'pbr') -> dict[str, str]:
    """The drawing process's environment: a clean one, drawing with `renderer`
    and capturing `frames` frames to `out`"""
    return renderoptions.clean_environment(
        OPENGLCONTEXT_RENDERER=renderer,
        OPENGLCONTEXT_HIDDEN='1', OPENGLCONTEXT_NO_VSYNC='1',
        OPENGLCONTEXT_PROFILE='core', OPENGLCONTEXT_BACKEND='glfw',
        OPENGLCONTEXT_SHADOW_CASCADES='3', OPENGLCONTEXT_BLOOM='0',
        OPENGLCONTEXT_DISABLE_FPS_DISPLAY='1', OPENGLCONTEXT_AUDIO='0',
        OPENGLCONTEXT_SEED='4242',
        OPENGLCONTEXT_CAPTURE_START=repr(WORLD_START),
        OPENGLCONTEXT_AUTO_EXIT_FRAMES=str(frames),
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR=os.path.dirname(os.path.abspath(out)),
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME=os.path.splitext(os.path.basename(out))[0])


def draw_document(path: str, root: str, size: tuple[int, int]) -> None:
    """Open `path` in a plain Context and let the capture run draw and read it

    `root` is a content root (:func:`OpenGLContext.loaders.resolver.add_content_root`):
    Web3D's examples name images in folders above their own.

    Run in the drawing process. Its frames are not counted, and its clock does
    not move, until the document's own loads -- the scene, and the textures
    and Inlines its nodes fetch -- have arrived, or :data:`LOAD_WAIT` seconds
    have passed. Prints the read's problems and the bound viewpoint as one
    :data:`REPORT_MARK` line.
    """
    import time  # noqa: PLC0415 only in the drawing process
    from OpenGLContext import testingcontext  # noqa: PLC0415 only in the drawing process
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 only in the drawing process
    from OpenGLContext.loaders import background  # noqa: PLC0415 only in the drawing process
    from OpenGLContext.loaders import resolver  # noqa: PLC0415 only in the drawing process
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 only in the drawing process

    resolver.add_content_root(root)
    base: Any = testingcontext.getInteractive()
    report: dict[str, Any] = {'problems': [], 'viewpoint': None, 'loads_waited': False}

    class Document(base):                       # pragma: no cover - its own process
        def OnInit(self) -> None:
            self.started = time.monotonic()
            self.sg = Loader.load(path)
            report['problems'] = [
                '%s: %s' % (problem.severity, problem.message)
                for problem in getattr(self.sg, 'problems', ())
                if problem.severity != 'info'][:MAX_PROBLEMS]

        def loadsPending(self) -> bool:
            pending = (super().loadsPending() or background.pending() > 0
                       or len(getattr(self, 'renderQueue', ())) > 0)
            if pending and time.monotonic() - self.started > LOAD_WAIT:
                report['loads_waited'] = True
                return False
            return pending

        def _autoExitCapture(self) -> None:
            from OpenGLContext.passes.viewpointbinding import default_viewpoint  # noqa: PLC0415 its own process
            view = getattr(self.sg, 'boundViewpoint', None)
            if view is not None and view is not default_viewpoint(self.sg):
                report['viewpoint'] = {'description': str(view.description),
                                       'DEF': str(getattr(view, 'DEF', '') or '')}
            print(REPORT_MARK + json.dumps(report), flush=True)
            super()._autoExitCapture()

    Document.ContextMainLoop(definition=ContextDefinition(size=size))


def _difference(reference: str, ours: str) -> Optional[float]:
    """Percent of pixels differing from the reference beyond REFERENCE_THRESHOLD"""
    import numpy as np  # noqa: PLC0415 only when comparing
    from PIL import Image  # noqa: PLC0415 only when comparing
    from OpenGLContext.testing.framebuffer_comparison import compare_images  # noqa: PLC0415 only when comparing
    try:
        theirs = np.asarray(Image.open(reference).convert('RGB'))
        mine = np.asarray(Image.open(ours).convert('RGB'))
    except OSError:
        return None
    result = compare_images(theirs, mine, threshold=REFERENCE_THRESHOLD)
    return 100.0 if not result.shapes_match else float(result.percent_different)


def _reference(scene: Scene, report: dict[str, Any], args: argparse.Namespace,
               rendered: str) -> dict[str, Any]:
    """The reference a render is shown beside, and how much it differs from it"""
    found: dict[str, Any] = {'reference': 'Web3D', 'reference_errors': [],
                             'upstream': upstream_render(scene.path, report.get('viewpoint'))}
    x_ite = os.path.join(args.reference_root or default_reference_root(), scene.slug + '.png')
    if args.reference == 'x_ite' and os.path.exists(x_ite):
        found.update(reference='X_ITE', upstream=x_ite)
        try:
            with open(os.path.splitext(x_ite)[0] + '.json') as stream:
                record = json.load(stream)
        except (OSError, ValueError):
            record = {}
        if record.get('x_ite'):
            found['reference'] = 'X_ITE %s' % record['x_ite']
        found['reference_errors'] = list(record.get('errors', ()))
    found['reference_difference'] = (_difference(found['upstream'], rendered)
                                     if found['upstream'] else None)
    return found


def _view_metadata(scene: Scene, report: dict[str, Any], args: argparse.Namespace,
                   provenance: dict[str, str]) -> dict[str, Any]:
    return {
        'scene': scene.name,
        'slug': scene.slug,
        'document': scene.path,
        'problems': list(report.get('problems', ())),
        'viewpoint': report.get('viewpoint'),
        'loads_waited': report.get('loads_waited', False),
        'frames': args.frames,
        'size': list(args.size),
        'git': provenance['git'],
        'rendered_at': provenance['rendered_at'],
        'gl_renderer': provenance['gl_renderer'],
        'gl_version': provenance['gl_version'],
    }


def render_scenes(scenes: Sequence[Scene], out_dir: str, baseline_root: str,
                  args: argparse.Namespace, provenance: dict[str, str]) -> list[str]:
    """Draw each scene to ``<slug>.png`` in `out_dir` with its ``<slug>.json``
    record, `args.jobs` at a time; the slugs drawn. A render that failed has a
    record with its ``error``."""
    os.makedirs(out_dir, exist_ok=True)

    def one(scene: Scene) -> str:
        try:
            return drawn(scene)
        except Exception as error:  # noqa: BLE001 one document's failure is its row, not the run's end
            record = {'scene': scene.name, 'slug': scene.slug, 'document': scene.path,
                      'error': '%s: %s' % (type(error).__name__, error)}
            try:
                renderregression.write_failure(out_dir, scene.slug, record)
            except OSError:
                pass  # noqa: S110 the run reports the failure; a record that cannot be written adds nothing
            return '  FAIL  %s (%s)' % (scene.name, record['error'])

    def drawn(scene: Scene) -> str:
        new_path = os.path.join(out_dir, scene.slug + '.png')
        ok, report = render_scene(scene, new_path, args.size, args.frames,
                                  renderer=args.renderer)
        record = _view_metadata(scene, report, args, provenance)
        if not ok:
            record.update(error=report.get('error', 'no render'),
                          returncode=report.get('returncode'))
            renderregression.write_failure(out_dir, scene.slug, record)
            return '  FAIL  %s (%s)' % (scene.name, record['error'])
        record.update(_reference(scene, report, args, new_path))
        atomicfiles.write_text(os.path.join(out_dir, scene.slug + '.json'),
                               json.dumps(record, indent=2))
        return '  OK    %s' % scene.name

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for line in pool.map(one, scenes):
            print(line, flush=True)
    return [scene.slug for scene in scenes]


def build_report(out_dir: str, baseline_root: str, report_path: str, tolerance: float,
                 diff_threshold: int,
                 drawn: Optional[Sequence[str]] = None) -> renderregression.ReportCounts:
    """The HTML report of the renders in `out_dir`, with each document's reference
    as the upstream column; the rows that fail, among `drawn` where given"""
    return renderregression.build_report(
        out_dir, baseline_root, report_path, tolerance, diff_threshold,
        title='X3D Example Regression -- our reference vs new',
        upstream=lambda meta, _slug: meta.get('upstream'),
        describe=_describe, drawn=drawn)


def _describe(meta: dict[str, Any]) -> str:
    """A row's title: the document, and how far it is from its reference"""
    difference = meta.get('reference_difference')
    if difference is None:
        return str(meta.get('scene', ''))
    return '%s -- %.0f%% unlike %s' % (meta.get('scene', ''), difference,
                                       meta.get('reference', 'the reference'))


def run(args: argparse.Namespace) -> int:
    from vrml.x3d import corpus  # noqa: PLC0415 only when running
    root = args.corpus or corpus.directory()
    if args.fetch:
        archives = corpus.with_references(args.archive or DEFAULT_ARCHIVES)
        for name, count in corpus.fetch(archives, root, resources=True).items():
            print('%s: %d documents' % (name, count))
    baseline_root = args.baseline_root or default_baseline_root()
    out_dir = args.out_dir or default_out_dir()
    report = args.report or default_report_path()
    if args.bless is not None:
        return bless(out_dir, baseline_root, args.bless)
    drawn = None
    if not args.report_only:
        scenes = find_scenes(root, args.archive or DEFAULT_ARCHIVES, args.only)
        if not scenes:
            print('No X3D documents in %s; --fetch downloads the corpus' % root)
            return 2
        provenance = renderregression.provenance(lambda: renderregression.gl_renderer())
        print('Corpus:     %s (%d documents)' % (root, len(scenes)))
        print('Baselines:  %s' % baseline_root)
        print('Renders:    %s' % out_dir)
        print('Provenance: git %s, %s, %s' % (
            provenance['git'], provenance['rendered_at'], provenance['gl_renderer']))
        drawn = render_scenes(scenes, out_dir, baseline_root, args, provenance)
    os.makedirs(out_dir, exist_ok=True)
    counts = build_report(out_dir, baseline_root, report, args.tolerance,
                          args.diff_threshold, drawn)
    return renderregression.exit_status(counts, report)


def bless(out_dir: str, baseline_root: str, parts: Sequence[str]) -> int:
    """Make the renders in `out_dir` baselines: every one, or those whose
    document's name contains one of `parts`; 1 where there were none"""
    promoted = renderregression.promote(
        out_dir, baseline_root,
        lambda _slug, record: not parts or any(part in record.get('scene', '') for part in parts))
    for slug in promoted:
        print('  BLESS %s' % slug)
    if not promoted:
        print('Nothing to bless in %s: draw the documents first' % out_dir)
        return 1
    print('%d baseline(s) in %s' % (len(promoted), baseline_root))
    return 0


def _parse_size(text: str) -> tuple[int, int]:
    width, _, height = text.lower().partition('x')
    return (int(width), int(height))


def build_parser(prog: str = 'oglc-x3d-regression') -> argparse.ArgumentParser:
    from vrml.x3d import corpus  # noqa: PLC0415 for the archive names
    parser = argparse.ArgumentParser(prog=prog, description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--fetch', action='store_true',
                        help='download and extract the archives, with their images and '
                             "Web3D's renders, before drawing")
    parser.add_argument('--archive', action='append', choices=corpus.ARCHIVES,
                        help='an archive to draw (repeatable; default %s)'
                             % ' and '.join(DEFAULT_ARCHIVES))
    parser.add_argument('--corpus', metavar='DIR',
                        help='the corpus directory (default: vrml.x3d.corpus.directory())')
    parser.add_argument('--only', action='append', metavar='PART',
                        help='draw only the documents whose name contains PART (repeatable)')
    parser.add_argument('--bless', nargs='*', metavar='PART', default=None,
                        help='make the renders already drawn, as the report shows them, the '
                             'baselines: every one, or those whose name contains a PART; '
                             'nothing is drawn')
    parser.add_argument('--jobs', type=int, default=os.cpu_count() or 1,
                        help='documents drawn at a time (default: the processor count)')
    parser.add_argument('--baseline-root', metavar='DIR',
                        help='baseline directory (default: tests/reference_images/x3d_baseline '
                             'or $OPENGLCONTEXT_X3D_BASELINE)')
    parser.add_argument('--report', metavar='HTML', help='report path')
    parser.add_argument('--out-dir', metavar='DIR',
                        help='the renders, records and differences (default: '
                             'tests/x3d_regression/renders)')
    parser.add_argument('--report-only', action='store_true',
                        help='rebuild the report from the renders already there')
    parser.add_argument('--size', type=_parse_size, default=DEFAULT_SIZE, metavar='WxH',
                        help='render size (default %dx%d, the size of Web3D\'s renders)'
                             % DEFAULT_SIZE)
    parser.add_argument('--frames', type=int, default=DEFAULT_FRAMES,
                        help='frames drawn once the loads have arrived (default %d)'
                             % DEFAULT_FRAMES)
    parser.add_argument('--tolerance', type=float, default=renderregression.DEFAULT_TOLERANCE,
                        metavar='PCT', help='percent of pixels that may differ (default %.1f)'
                        % renderregression.DEFAULT_TOLERANCE)
    parser.add_argument('--diff-threshold', type=int, default=renderregression.DIFF_THRESHOLD,
                        metavar='N', help='per-channel difference a pixel must exceed to count '
                        '(default %d)' % renderregression.DIFF_THRESHOLD)
    parser.add_argument('--reference', choices=('x_ite', 'web3d'), default='x_ite',
                        help="what each render is shown beside: X_ITE's render of it "
                             "(default, where there is one), or Web3D's published one")
    parser.add_argument('--reference-root', metavar='DIR',
                        help="X_ITE's renders (default: tests/reference_images/x3d_xite)")
    parser.add_argument('--renderer', choices=('pbr', 'vrml97'), default='pbr',
                        help="the pass documents are drawn with: the PBR pass (default), "
                             "or the VRML97 pass, which shades a Material by X3D's equation")
    parser.add_argument('--render', metavar='DOCUMENT', help=argparse.SUPPRESS)
    parser.add_argument('--root', metavar='DIR', help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.render:                             # pragma: no cover - its own process
        draw_document(args.render, args.root or os.path.dirname(args.render), args.size)
        return 0
    return run(args)


if __name__ == '__main__':  # pragma: no cover - CLI entry point
    sys.exit(main())
