#! /usr/bin/env python
"""X3D Geospatial: an alpine valley placed on the Earth.

    oglc-x3d-geospatial [--directory DIR]

    g      where the viewer is, in latitude, longitude and height
    w      the scene written back as X3D in each encoding, beside the document

Click the ground to have its latitude, longitude and height printed.

:func:`prepare` writes ``x3d_geospatial.x3d`` and the files it names: a
valley four and a half kilometres across near 46.55 N 7.98 E, its heights
from the engine's ridged noise. From afar it is one coarse
`GeoElevationGrid`; within two and a half kilometres a `GeoLOD` reads four
finer tiles, each with its own colour and normal maps. Huts stand on the
valley floor, each placed by a `GeoLocation`; a balloon drifts along a loop
a `GeoPositionInterpolator` makes round the globe; three `GeoViewpoint`s
look across it, one of them given in UTM. A `GeoProximitySensor` reports
where the viewer is and a `GeoTouchSensor` where the ground is clicked.
docs/x3d.rst describes the nodes.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

import numpy as np

__all__ = ['AREA', 'Showcase', 'colour_map', 'heights', 'main', 'prepare']

#: The valley: (south latitude, west longitude, north latitude, east longitude), degrees.
AREA = (46.53, 7.95, 46.57, 8.01)
#: Where the scene's origin is: (latitude, longitude, height), with +Y up there.
ORIGIN = (46.55, 7.98, 1000.0)
#: Points a side of the coarse grid, and of each of the four fine tiles.
COARSE, FINE = 33, 49
#: The hamlet on the valley floor: each hut's (latitude, longitude, turn in radians).
HUTS = ((46.5450, 7.9858, 0.3), (46.5456, 7.9866, -0.2), (46.5461, 7.9855, 1.1),
        (46.5447, 7.9871, 0.6), (46.5466, 7.9864, -0.5), (46.5440, 7.9862, 1.4))
#: Where the viewpoint given in UTM stands, 30 metres above the ground: (latitude, longitude).
LOOKOUT = (46.5418, 7.9868)
#: The balloon's loop over the hamlet: (latitude, longitude, height) it passes through.
BALLOON = ((46.546, 7.983, 1180.0), (46.552, 7.988, 1300.0), (46.558, 7.982, 1350.0),
           (46.552, 7.976, 1250.0), (46.546, 7.983, 1180.0))


def heights(latitude: np.ndarray, longitude: np.ndarray) -> np.ndarray:
    """The ground's height above the ellipsoid, metres, at each latitude and longitude"""
    from OpenGLContext import noise  # noqa: PLC0415 NumPy work only when written
    south, west, north, east = AREA
    across = (np.asarray(longitude, 'd') - west) / (east - west)
    along = (np.asarray(latitude, 'd') - south) / (north - south)
    river = 0.5 + 0.08 * np.sin(along * 2.0 * math.pi) + 0.04 * np.sin(along * 7.0)
    side = np.clip((np.abs(across - river) - 0.04) / 0.42, 0.0, 1.0)
    walls = side * side * (3.0 - 2.0 * side)
    ridges = noise.ridged(across * 6.0, along * 6.0, seed=11)
    rough = noise.fbm(across * 40.0, along * 40.0, seed=3, octaves=3)
    found: np.ndarray = 1000.0 + 1300.0 * walls + 450.0 * ridges * walls + 12.0 * rough
    return found


def _grid(south: float, west: float, north: float, east: float,
          count: int) -> tuple[np.ndarray, np.ndarray]:
    """(latitudes, longitudes), (count, count), row by row from the south-west"""
    latitude, longitude = np.meshgrid(np.linspace(south, north, count),
                                      np.linspace(west, east, count), indexing='ij')
    return latitude, longitude


def colour_map(ground: np.ndarray) -> np.ndarray:
    """An sRGB image of the ground (rows south to north): meadow, scree, rock, snow by height and slope"""
    rise = np.hypot(*np.gradient(ground))
    slope = np.clip(rise / max(float(rise.max()), 1e-6), 0.0, 1.0)
    height = np.clip((ground - 1000.0) / 1700.0, 0.0, 1.0)
    meadow, scree = np.array([0.30, 0.42, 0.16]), np.array([0.52, 0.49, 0.44])
    rock, snow = np.array([0.38, 0.36, 0.34]), np.array([0.93, 0.94, 0.96])
    rocky = np.clip(slope * 1.6 + height * 0.6 - 0.25, 0.0, 1.0)[..., None]
    base = meadow * (1 - rocky) + (scree * 0.5 + rock * 0.5) * rocky
    snowy = np.clip((height - 0.72) * 6.0 - slope * 1.5, 0.0, 1.0)[..., None]
    found = base * (1 - snowy) + snow * snowy
    return np.asarray(np.clip(found ** (1 / 2.2), 0, 1) * 255 + 0.5, np.uint8)


