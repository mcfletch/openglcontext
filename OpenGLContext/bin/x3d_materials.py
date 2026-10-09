#! /usr/bin/env python
"""X3D with X_ITE's nodes: a gallery of material extensions, blend and depth modes on marble.

    oglc-x3d-materials [--directory DIR]

    r      the safety sign's retroreflection off and on
    x      the wax candle's volume scatter off and on
    f      the fogged banner's FogCoordinate off and on
    w      the scene written back as X3D in each encoding, beside the document

:func:`prepare` writes ``x3d_materials.x3d`` and the maps it names, and the
document names X_ITE's component. On a marble floor stand spheres of
PhysicalMaterial, each with one or two of X_ITE's material extension nodes:
clearcoat over red metal, sheen on velvet, iridescence on steel, glass with
transmission and volume, brushed brass with anisotropy, and a wax candle with
diffuse transmission, volume and volume scatter. A gold
SpecularGlossinessMaterial sphere stands beside them. Behind, a row of
sandstone pillars is one InstancedShape, a safety sign is retroreflective
under a lamp beside the eye, a glowing pane adds its colour through a
BlendMode, a marker draws over everything through a DepthMode, and a banner
fades into the fog by its FogCoordinate. A crate wears an ImageTextureAtlas.
docs/x3d.rst describes the nodes.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

import numpy as np

__all__ = ['Showcase', 'atlas', 'document', 'main', 'prepare']

#: The atlas's tiles: across, down, and the slices used.
ATLAS_TILES = (4, 2, 8)


def atlas(size: int = 64) -> np.ndarray:
    """An RGB picture of :data:`ATLAS_TILES` tiles, each a wood grain of another hue"""
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    across, down, _slices = ATLAS_TILES
    rows = []
    for row in range(down):
        tiles = []
        for column in range(across):
            index = row * across + column
            hue = np.array((0.42, 0.25, 0.12)) * (0.6 + 0.1 * index)
            maps = surfaces.wood(size, colour=tuple(np.clip(hue, 0.0, 1.0)), seed=index)
            tiles.append(surfaces.images(maps)[0])
        rows.append(np.concatenate(tiles, axis=1))
    found: np.ndarray = np.concatenate(rows, axis=0)
    return found


def _sphere(x: float, material: str, DEF: str = '') -> str:
    named = ' DEF="%s"' % DEF if DEF else ''
    return ('<Transform translation="%g 0.45 0.6"><Shape><Appearance>%s</Appearance>'
            '<Sphere radius="0.4"/></Shape></Transform>' % (x, material.replace(
                '<PhysicalMaterial', '<PhysicalMaterial%s' % named, 1)))


def document() -> str:
    """The showcase's X3D document"""
    spheres = ''.join((
        _sphere(-3.0, '<PhysicalMaterial baseColor="0.7 0.05 0.04" metallic="1" roughness="0.5">'
                '<ClearcoatMaterialExtension clearcoat="1" clearcoatRoughness="0.05"/>'
                '</PhysicalMaterial>'),
        _sphere(-2.0, '<PhysicalMaterial baseColor="0.15 0.02 0.25" metallic="0" roughness="0.8">'
                '<SheenMaterialExtension sheenColor="0.8 0.5 1" sheenRoughness="0.4"/>'
                '</PhysicalMaterial>'),
        _sphere(-1.0, '<PhysicalMaterial baseColor="0.6 0.6 0.62" metallic="1" roughness="0.25">'
                '<IridescenceMaterialExtension iridescence="1" iridescenceThicknessMaximum="420"/>'
                '</PhysicalMaterial>'),
        _sphere(0.0, '<PhysicalMaterial baseColor="0.9 1 0.95" metallic="0" roughness="0.05">'
                '<TransmissionMaterialExtension transmission="1"/>'
                '<VolumeMaterialExtension thickness="0.6" attenuationDistance="1.2"'
                ' attenuationColor="0.5 0.85 0.7"/><IORMaterialExtension indexOfRefraction="1.5"/>'
                '</PhysicalMaterial>'),
        _sphere(1.0, '<PhysicalMaterial baseColor="0.9 0.65 0.3" metallic="1" roughness="0.45">'
                '<AnisotropyMaterialExtension anisotropyStrength="0.8"/></PhysicalMaterial>'),
        _sphere(2.0, '<PhysicalMaterial baseColor="0.95 0.85 0.65" metallic="0" roughness="0.5">'
                '<DiffuseTransmissionMaterialExtension diffuseTransmission="0.9"'
                ' diffuseTransmissionColor="1 0.8 0.5"/>'
                '<VolumeMaterialExtension thickness="0.8" attenuationDistance="0.15"'
                ' attenuationColor="0.95 0.5 0.25"/>'
                '<VolumeScatterMaterialExtension multiscatterColor="0.9 0.55 0.3"/>'
                '</PhysicalMaterial>', DEF='Wax'),
        '<Transform translation="3 0.45 0.6"><Shape><Appearance>'
        '<SpecularGlossinessMaterial diffuseColor="0.05 0.04 0.02" specularColor="1 0.78 0.34"'
        ' glossiness="0.8"/></Appearance><Sphere radius="0.4"/></Shape></Transform>',
    ))
    return '''<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Immersive" version="4.0">
<head><component name="X_ITE" level="1"/><component name="Texturing3D" level="1"/>
<meta name="title" content="X3D with X_ITE's nodes: materials, modes and instances"/>
<meta name="creator" content="OpenGLContext"/>
<meta name="license" content="BSD-3-Clause"/></head>
<Scene>
<WorldInfo title="X3D with X_ITE's nodes"/>
<NavigationInfo headlight="false" type='"EXAMINE" "ANY"'/>
<Background skyColor="0.3 0.45 0.8 0.8 0.82 0.85" skyAngle="1.45"
  groundColor="0.8 0.8 0.78 0.35 0.32 0.28" groundAngle="1.5"/>
<Fog color="0.8 0.82 0.85" visibilityRange="60"/>
<Viewpoint description="The gallery" position="0 1.6 5.4" orientation="1 0 0 -0.18"/>
<DirectionalLight global="true" direction="-0.4 -0.8 -0.45" intensity="2.2" color="1 0.96 0.9"/>
<DirectionalLight global="true" direction="0.5 -0.3 0.6" intensity="0.5" color="0.6 0.7 0.95"/>
<PointLight DEF="Lamp" global="true" location="0 1.6 5.4" intensity="1.5" attenuation="0 0 0.05"/>
<Shape>
  <Appearance>
    <PhysicalMaterial metallic="0" roughness="1">
      <ImageTexture containerField="baseTexture" url='"marble_base.png"'/>
      <ImageTexture containerField="metallicRoughnessTexture" url='"marble_mr.png"'/>
      <ImageTexture containerField="normalTexture" url='"marble_normal.png"'/>
    </PhysicalMaterial>
    <TextureTransform scale="5 4"/>
  </Appearance>
  <IndexedTriangleSet index="0 1 2 0 2 3" solid="false">
    <Coordinate point="-5 0 -4, -5 0 4, 5 0 4, 5 0 -4"/>
    <Normal vector="0 1 0, 0 1 0, 0 1 0, 0 1 0"/>
    <TextureCoordinate point="0 1, 0 0, 1 0, 1 1"/>
  </IndexedTriangleSet>
</Shape>
{spheres}
<InstancedShape DEF="Pillars" translations="-4 1 -2.5, -2 1 -2.5, 0 1 -2.5, 2 1 -2.5, 4 1 -2.5"
  rotations="0 1 0 0, 0 1 0 0.4, 0 1 0 0.8, 0 1 0 1.2, 0 1 0 1.6">
  <Appearance>
    <PhysicalMaterial metallic="0" roughness="0.9">
      <ImageTexture containerField="baseTexture" url='"sandstone_base.png"'/>
      <ImageTexture containerField="normalTexture" url='"sandstone_normal.png"'/>
    </PhysicalMaterial>
  </Appearance>
  <Box size="0.5 2 0.5"/>
</InstancedShape>
<Transform translation="-3 1.2 -1.4" rotation="0 1 0 0.5">
  <Shape>
    <Appearance>
      <PhysicalMaterial DEF="Sign" baseColor="1 0.45 0.05" metallic="0" roughness="0.35">
        <RetroreflectionMaterialExtension retroreflection="1"/>
      </PhysicalMaterial>
    </Appearance>
    <Box size="1.2 0.8 0.05"/>
  </Shape>
</Transform>
<Transform translation="-0.9 1.3 -1.2">
  <Shape>
    <Appearance>
      <UnlitMaterial emissiveColor="0.1 0.35 0.9"/>
      <BlendMode sourceColorFactor="ONE" destinationColorFactor="ONE"/>
    </Appearance>
    <Box size="1 0.9 0.05"/>
  </Shape>
</Transform>
<Transform translation="0.9 2.4 -1.8">
  <Shape>
    <Appearance>
      <UnlitMaterial emissiveColor="1 0.85 0.1"/>
      <DepthMode depthTest="false"/>
    </Appearance>
    <Cone bottomRadius="0.15" height="0.3"/>
  </Shape>
</Transform>
<Transform translation="2.9 1.6 -1.2">
  <Shape>
    <Appearance><Material diffuseColor="0 0 0" emissiveColor="0.75 0.12 0.1"/></Appearance>
    <IndexedTriangleSet index="0 1 2 0 2 3" solid="false">
      <Coordinate point="-0.8 -0.5 0, 0.8 -0.5 0, 0.8 0.5 0, -0.8 0.5 0"/>
      <FogCoordinate DEF="BannerFog" depth="0 0.95 0.95 0"/>
    </IndexedTriangleSet>
  </Shape>
</Transform>
<Transform translation="1.6 0.3 -0.6" rotation="0 1 0 0.6">
  <Shape>
    <Appearance>
      <Material/>
      <ImageTextureAtlas url='"atlas.png"' slicesOverX="{across}" slicesOverY="{down}"
        numberOfSlices="{slices}"/>
    </Appearance>
    <Box size="0.6 0.6 0.6"/>
  </Shape>
</Transform>
</Scene>
</X3D>
'''.format(spheres=spheres, across=ATLAS_TILES[0], down=ATLAS_TILES[1], slices=ATLAS_TILES[2])


