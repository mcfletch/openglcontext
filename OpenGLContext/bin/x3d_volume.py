#! /usr/bin/env python
"""X3D volume rendering: three CT scans of an ammonite, each drawn its own way.

    oglc-x3d-volume [--directory DIR]

    1-9, 0  the left specimen's render style: 1 opacity map, 2 boundary
            enhancement, 3 cartoon, 4 composed edge and silhouette, 5 edge
            enhancement, 6 maximum intensity projection, 7 shaded,
            8 silhouette enhancement, 9 tone mapped, 0 blended with
            itself tone-mapped
    s       the centre specimen's sediment shown or hidden
    i       the right specimen's inner surface value stepped

The document is ``x3d_volume.x3d``, shipped with this module. Three marble
plinths each carry a scan on a steel rod that passes through it:

- on the left a VolumeData whose style is an OpacityMapVolumeStyle with a
  transfer function, which hides the sediment's density and colours the
  shell, composed with a SilhouetteEnhancementVolumeStyle;
- in the centre a SegmentedVolumeData, turning: the shell wall shaded and
  lit, the septa tone-mapped, the siphuncle edge-enhanced and the sediment
  boundary-enhanced;
- on the right an IsoSurfaceVolumeData with two surfaces: the sediment's,
  silhouette-enhanced and translucent, and the shell's, cartoon-shaded.

The scans are generated (:func:`ammonite`): a planispiral shell growing
threefold each whorl, its septa and siphuncle, sediment in its living
chamber and last chambers, then blurred over a voxel and given a scanner's
noise, as a CT scan of a fossil is. :func:`prepare` writes them as NRRD
files beside a copy of the document, with the transfer function and the
surface maps it names. docs/x3d.rst describes the nodes.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from collections.abc import Callable, Sequence
from typing import Any, ClassVar, Optional

import numpy as np

__all__ = ['DOCUMENT', 'LABELS', 'STYLES', 'VolumeScene', 'ammonite', 'blurred', 'main',
           'prepare', 'transfer_function']

#: The X3D document the scene is read from.
DOCUMENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x3d_volume.x3d')
#: The segment identifiers :func:`ammonite` labels its voxels with.
LABELS = {'air': 0, 'wall': 1, 'septum': 2, 'siphuncle': 3, 'sediment': 4}
#: Each material's density, 0 to 1: the scan's value before blur and noise.
DENSITY = {'wall': 0.86, 'septum': 0.74, 'siphuncle': 0.58, 'sediment': 0.34}
#: The scans' size in voxels: depth, height, width.
SHAPE = (80, 160, 160)


def blurred(values: np.ndarray, sigma: float) -> np.ndarray:
    """``values`` blurred by a Gaussian ``sigma`` voxels wide along each axis

    Separable, over five taps an axis; the edges repeat.
    """
    taps = np.arange(-2, 3, dtype=np.float64)
    weights = np.exp(-0.5 * (taps / max(float(sigma), 1e-6)) ** 2)
    weights /= weights.sum()
    found = np.asarray(values, np.float32)
    for axis in range(found.ndim):
        padded = np.pad(found, [(2, 2) if index == axis else (0, 0)
                                for index in range(found.ndim)], mode='edge')
        size = found.shape[axis]
        found = sum((float(weight) * np.take(padded, np.arange(offset, offset + size), axis=axis)
                     for offset, weight in enumerate(weights)), np.zeros_like(found))
    return found


def ammonite(shape: Sequence[int] = SHAPE, seed: int = 3, whorls: float = 3.2,
             septa: int = 12, living: float = 0.4,
             noise: float = 0.012) -> tuple[np.ndarray, np.ndarray]:
    """A CT scan of an ammonite: ``(voxels, labels)``, two uint8 ``shape`` arrays

    The shell coils in the volume's XY plane, a logarithmic spiral growing
    three times wider each whorl, ``whorls`` of them. Behind the living
    chamber (the last ``living`` of a whorl) ``septa`` curved partitions a
    whorl divide it into chambers, threaded by the siphuncle. Sediment fills
    the living chamber and the lower part of the last three chambers.
    ``labels`` holds :data:`LABELS`; ``voxels`` the densities, blurred over
    a voxel with Gaussian noise of ``noise``.
    """
    depth, height, width = (int(value) for value in shape)
    grow = math.log(3.0) / (2.0 * math.pi)
    end = 2.0 * math.pi * whorls
    a = 0.94 / math.exp(grow * end)

    def axis(count: int) -> np.ndarray:
        return (np.arange(count) + 0.5) / count * 2.0 - 1.0
    z, y, x = np.meshgrid(axis(depth) * depth / width, axis(height) * height / width,
                          axis(width), indexing='ij')
    rho = np.hypot(x, y)
    phi = np.arctan2(y, x) % (2.0 * math.pi)
    # The whorl a point is in: the angle theta = phi + 2 pi k whose tube spans
    # r(theta - 2 pi) to r(theta), where r = a exp(grow theta).
    spiral = np.log(np.maximum(rho, 1e-6) / a) / grow
    theta = phi + 2.0 * math.pi * np.ceil((spiral - phi) / (2.0 * math.pi))
    outer = a * np.exp(grow * theta)
    centre = outer * 2.0 / 3.0
    half = outer / 3.0
    tall = 1.15 * half
    across = np.sqrt(((rho - centre) / half) ** 2 + (z / tall) ** 2)
    shell = (theta <= end) & (theta > 0.6)
    thick = 0.035 * half + 0.008
    wall = shell & (np.abs(across - 1.0) * half < thick)
    inside = shell & (across < 1.0) & ~wall
    chambered = theta < end - 2.0 * math.pi * living
    spacing = 2.0 * math.pi / septa
    along = (theta - 0.35 * spacing * (1.0 - np.minimum(across, 1.0) ** 2)) / spacing
    septum = inside & chambered & (np.abs(along - np.round(along)) * spacing * rho < 0.6 * thick)
    siphuncle = inside & chambered & (
        np.abs(np.hypot(rho - centre, z) - 0.09 * half) < 0.4 * thick)
    level = np.sin(theta * 1.7 + 0.5) * 0.4 * tall
    sediment = inside & (~chambered | ((theta > end - 2.0 * math.pi * living - 3 * spacing)
                                       & (z < level)))
    labels = np.zeros((depth, height, width), np.uint8)
    for name, where in (('sediment', sediment), ('septum', septum),
                        ('siphuncle', siphuncle), ('wall', wall)):
        labels[where] = LABELS[name]
    density = np.zeros(labels.shape, np.float32)
    for name, value in DENSITY.items():
        density[labels == LABELS[name]] = value
    # The ribs across the shell, as a little more and less of it.
    ribbed = labels == LABELS['wall']
    density[ribbed] += (0.06 * np.sin(theta * 26.0))[ribbed].astype(np.float32)
    density = blurred(density, 0.8)
    density += np.random.default_rng(seed).normal(0.0, noise, density.shape).astype(np.float32)
    voxels = np.clip(np.round(density * 255.0), 0, 255).astype(np.uint8)
    return voxels, labels


def transfer_function(size: int = 256) -> np.ndarray:
    """The left specimen's transfer function: ``(1, size, 4)`` RGBA uint8

    Transparent to the sediment's density, a translucent amber through the
    siphuncle's and septa's, and an opaque ivory at the shell wall's.
    """
    value = np.linspace(0.0, 1.0, size)
    keys = [(0.0, (0.0, 0.0, 0.0, 0.0)), (0.45, (0.30, 0.14, 0.04, 0.0)),
            (0.58, (0.78, 0.42, 0.12, 0.10)), (0.72, (0.93, 0.70, 0.40, 0.35)),
            (0.84, (0.98, 0.94, 0.84, 0.95)), (1.0, (1.0, 0.98, 0.94, 1.0))]
    stops = np.array([key for key, _colour in keys])
    colours = np.array([colour for _key, colour in keys])
    table = np.stack([np.interp(value, stops, colours[:, channel]) for channel in range(4)], -1)
    return np.round(table * 255.0).astype(np.uint8)[None]


def _surface(name: str) -> Any:
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    if name == 'marble':
        return surfaces.checkered_marble(256, tiles=2)
    if name == 'steel':
        return surfaces.brushed_metal(256)
    return surfaces.sandstone(256)


def prepare(directory: str, force: bool = False, shape: Sequence[int] = SHAPE) -> str:
    """The document, copied to `directory` with the scans and images it names

    Files already there are kept unless `force`. Returns the copy's path.
    """
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import copy_file, staged_file  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.textureimages import nrrd_bytes  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 only when written
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, os.path.basename(DOCUMENT))
    copy_file(DOCUMENT, target)
    for name in ('marble', 'sandstone', 'steel'):
        paths = [os.path.join(directory, '%s_%s.png' % (name, part))
                 for part in ('base', 'mr', 'normal')]
        if force or not all(os.path.exists(path) for path in paths):
            for path, pixels in zip(paths, surfaces.images(_surface(name)), strict=True):
                with staged_file(path) as handle:
                    Image.fromarray(pixels, 'RGB').save(handle, 'PNG')
    scans = [os.path.join(directory, name) for name in ('ammonite.nrrd', 'ammonite_segments.nrrd')]
    if force or not all(os.path.exists(path) for path in scans):
        for path, volume in zip(scans, ammonite(shape), strict=True):
            with staged_file(path) as handle:
                handle.write(nrrd_bytes(volume))
    path = os.path.join(directory, 'ammonite_transfer.png')
    if force or not os.path.exists(path):
        with staged_file(path) as handle:
            Image.fromarray(transfer_function(), 'RGBA').save(handle, 'PNG')
    return target


def _styles() -> dict[str, tuple[str, Callable[[Any], Any]]]:
    """The left specimen's styles by key: a description, and a maker given the scene"""
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 nodes only when the scene is made

    def table(scene: Any) -> Any:
        return scene.getDEF('Transfer')
    return {
        '1': ('opacity map', lambda scene: x3d.OpacityMapVolumeStyle(transferFunction=table(scene))),
        '2': ('boundary enhancement', lambda scene: x3d.BoundaryEnhancementVolumeStyle(
            boundaryOpacity=1.0, retainedOpacity=0.1, opacityFactor=1.0)),
        '3': ('cartoon', lambda scene: x3d.CartoonVolumeStyle(
            colorSteps=5, orthogonalColor=(1.0, 0.93, 0.78, 1.0),
            parallelColor=(0.35, 0.12, 0.05, 1.0))),
        '4': ('composed edge and silhouette', lambda scene: x3d.ComposedVolumeStyle(renderStyle=[
            x3d.OpacityMapVolumeStyle(transferFunction=table(scene)),
            x3d.EdgeEnhancementVolumeStyle(edgeColor=(0.25, 0.05, 0.0, 1.0),
                                           gradientThreshold=0.6),
            x3d.SilhouetteEnhancementVolumeStyle(silhouetteBoundaryOpacity=1.0,
                                                 silhouetteRetainedOpacity=0.3,
                                                 silhouetteSharpness=4.0)])),
        '5': ('edge enhancement', lambda scene: x3d.EdgeEnhancementVolumeStyle(
            edgeColor=(0.6, 0.1, 0.0, 1.0), gradientThreshold=0.5)),
        '6': ('maximum intensity projection', lambda scene: x3d.ProjectionVolumeStyle()),
        '7': ('shaded', lambda scene: x3d.ShadedVolumeStyle(lighting=True, material=x3d.Material(
            diffuseColor=(0.95, 0.86, 0.72), specularColor=(0.6, 0.6, 0.6), shininess=0.4,
            ambientIntensity=0.2))),
        '8': ('silhouette enhancement', lambda scene: x3d.SilhouetteEnhancementVolumeStyle(
            silhouetteBoundaryOpacity=1.0, silhouetteRetainedOpacity=0.15,
            silhouetteSharpness=3.0)),
        '9': ('tone mapped', lambda scene: x3d.ToneMappedVolumeStyle(
            warmColor=(1.0, 0.7, 0.3, 0.0), coolColor=(0.1, 0.3, 0.7, 0.0))),
        '0': ('blended', lambda scene: x3d.BlendedVolumeStyle(
            voxels=scene.getDEF('Scan'), weightConstant1=0.6, weightConstant2=0.4,
            renderStyle=x3d.ToneMappedVolumeStyle(warmColor=(1.0, 0.3, 0.2, 0.0),
                                                  coolColor=(0.2, 0.1, 0.5, 0.0)))),
    }