def _blurred(values: np.ndarray, radius: int) -> np.ndarray:
    """`values` averaged over a square `radius` texels each way, edges repeated"""
    kernel = np.full(2 * radius + 1, 1.0 / (2 * radius + 1))
    padded = np.pad(np.asarray(values, 'd'), radius, mode='edge')
    rows = np.apply_along_axis(np.convolve, 1, padded, kernel, mode='valid')
    found: np.ndarray = np.apply_along_axis(np.convolve, 0, rows, kernel, mode='valid')
    return found


def _write_image(path: str, pixels: np.ndarray) -> None:
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import staged_file  # noqa: PLC0415 kept with its use
    with staged_file(path) as handle:
        # X3D puts texture coordinate (0, 0) at an image's lower left.
        Image.fromarray(np.ascontiguousarray(pixels[::-1]), 'RGB').save(handle, 'PNG')


def _numbers(values: Any) -> str:
    return ' '.join('%.6g' % value for value in np.asarray(values, 'd').ravel())


ORIGIN_DEF = ('<GeoOrigin DEF="Origin" containerField="geoOrigin" geoCoords="%s" '
              'rotateYUp="true"/>' % _numbers(ORIGIN))
ORIGIN_USE = '<GeoOrigin USE="Origin" containerField="geoOrigin"/>'


def _ground(directory: str, name: str, bounds: Sequence[float], count: int) -> str:
    """A GeoElevationGrid over `bounds` with its maps written beside it, as X3D"""
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    south, west, north, east = bounds
    latitude, longitude = _grid(south, west, north, east, count)
    ground = heights(latitude, longitude)
    fine = _grid(south, west, north, east, 256)
    pixels = heights(*fine)
    _write_image(os.path.join(directory, '%s_colour.png' % name), colour_map(pixels))
    # The detail finer than the grid's spacing, in texels: the grid's own
    # normals carry the slopes it has.
    texel = (north - south) * 111_132.0 / (len(pixels) - 1)
    detail = pixels - _blurred(pixels, round(len(pixels) / (count - 1)))
    top_first = detail[::-1] / texel
    normals = surfaces.normal_map(top_first, 1.0, wrap=False)[::-1]
    _write_image(os.path.join(directory, '%s_normal.png' % name),
                 np.asarray(normals * 255 + 0.5, np.uint8))
    return ('<Shape><Appearance><PhysicalMaterial roughness="0.92" metallic="0">'
            '<ImageTexture containerField="normalTexture" url=\'"%s_normal.png"\' '
            'repeatS="false" repeatT="false"/></PhysicalMaterial><ImageTexture '
            'url=\'"%s_colour.png"\' repeatS="false" repeatT="false"/></Appearance>'
            '<GeoElevationGrid geoGridOrigin="%s %s 0" xDimension="%d" zDimension="%d" '
            'xSpacing="%.9g" zSpacing="%.9g" creaseAngle="3.14" height="%s">%s'
            '</GeoElevationGrid></Shape>'
            % (name, name, repr(south), repr(west), count, count,
               (east - west) / (count - 1), (north - south) / (count - 1),
               _numbers(ground), ORIGIN_USE))


def _hut(index: int, latitude: float, longitude: float, turn: float) -> str:
    """A hut on the ground at `latitude`, `longitude`, as X3D"""
    floor = float(heights(np.array([latitude]), np.array([longitude]))[0]) - 0.4
    roof = ('<Shape><Appearance DEF="Roof%d"><PhysicalMaterial roughness="0.7" '
            'baseColor="0.45 0.16 0.10"/></Appearance><IndexedFaceSet solid="false" '
            'coordIndex="0 1 2 -1 3 5 4 -1 0 3 4 1 -1 1 4 5 2 -1" '
            'creaseAngle="0"><Coordinate point="-3.6 0 -4.6 0 2.4 -4.6 3.6 0 -4.6 '
            '-3.6 0 4.6 0 2.4 4.6 3.6 0 4.6"/></IndexedFaceSet></Shape>' % index)
    return ('<GeoLocation geoCoords="%r %r %r">%s<Transform rotation="0 1 0 %r" scale="1.4 1.4 1.4">'
            '<Transform translation="0 2 0"><Shape><Appearance><PhysicalMaterial '
            'roughness="0.85"><ImageTexture containerField="baseTexture" '
            'url=\'"plaster.png"\'/></PhysicalMaterial></Appearance>'
            '<Box size="6 4 8"/></Shape></Transform><Transform translation="0 4 0">%s'
            '</Transform></Transform></GeoLocation>'
            % (latitude, longitude, floor, ORIGIN_USE, turn, roof))