def prepare(directory: str) -> str:
    """The document and the maps it names, written to `directory`; the document's path"""
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import staged_file  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    os.makedirs(directory, exist_ok=True)
    for name, maps in (('marble', surfaces.marble_tiles(256, tiles=2)),
                       ('sandstone', surfaces.sandstone(256))):
        for part, pixels in zip(('base', 'mr', 'normal'), surfaces.images(maps), strict=True):
            with staged_file(os.path.join(directory, '%s_%s.png' % (name, part))) as handle:
                Image.fromarray(pixels, 'RGB').save(handle, 'PNG')
    with staged_file(os.path.join(directory, 'atlas.png')) as handle:
        Image.fromarray(atlas(), 'RGB').save(handle, 'PNG')
    target = os.path.join(directory, 'x3d_materials.x3d')
    with staged_file(target) as handle:
        handle.write(document().encode('utf-8'))
    return target


class Showcase:
    """The materials showcase with no window: what the command, its tutorial and its tests share

    ``scene`` is the document read by the engine's loader.
    """

    KEYS: ClassVar[dict[str, str]] = {
        'r': "the safety sign's retroreflection off and on",
        'x': "the wax candle's volume scatter off and on",
        'f': "the banner's FogCoordinate off and on",
        'w': 'the scene written back as X3D in each encoding',
    }

    def __init__(self, directory: str) -> None:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory)
        self.scene = Loader.load(self.path)
        self.sign = self.scene.getDEF('Sign')
        self.wax = self.scene.getDEF('Wax')
        self.fog = self.scene.getDEF('BannerFog')
        self._scatter = list(self.wax.extensions)
        self._depths = list(self.fog.depth)

    def press(self, key: str) -> str:
        """Answer a key; what it did, for the console"""
        if key == 'r':
            self.sign.retroreflection = 0.0 if self.sign.retroreflection else 1.0
            return 'the sign is %s' % ('retroreflective' if self.sign.retroreflection
                                       else 'ordinary paint')
        if key == 'x':
            from vrml.x3d import xite  # noqa: PLC0415 kept with its use
            kept = [item for item in self.wax.extensions
                    if not isinstance(item, xite.VolumeScatterMaterialExtension)]
            scattering = len(kept) == len(self.wax.extensions)
            self.wax.extensions = self._scatter if scattering else kept
            return 'the candle %s light beneath its surface' % (
                'scatters' if scattering else 'does not scatter')
        if key == 'f':
            fogged = not len(self.fog.depth)
            self.fog.depth = self._depths if fogged else []
            return 'the banner is fogged by %s' % ('its depths' if fogged else 'distance')
        if key == 'w':
            from vrml import x3d  # noqa: PLC0415 kept with its use
            written = []
            for suffix in ('x3d', 'x3dv', 'x3dj'):
                path = os.path.join(self.directory, 'written.%s' % (suffix,))
                x3d.dump(self.scene, path)
                written.append('%s (%d bytes)' % (os.path.basename(path), os.path.getsize(path)))
            return 'wrote ' + ', '.join(written)
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line"""
        return '\n'.join('  %s  %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the showcase in a window"""
    parser = argparse.ArgumentParser(
        prog='oglc-x3d-materials', description=(__doc__ or '').split('\n')[0],
        epilog=Showcase.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document and its files are written '
                        '(default: the user cache directory)')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-materials')
    base: Any = testingcontext.getInteractive()

    class ShowcaseContext(base):                 # pragma: no cover - needs a window
        def OnInit(self) -> None:
            self.showcase = Showcase(directory)
            self.sg = self.showcase.scene
            for key in Showcase.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print(Showcase.help())

        def OnKey(self, event: Any) -> None:
            said = self.showcase.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(True)

    ShowcaseContext.ContextMainLoop(definition=ContextDefinition(
        title="X3D with X_ITE's nodes", size=(1280, 720), renderer='pbr'))
    return 0


if __name__ == '__main__':  # pragma: no cover - the command line
    sys.exit(main())
