#!/usr/bin/env python
"""Run every demo script under both OpenGL profiles and compare what it drew.

An exit code does not say whether a script rendered.  A fixed-function call in a
core context raises ``GLError(1282)``, and the render pass catches it per node,
logs it and carries on -- so the process exits 0, the log has a line in it that
nobody reads, and the frame is black.  That is the failure this exists to catch,
and the one that produced the black figures behind
[plans/CORE-PROFILE-DEFAULT.md](../plans/CORE-PROFILE-DEFAULT.md).

So each script is run twice -- once with ``OPENGLCONTEXT_PROFILE=compatibility``
and once with nothing set at all, which is the core profile every context gets by
default -- through the auto-exit capture path, and judged on its **capture** as
well as its exit code.  A script that declares ``profile = 'compatibility'`` gets
that in both arms, which is the point: the declaration outranks the variable, so
what the sweep measures is what a person running the script will see.

```bash
scripts/profile_sweep.py --out /tmp/sweep            # both profiles, every script
scripts/profile_sweep.py --out /tmp/sweep shader_1.py molehill.py
```

The report names, per bucket, what changed between the profiles.  The bucket that
matters is *blank under core*: a script that drew under one profile and drew
nothing under the other.  ``results.json`` beside the captures holds the whole
run, so a later comparison does not have to render again.

Requires a GL target.  See the headless notes in CLAUDE.md for CI.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Sequence

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(HERE, 'tests')

#: Scripts that are not a profile question: platform-specific, their own test
#: harness, or this file's siblings.
SKIP = {
    '__init__.py', 'conftest.py', 'runalltests.py', 'run_core_tests.py',
    'run_teapot_regression.py', 'test_all_scripts.py', 'numpyfields.py',
    'frust_test_module.py', 'profile_view.py',
    # Windows-only (WGL)
    'wgl_font.py', 'wgl_bitmap_font.py', 'wglpixelformatarb.py', 'glprint.py',
    # Each names a backend of its own, so running it under --backend measures
    # that backend's absence rather than either profile.
    'glut_font.py', 'wx_font.py', 'wx_multiple_contexts.py', 'wx_with_controls.py',
}

#: Below this percentage of pixels differing from the frame's most common colour,
#: a capture counts as having drawn nothing.  A frame that drew only the
#: background is black by this measure, which is the intent.
DREW = 0.05


def scripts(only: Sequence[str] = ()) -> List[str]:
    """The scripts to sweep, as bare file names."""
    if only:
        return list(only)
    return sorted(
        name for name in os.listdir(TESTS)
        if name.endswith('.py') and not name.startswith('_') and name not in SKIP
    )


def drawn_fraction(path: str) -> Optional[float]:
    """Percentage of the capture that differs from its most common colour.

    Measured against the frame's own background rather than against black, so a
    scene on a sky-blue background is not read as fully drawn.
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:  # pragma: no cover - numpy and Pillow are dependencies
        return None
    try:
        pixels = np.asarray(Image.open(path).convert('RGB')).reshape(-1, 3).astype(int)
    except Exception:
        return None
    values, counts = np.unique(pixels, axis=0, return_counts=True)
    background = values[counts.argmax()]
    return round(float((np.abs(pixels - background).max(axis=1) > 12).mean()) * 100, 2)


def run(name: str, profile: str, capture_dir: str, backend: str,
        frames: int, timeout: int) -> Dict[str, Any]:
    """One script, one profile, one capture."""
    env = dict(os.environ)
    # The core arm names no profile at all, because core is what a context asks
    # for when nothing does -- and a script that declares
    # ``profile = 'compatibility'`` outranks the variable, so setting it would
    # measure something no user will ever run.
    if profile == 'core':
        env.pop('OPENGLCONTEXT_PROFILE', None)
    else:
        env['OPENGLCONTEXT_PROFILE'] = profile
    env.update({
        'OPENGLCONTEXT_BACKEND': backend,
        'OPENGLCONTEXT_HIDDEN': '1',
        'OPENGLCONTEXT_NO_VSYNC': '1',
        'OPENGLCONTEXT_AUTO_EXIT_FRAMES': str(frames),
        'OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR': capture_dir,
        'OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME': name[:-3],
        'OPENGLCONTEXT_DISABLE_FPS_DISPLAY': '1',
        # Pinned so a difference between the two runs is the profile rather than
        # the frame rate: both adapt themselves otherwise.
        'OPENGLCONTEXT_LOD': 'off',
        'OPENGLCONTEXT_SHADOW_CASCADES': '2',
    })
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(TESTS, name)], cwd=TESTS, env=env,
            capture_output=True, text=True, timeout=timeout)
        exit_code: Any = proc.returncode
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        exit_code, output = 'timeout', ''
    png = os.path.join(capture_dir, name[:-3] + '.png')
    return {
        'script': name,
        'profile': profile,
        'exit': exit_code,
        'drawn': drawn_fraction(png) if os.path.exists(png) else None,
        'failing_calls': sorted(set(re.findall(r'baseOperation = (\w+)', output))),
        'tail': '\n'.join(output.strip().splitlines()[-25:]),
    }