def document(directory: str) -> str:
    """The showcase's X3D document, its tiles and maps written to `directory`"""
    from vrml.x3d import geospatial  # noqa: PLC0415 kept with its use
    from OpenGLContext.atomicfiles import staged_file  # noqa: PLC0415 kept with its use
    south, west, north, east = AREA
    middle_latitude, middle_longitude = (south + north) / 2, (west + east) / 2
    tiles = []
    for row, (low, high) in enumerate(((south, middle_latitude), (middle_latitude, north))):
        for column, (left, right) in enumerate(((west, middle_longitude),
                                                (middle_longitude, east))):
            name = 'tile%d%d' % (row, column)
            tile = ('<X3D profile="Immersive" version="4.0"><head><component name="Geospatial" '
                    'level="1"/></head><Scene>%s</Scene></X3D>'
                    % _ground(directory, name, (low, left, high, right), FINE).replace(
                        ORIGIN_USE, ORIGIN_DEF))
            with staged_file(os.path.join(directory, name + '.x3d')) as handle:
                handle.write(tile.encode('utf-8'))
            tiles.append(name + '.x3d')
    coarse = _ground(directory, 'valley', AREA, COARSE)
    ground = float(heights(np.array([LOOKOUT[0]]), np.array([LOOKOUT[1]]))[0])
    utm = geospatial.from_geocentric(geospatial.system(['UTM', 'Z32']), geospatial.to_geocentric(
        geospatial.system(['GD']), [(LOOKOUT[0], LOOKOUT[1], ground + 30.0)]))[0]
    balloon_keys = ' '.join('%r' % (index / (len(BALLOON) - 1)) for index in range(len(BALLOON)))
    return '''<X3D profile="Immersive" version="4.0">
<head><component name="Geospatial" level="1"/>
<meta name="title" content="An alpine valley, placed on the Earth"/></head>
<Scene>
<WorldInfo title="X3D Geospatial: an alpine valley"/>
<NavigationInfo type='"FLY" "EXAMINE" "ANY"' headlight="false"/>
<Background skyColor="0.38 0.58 0.86 0.62 0.77 0.93 0.8 0.86 0.92" skyAngle="0.9 1.5"
  groundColor="0.8 0.86 0.92"/>
<Fog fogType="EXPONENTIAL" color="0.8 0.86 0.92" visibilityRange="16000"/>
<DirectionalLight direction="0.35 -0.8 -0.48" intensity="1.6" color="1 0.96 0.88"/>
<DirectionalLight direction="-0.5 -0.45 0.55" intensity="0.55" color="0.62 0.72 0.92"/>
<DirectionalLight direction="0 -1 0" intensity="0.25" color="0.7 0.8 1"/>
<GeoViewpoint description="Down the valley" position="46.533 7.9805 1450"
  orientation="1 0 0 -0.12" speedFactor="0.05">{origin}</GeoViewpoint>
<GeoViewpoint description="Above the huts (UTM)" geoSystem='"UTM" "Z32"'
  position="{utm}" orientation="1 0 0 -0.1" speedFactor="0.05">{use}</GeoViewpoint>
<GeoViewpoint description="Over the head of the valley" position="46.585 7.9905 3300"
  orientation="0.04 0.99 0.12 2.95" speedFactor="0.05">{use}</GeoViewpoint>
<GeoProximitySensor DEF="Where" geoCenter="46.55 7.98 2000" size="20000 20000 20000">{use}
</GeoProximitySensor>
<Group>
<GeoTouchSensor DEF="Touch" description="the ground">{use}</GeoTouchSensor>
<GeoLOD center="46.55 7.98 1400" range="2500" child1Url='"{tiles[0]}"'
  child2Url='"{tiles[1]}"' child3Url='"{tiles[2]}"' child4Url='"{tiles[3]}"'>{use}
{coarse}
</GeoLOD>
</Group>
{huts}
<Transform DEF="Balloon"><Transform translation="0 9 0"><Shape><Appearance>
<PhysicalMaterial baseColor="0.78 0.12 0.09" roughness="0.45"/></Appearance>
<Sphere radius="8"/></Shape></Transform><Shape><Appearance><PhysicalMaterial
  baseColor="0.42 0.3 0.16" roughness="0.9"/></Appearance><Box size="2.4 1.6 2.4"/></Shape>
</Transform>
<TimeSensor DEF="Drift" cycleInterval="120" loop="true"/>
<GeoPositionInterpolator DEF="Path" key="{keys}" keyValue="{balloon}">{use}
</GeoPositionInterpolator>
<ROUTE fromNode="Drift" fromField="fraction_changed" toNode="Path" toField="set_fraction"/>
<ROUTE fromNode="Path" fromField="value_changed" toNode="Balloon" toField="translation"/>
</Scene>
</X3D>
'''.format(origin=ORIGIN_DEF, use=ORIGIN_USE, utm=_numbers(utm), tiles=tiles, coarse=coarse,
           huts='\n'.join(_hut(index, *hut) for index, hut in enumerate(HUTS)),
           keys=balloon_keys, balloon=_numbers(BALLOON))


