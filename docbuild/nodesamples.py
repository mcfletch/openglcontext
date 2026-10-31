"""The sample world of each node: ``docs/samples/nodes/<Node>.x3d``.

A sample is a small X3D XML document written by hand, with comments saying what
it shows.  Where the node is in VRML97 the same scene is also committed as
``<Node>.wrl``, converted from the ``.x3d`` by :func:`vrml97_text` so the two
cannot differ.  What a sample says about itself is in the ``head`` of its
document:

``title``, ``description``
    what the page for the node calls it and says about it.
``sample:frames``
    the frames drawn, on the capture clock, before the reference render is
    read; the moment a circuit of sensors and interpolators has reached.
``sample:interactive``
    ``true`` where the sample is for a reader to operate (click it, drag it),
    which is when a page also embeds a live view.

    python -m docbuild.nodesamples            # the .wrl files out of date, and the nodes with no sample
    python -m docbuild.nodesamples --write    # bring the .wrl files up to date

The build gives each node's class page a *Sample world* block: the reference
render, and the two sources included from ``docs/samples/nodes`` (:func:`section`,
:func:`class_sections`).  The renders are copied from the baselines to
``docs/images/samples`` by :func:`publish_images`.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import shutil
import sys
from collections.abc import Callable, Collection, Iterable

from OpenGLContext import atomicfiles
from OpenGLContext.bin.x3d_regression import SAMPLE_FRAMES

__all__ = [
    'SAMPLES',
    'Sample',
    'class_sections',
    'find',
    'problems',
    'publish_images',
    'section',
    'stale',
    'unsampled',
    'vrml97_nodes',
    'vrml97_text',
    'write',
]

log = logging.getLogger('nodesamples')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Where the samples are.
SAMPLES = os.path.join(HERE, 'docs', 'samples', 'nodes')

#: Where the pages read the renders: ``docs/images/samples``, which a build writes.
IMAGES = os.path.join(HERE, 'docs', 'images', 'samples')

#: What the loader says of a sample that is not a fault in it: the Script
#: sample holds a program the engine reads and does not run.
EXPECTED = ('scripts are kept and not run',)

#: The ``head`` ``meta`` name that says a sample is for a reader to operate.
INTERACTIVE = 'sample:interactive'


@dataclasses.dataclass(frozen=True)
class Sample:
    """One node's sample document."""

    #: The node the sample is for.
    node: str
    #: The ``.x3d`` document.
    path: str

    @property
    def wrl(self) -> str:
        """Where the VRML97 form of the document is."""
        return os.path.splitext(self.path)[0] + '.wrl'

    def meta(self) -> dict[str, str]:
        """The ``head`` ``meta`` entries of the document, by name."""
        from vrml.x3d import files  # noqa: PLC0415 only when a sample is read

        return {item.name: item.content for item in files.load(self.path).meta}

    @property
    def frames(self) -> int | None:
        """The frames to draw before the reference render, or None for the tool's own."""
        text = self.meta().get(SAMPLE_FRAMES)
        return int(text) if text else None

    @property
    def interactive(self) -> bool:
        return self.meta().get(INTERACTIVE, '').lower() == 'true'


def find(directory: str = SAMPLES) -> list[Sample]:
    """The samples in ``directory``, by node name."""
    if not os.path.isdir(directory):
        return []
    return [
        Sample(os.path.splitext(name)[0], os.path.join(directory, name))
        for name in sorted(os.listdir(directory))
        if name.endswith('.x3d')
    ]


def vrml97_nodes() -> frozenset[str]:
    """The nodes of VRML97."""
    from vrml.x3d import dialects, nodes  # noqa: PLC0415 only when asked

    tables = dialects.DIALECTS['2.0'].tables()
    return frozenset(
        name
        for name in dir(nodes)
        if isinstance(getattr(nodes, name), type) and tables.has_node(name)
    )


def unsampled(samples: Iterable[Sample], wanted: Iterable[str] | None = None) -> list[str]:
    """The nodes of ``wanted`` (VRML97's by default) with no sample, by name."""
    have = {sample.node for sample in samples}
    return sorted(set(vrml97_nodes() if wanted is None else wanted) - have)


def problems(sample: Sample) -> list[str]:
    """What the loader reports against the sample other than information, as messages."""
    from vrml.x3d import files  # noqa: PLC0415 only when a sample is read

    return [
        'line %d: %s: %s' % (problem.line, problem.severity, problem.message)
        for problem in files.load(sample.path).problems
        if problem.severity != 'info' and not any(note in problem.message for note in EXPECTED)
    ]


