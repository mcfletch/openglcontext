#!/usr/bin/env python
"""Build levels of detail for a mesh and measure what each one looks like.

Decimates a model into a chain, renders every level against the original over a
sweep of camera distances -- from far enough that it covers a few pixels to
close enough to read the surface -- and reports, for each level, the closest
distance at which swapping it in does not change the picture.

    python scripts/lod_quality.py model.gltf
    python scripts/lod_quality.py model.npz --levels 6 --budget 0.02 --sheet out.png

A ``.npz`` is read as ``POSITION``/``NORMAL``/``INDICES`` arrays; anything else
goes through the glTF loader. ``--sheet`` writes a contact sheet so the numbers
can be checked against what they are measuring.
"""

import argparse
import os
import sys
import time

import numpy as np


def load(path):
    """``(attributes, indices)`` from a ``.npz`` of arrays or a glTF file."""
    if path.endswith('.npz'):
        held = np.load(path)
        attributes = {name: held[name] for name in held.files if name != 'INDICES'}
        return attributes, held['INDICES']
    from OpenGLContext.loaders.gltf import scene as gltfscene

    loaded = gltfscene.load(path)
    raise SystemExit('give a .npz of arrays; %r loaded as %r' % (path, type(loaded)))


def contact_sheet(images, path, columns=None):
    """Tile renders into one picture so the levels can be compared by eye."""
    from PIL import Image

    columns = columns or len(images[0])
    size = images[0][0].shape[0]
    sheet = Image.new('RGB', (columns * size, len(images) * size))
    for row, line in enumerate(images):
        for column, picture in enumerate(line[:columns]):
            sheet.paste(Image.fromarray(picture), (column * size, row * size))
    sheet.save(path)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model')
    parser.add_argument('--levels', type=int, default=6)
    parser.add_argument('--ratio', type=float, default=0.5)
    parser.add_argument('--budget', type=float, default=0.02,
                        help='share of the object\'s pixels allowed to change')
    parser.add_argument('--size', type=int, default=512)
    parser.add_argument('--sheet', default=None, help='write a contact sheet here')
    parser.add_argument('--rotation', type=float, default=25.0)
    args = parser.parse_args(argv)

    from OpenGLContext.meshlod import build_chain, measure_chain
    from OpenGLContext.meshlod.quality import LODProbe
    from OpenGLContext.testing.glcontext import hidden_window

    attributes, indices = load(args.model)
    triangles = len(np.asarray(indices).reshape(-1)) // 3
    print('%s: %d triangles, %d vertices'
          % (os.path.basename(args.model), triangles, len(attributes['POSITION'])))

    start = time.perf_counter()
    chain = build_chain(attributes, indices, levels=args.levels, ratio=args.ratio)
    print('built %d levels in %.1fs (radius %.4f)\n'
          % (len(chain), time.perf_counter() - start, chain.radius))

    # Multiples of the object's radius, measured from its surface: the near
    # end is a camera almost touching it, the far end is where the whole thing
    # covers a few dozen pixels.
    distances = [0.002, 0.01, 0.05, 0.2, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0]

    with hidden_window('lod-quality', size=(args.size, args.size), profile='core') as _window:
        with LODProbe(size=args.size) as probe:
            reports = measure_chain(chain, probe, distances, budget=args.budget,
                                    rotation=args.rotation)
            sheet = None
            if args.sheet:
                rows = [
                    [
                        probe.render(level.attributes['POSITION'], level.attributes['NORMAL'],
                                     level.indices, distance=(1.0 + d) * chain.radius,
                                     radius=chain.radius, centre=chain.centre,
                                     rotation=args.rotation)
                        for d in (0.01, 0.2, 1.0, 8.0)
                    ]
                    for level in chain
                ]
                sheet = contact_sheet(rows, args.sheet)

    def distance(value):
        return 'never' if value == float('inf') else '%6.2fr' % value

    header = '  '.join('%7.3fr' % d for d in distances)
    print('outline change (pixels the object covers in one render and not the other)')
    print('%-5s %9s %9s  %8s  %s' % ('level', 'triangles', 'error', 'safe at', header))
    for report in reports:
        print('%-5d %9d %9.5f  %8s  %s'
              % (report.level, report.triangle_count, report.error,
                 distance(report.safe_at_outline),
                 '  '.join('%7.2f%%' % (p * 100) for p in report.outlines)))
    print()
    print('shading change (pixels both cover, lit differently by the level\'s normals)')
    print('%-5s %9s %9s  %8s  %s' % ('level', 'triangles', 'error', 'safe at', header))
    for report in reports:
        print('%-5d %9d %9.5f  %8s  %s'
              % (report.level, report.triangle_count, report.error,
                 distance(report.safe_at),
                 '  '.join('%7.2f%%' % (s * 100) for s in report.shadings)))

    print('\n"safe at" is the distance from the surface, in object radii, beyond')
    print('which the level changes less than %.0f%% of the object\'s pixels.'
          % (args.budget * 100))
    if sheet:
        print('contact sheet: %s' % (sheet,))
    return 0


if __name__ == '__main__':
    sys.exit(main())
