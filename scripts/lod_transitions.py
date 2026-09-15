#!/usr/bin/env python
"""Render each level-of-detail switch at the distance it would happen.

A sweep says how far away a level stops being visible. What a reviewer wants to
see is the switch itself: the two levels that swap, drawn at the distance the
swap happens, with the difference between them amplified beside them. That is
the frame a player would see, and either it is acceptable or it is not.

    python scripts/lod_transitions.py bust.npz cliff.npz --sheet transitions.png

For every mesh and every adjacent pair of levels, one row: the finer level, the
coarser one, and their difference. Prints what each switch costs in the pixels
it moves, split into the outline and the shading.
"""

import argparse
import os
import sys

import numpy as np


def load(path):
    """``(attributes, indices)`` from a ``.npz`` of glTF-shaped arrays."""
    held = np.load(path)
    return ({name: held[name] for name in held.files if name != 'INDICES'},
            held['INDICES'])


def amplify(difference, gain=6):
    """The difference image, brightened enough to see what moved."""
    return np.clip(difference.astype(np.int32) * gain, 0, 255).astype(np.uint8)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('models', nargs='+')
    parser.add_argument('--levels', type=int, default=5)
    parser.add_argument('--budget', type=float, default=0.10,
                        help='share of the object\'s pixels a switch may change')
    parser.add_argument('--size', type=int, default=384)
    parser.add_argument('--rotation', type=float, default=25.0)
    parser.add_argument('--distance', type=float, default=None,
                        help='render at this distance from the surface, in object '
                             'radii, instead of at the measured transition')
    parser.add_argument('--sheet', default=None)
    args = parser.parse_args(argv)

    from OpenGLContext.meshlod import build_chain, measure_chain
    from OpenGLContext.meshlod.quality import LODProbe, pop_breakdown
    from OpenGLContext.testing.framebuffer_comparison import compare_images
    from OpenGLContext.testing.glcontext import hidden_window

    # Wide enough to place a switch anywhere from touching the surface to far
    # enough that the object is a smudge.
    sweep = [0.002, 0.01, 0.05, 0.2, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0]
    chains = {}
    for path in args.models:
        name = os.path.splitext(os.path.basename(path))[0]
        attributes, indices = load(path)
        chains[name] = build_chain(attributes, indices, levels=args.levels, certify=False)
        print('%-14s %8d triangles -> %s'
              % (name, len(np.asarray(indices).reshape(-1)) // 3,
                 ', '.join(str(level.triangle_count) for level in chains[name])))
    print()

    rows, labels = [], []
    with hidden_window('lod-transitions', size=(args.size, args.size), profile='core'):
        with LODProbe(size=args.size) as probe:
            for name, chain in chains.items():
                reports = measure_chain(chain, probe, sweep, budget=args.budget,
                                        rotation=args.rotation)
                for finer, coarser in zip(reports, reports[1:]):
                    # Where the coarser level becomes acceptable. Judged on the
                    # whole picture where that is reachable and on the outline
                    # alone where it is not, since a shading difference that
                    # never falls under budget would otherwise place every
                    # switch at infinity.
                    at, judged = coarser.safe_at, 'whole'
                    if at == float('inf'):
                        at, judged = coarser.safe_at_outline, 'outline'
                    if at == float('inf'):
                        at, judged = sweep[-1], 'furthest'
                    if args.distance is not None:
                        at, judged = args.distance, 'asked'

                    pictures = [
                        probe.render(level.attributes['POSITION'],
                                     level.attributes['NORMAL'], level.indices,
                                     distance=(1.0 + at) * chain.radius,
                                     radius=chain.radius, centre=chain.centre,
                                     rotation=args.rotation)
                        for level in (chain[finer.level], chain[coarser.level])
                    ]
                    outline, shading = pop_breakdown(*pictures)
                    result = compare_images(pictures[0], pictures[1], threshold=12)
                    rows.append(pictures + [amplify(np.abs(
                        pictures[0].astype(np.int16) - pictures[1].astype(np.int16)))])
                    labels.append((name, finer, coarser, at, judged, outline, shading,
                                   result))

    print('%-14s %-15s %8s  %7s  %7s  %8s' % (
        'mesh', 'switch', 'at', 'outline', 'shading', 'of frame'))
    for name, finer, coarser, at, judged, outline, shading, result in labels:
        print('%-14s %6d->%-8d %7.2fr  %6.2f%%  %6.2f%%  %7.2f%%   (%s)'
              % (name, finer.triangle_count, coarser.triangle_count, at,
                 outline * 100, shading * 100,
                 result.percent_different, judged))

    if args.sheet and rows:
        from PIL import Image

        size = args.size
        sheet = Image.new('RGB', (3 * size, len(rows) * size))
        for index, row in enumerate(rows):
            for column, picture in enumerate(row):
                sheet.paste(Image.fromarray(picture), (column * size, index * size))
        sheet.save(args.sheet)
        print('\ncontact sheet (finer | coarser | difference x6): %s' % (args.sheet,))
    print('\n"at" is the distance from the surface, in object radii, at which the')
    print('coarser level takes over; "outline"/"shading" are what the switch costs')
    print('there, as shares of the object\'s pixels.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