#: The left specimen's render styles, by key: what each is.
STYLES = {key: name for key, (name, _make) in _styles().items()}


class VolumeScene:
    """The scene with no window: what the demo and its tests share

    ``scene`` is the document read by the engine's loader.
    """

    KEYS: ClassVar[dict[str, str]] = dict(
        {key: 'the left specimen drawn by %s' % (name,) for key, name in STYLES.items()},
        s="the centre specimen's sediment shown or hidden",
        i="the right specimen's inner surface value stepped")

    #: The inner surface values ``i`` steps through.
    INNER = (0.2, 0.28, 0.36)

    def __init__(self, directory: str, shape: Sequence[int] = SHAPE) -> None:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory, shape=shape)
        self.scene = Loader.load(self.path)
        self._styles = _styles()

    def node(self, name: str) -> Any:
        """The node the document names `name`"""
        return self.scene.getDEF(name)

    def press(self, key: str) -> str:
        """Answer a key; what it did, for the console"""
        if key in self._styles:
            name, make = self._styles[key]
            self.node('Study').renderStyle = make(self.scene)
            return 'left specimen: %s' % (name,)
        if key == 's':
            sections = self.node('Sections')
            enabled = list(sections.segmentEnabled)
            enabled[LABELS['sediment']] = not enabled[LABELS['sediment']]
            sections.segmentEnabled = enabled
            return 'sediment %s' % ('shown' if enabled[LABELS['sediment']] else 'hidden')
        if key == 'i':
            surfaces = self.node('Surfaces')
            values = list(surfaces.surfaceValues)
            at = min(range(len(self.INNER)), key=lambda index: abs(self.INNER[index] - values[0]))
            values[0] = self.INNER[(at + 1) % len(self.INNER)]
            surfaces.surfaceValues = values
            return 'inner surface at %.2f' % (values[0],)
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line"""
        return '\n'.join('  %s  %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the scene in a window"""
    parser = argparse.ArgumentParser(
        prog='oglc-x3d-volume', description=__doc__.split('\n')[0],
        epilog=VolumeScene.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document, its scans and images are '
                        'written (default: the user cache directory)')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-volume')
    base: Any = testingcontext.getInteractive()

    class VolumeContext(base):                   # pragma: no cover - needs a window
        def OnInit(self) -> None:
            self.volumes = VolumeScene(directory)
            self.sg = self.volumes.scene
            for key in VolumeScene.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print(VolumeScene.help())

        def OnKey(self, event: Any) -> None:
            said = self.volumes.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(1)

    definition = ContextDefinition(title='OpenGLContext X3D volumes', size=(1280, 720),
                                   renderer='pbr')
    VolumeContext.ContextMainLoop(definition=definition)
    return 0


if __name__ == '__main__':
    sys.exit(main())