def prepare(directory: str) -> str:
    """The document and the files it names, written to `directory`; the document's path"""
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import staged_file  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    os.makedirs(directory, exist_ok=True)
    plaster = surfaces.images(surfaces.plaster(256))[0]
    with staged_file(os.path.join(directory, 'plaster.png')) as handle:
        Image.fromarray(plaster, 'RGB').save(handle, 'PNG')
    target = os.path.join(directory, 'x3d_geospatial.x3d')
    text = document(directory)
    with staged_file(target) as handle:
        handle.write(text.encode('utf-8'))
    return target


def _triple(values: Any) -> Optional[tuple[float, float, float]]:
    """Three coordinates as floats; None for None"""
    if values is None:
        return None
    return float(values[0]), float(values[1]), float(values[2])


class Showcase:
    """The geospatial showcase with no window: what the command, its tutorial and its tests share

    ``scene`` is the document read by the engine's loader.
    """

    KEYS: ClassVar[dict[str, str]] = {
        'g': 'where the viewer is',
        'w': 'the scene written back as X3D in each encoding',
    }

    def __init__(self, directory: str) -> None:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory)
        self.scene = Loader.load(self.path)

    def where(self) -> Optional[tuple[float, float, float]]:
        """The viewer's (latitude, longitude, height); None before it has been sensed"""
        return _triple(self.scene.getDEF('Where').__dict__.get('geoCoord_changed'))

    def touched(self) -> Optional[tuple[float, float, float]]:
        """The (latitude, longitude, height) of the ground last under the pointer; None before"""
        return _triple(self.scene.getDEF('Touch').__dict__.get('hitGeoCoord_changed'))

    def press(self, key: str) -> str:
        """Answer a key; what it did, for the console"""
        if key == 'g':
            where = self.where()
            if where is None:
                return 'the viewer has not been sensed yet'
            return '%.5f N %.5f E, %.0f m' % where
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
        prog='oglc-x3d-geospatial', description=(__doc__ or '').split('\n')[0],
        epilog=Showcase.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document and its files are written '
                        '(default: the user cache directory)')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-geospatial')
    base: Any = testingcontext.getInteractive()

    class ShowcaseContext(base):                 # pragma: no cover - needs a window
        contextDefinition = ContextDefinition(title='X3D Geospatial', size=(1280, 720))

        def OnInit(self) -> None:
            from pydispatch import dispatcher  # noqa: PLC0415 kept with its use
            from vrml import protofunctions  # noqa: PLC0415 kept with its use
            self.showcase = Showcase(directory)
            self.sg = self.showcase.scene
            for key in Showcase.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            touch = self.sg.getDEF('Touch')
            dispatcher.connect(self.OnTouch, signal=('set', protofunctions.getField(
                touch, 'touchTime')), sender=touch)
            print(Showcase.help())

        def OnKey(self, event: Any) -> None:
            said = self.showcase.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(True)

        def OnTouch(self, **_named: Any) -> None:
            found = self.showcase.touched()
            if found is not None:
                print('the ground at %.5f N %.5f E, %.0f m' % found)

    ShowcaseContext.ContextMainLoop()
    return 0


if __name__ == '__main__':  # pragma: no cover - the command line
    sys.exit(main())