def vrml97_text(sample: Sample) -> str | None:
    """The sample as a VRML97 document, or None where its node is not in VRML97.

    Raises ValueError where the document holds something VRML97 cannot say.
    """
    from vrml.x3d import files  # noqa: PLC0415 only when a sample is read

    if sample.node not in vrml97_nodes():
        return None
    return files.dumps(files.load(sample.path), 'classic', '2.0')


def stale(samples: Iterable[Sample]) -> list[Sample]:
    """The samples whose ``.wrl`` is missing or is not what the ``.x3d`` converts to."""
    out = []
    for sample in samples:
        text = vrml97_text(sample)
        if text is None:
            continue
        try:
            with open(sample.wrl, encoding='utf-8') as handle:
                current = handle.read()
        except OSError:
            current = None
        if current != text:
            out.append(sample)
    return out


def write(samples: Iterable[Sample]) -> list[Sample]:
    """Write the ``.wrl`` of each sample out of date; the samples written."""
    changed = stale(samples)
    for sample in changed:
        text = vrml97_text(sample)
        assert text is not None  # noqa: S101 stale() lists only samples that convert
        atomicfiles.write_text(sample.wrl, text)
    return changed


def publish_images(baselines: str, destination: str = IMAGES) -> set[str]:
    """Copy each sample's baseline render to ``<destination>/<Node>.png``; the nodes copied.

    A file under 1 KiB is not a render: a checkout without its LFS objects holds a
    text pointer where the picture is.
    """
    found: set[str] = set()
    if not os.path.isdir(baselines):
        return found
    os.makedirs(destination, exist_ok=True)
    for name in sorted(os.listdir(baselines)):
        if not (name.startswith('Samples.') and name.endswith('.png')):
            continue
        source = os.path.join(baselines, name)
        if os.path.getsize(source) < 1024 and not _is_png(source):
            continue
        node = name[len('Samples.') : -len('.png')]
        target = os.path.join(destination, node + '.png')
        if not os.path.exists(target) or _bytes(target) != _bytes(source):
            atomicfiles.copy_file(source, target)
        found.add(node)
    return found


def _bytes(path: str) -> bytes:
    with open(path, 'rb') as handle:
        return handle.read()


def _is_png(path: str) -> bool:
    return _bytes(path)[:8] == b'\x89PNG\r\n\x1a\n'


def section(sample: Sample, image: bool, source: str = '/samples/nodes', images: str = '/images/samples') -> list[str]:
    """The reST block showing ``sample`` on its node's page, in a list of one.

    ``image`` is whether there is a render to show.  ``source`` and ``images``
    are where the page finds the sample files and the renders, from the root of
    the documentation.
    """
    meta = sample.meta()
    out = ['.. rubric:: Sample world', '', meta.get('description', '')]
    if image:
        out += ['', '.. image:: %s/%s.png' % (images, sample.node), '   :alt: %s' % (meta.get('title', sample.node),), '   :width: 480px']
    if sample.interactive:
        out += ['', 'The sample is one to operate: click it or drag it in a viewer such as ``oglc-view``.']
    for path, language in ((sample.path, 'xml'), (sample.wrl, 'text')):
        if os.path.exists(path):
            name = os.path.basename(path)
            out += ['', '.. literalinclude:: %s/%s' % (source, name), '   :language: %s' % (language,), '   :caption: %s' % (name,)]
    return ['\n'.join(out)]


def class_sections(samples: Iterable[Sample], images: Collection[str] = ()) -> Callable[[type], list[str]]:
    """The callable PyOpenGL's ``directdocs`` takes as ``class_sections``.

    It answers the *Sample world* block for the class of a node that has a
    sample, and nothing for any other class.  ``images`` names the nodes with a render.
    """
    from docbuild import nodeusage  # noqa: PLC0415 only when the pages are written

    by_node = {sample.node: sample for sample in samples}

    def sections(cls: type) -> list[str]:
        node = nodeusage.node_name(cls)
        if node is None or node not in by_node:
            return []
        return section(by_node[node], node in images)

    return sections


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--write', action='store_true', help='write the .wrl files that are out of date')
    parser.add_argument('--directory', default=SAMPLES, help='where the samples are (default: %(default)s)')
    options = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    samples = find(options.directory)
    if options.write:
        for sample in write(samples):
            print('wrote %s' % (sample.wrl,))
        return 0
    out = stale(samples)
    for sample in out:
        print('out of date: %s' % (sample.wrl,))
    missing = unsampled(samples)
    if missing:
        print('no sample: %s' % (', '.join(missing),))
    return 1 if out else 0


if __name__ == '__main__':
    sys.exit(main())