def sweep(out: str, names: Sequence[str], backend: str, frames: int,
          timeout: int, jobs: int) -> List[Dict[str, Any]]:
    results = []
    for profile in ('compatibility', 'core'):
        capture_dir = os.path.join(out, profile)
        os.makedirs(capture_dir, exist_ok=True)
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = [pool.submit(run, name, profile, capture_dir, backend, frames, timeout)
                       for name in names]
            for future in futures:
                result = future.result()
                results.append(result)
                print('%-14s %-34s exit=%-8s drawn=%s'
                      % (profile, result['script'], result['exit'], result['drawn']),
                      flush=True)
    return results


def report(results: Sequence[Dict[str, Any]]) -> int:
    """Print the buckets and return the number of regressions found."""
    paired: Dict[str, Dict[str, Any]] = collections.defaultdict(dict)
    for result in results:
        paired[result['script']][result['profile']] = result

    buckets: Dict[str, List[Any]] = collections.defaultdict(list)
    for name, pair in sorted(paired.items()):
        compat, core = pair.get('compatibility'), pair.get('core')
        if not compat or not core:
            buckets['incomplete'].append(name)
            continue
        compat_ran, core_ran = compat['exit'] == 0, core['exit'] == 0
        compat_drew = (compat['drawn'] or 0) > DREW
        core_drew = (core['drawn'] or 0) > DREW
        if not compat_ran and not core_ran:
            buckets['broken under both profiles'].append(name)
        elif compat_ran and not core_ran:
            buckets['crashes under core'].append(
                '%-32s %s' % (name, ','.join(core['failing_calls']) or core['exit']))
        elif core_ran and not compat_ran:
            buckets['fixed by core'].append(name)
        elif compat_drew and not core_drew:
            buckets['BLANK UNDER CORE'].append(
                '%-32s %5.2f%% -> nothing   %s'
                % (name, compat['drawn'], ','.join(core['failing_calls']) or '(no GLError)'))
        elif core_drew and not compat_drew:
            buckets['blank under compatibility'].append(
                '%-32s nothing -> %5.2f%%' % (name, core['drawn']))
        elif not compat_drew and not core_drew:
            buckets['nothing drawn either way'].append(name)
        else:
            buckets['draws under both'].append(name)

    order = ['BLANK UNDER CORE', 'crashes under core', 'blank under compatibility',
             'fixed by core', 'broken under both profiles', 'draws under both',
             'nothing drawn either way', 'incomplete']
    for key in order:
        items = buckets.get(key)
        if not items:
            continue
        print('\n== %s: %d ==' % (key, len(items)))
        for item in items:
            print('   ', item)
    return len(buckets['BLANK UNDER CORE']) + len(buckets['crashes under core'])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('scripts', nargs='*', help='scripts to sweep (default: all)')
    parser.add_argument('--out', default='profile-sweep',
                        help='where captures and results.json go')
    parser.add_argument('--backend', default='glfw')
    parser.add_argument('--frames', type=int, default=8,
                        help='frames to render before the capture')
    parser.add_argument('--timeout', type=int, default=45, help='seconds per run')
    parser.add_argument('--jobs', type=int, default=4, help='scripts to run at once')
    parser.add_argument('--report', metavar='RESULTS',
                        help='report on an existing results.json instead of rendering')
    options = parser.parse_args()

    if options.report:
        with open(options.report) as handle:
            return 1 if report(json.load(handle)) else 0

    os.makedirs(options.out, exist_ok=True)
    results = sweep(options.out, scripts(options.scripts), options.backend,
                    options.frames, options.timeout, options.jobs)
    with open(os.path.join(options.out, 'results.json'), 'w') as handle:
        json.dump(results, handle, indent=1)
    return 1 if report(results) else 0


if __name__ == '__main__':
    sys.exit(main())
