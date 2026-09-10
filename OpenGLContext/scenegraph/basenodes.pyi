"""Every registered scenegraph node class, by name.

:mod:`OpenGLContext.scenegraph.basenodes` builds its namespace at import time
from the plugin registry, so this declares what a type checker finds there.
The runtime module is the authority on what is present; this file is generated
from the registrations in ``OpenGLContext/__init__.py`` by
``scripts/write_basenodes_stub.py``, and ``tests/unit/test_basenodes_stub.py``
holds it to them.

A third party's node, registered by importing its own package, is not here and
resolves as ``Any`` -- which is what a checker can say about a name whose class
it has no declaration for.
"""
from typing import Any, Dict

#: Node classes by the name they are registered under, including any a third
#: party added; ``basenodes.NAME`` is the same object.
PROTOTYPES: Dict[str, Any]

from OpenGLContext.scenegraph.shaders import FloatUniform as _FloatUniform
from OpenGLContext.scenegraph.shaders import IntUniform as _IntUniform

from OpenGLContext.scenegraph.appearance import Appearance as Appearance
from OpenGLContext.scenegraph.audio import AudioEmitter as AudioEmitter
from OpenGLContext.scenegraph.audio import AudioSource as AudioSource
from OpenGLContext.scenegraph.audio import Sound as Sound
from OpenGLContext.scenegraph.background import Background as Background
from OpenGLContext.scenegraph.billboard import Billboard as Billboard
from OpenGLContext.scenegraph.box import Box as Box
from OpenGLContext.scenegraph.collision import Collision as Collision
from OpenGLContext.scenegraph.coordinate import Coordinate as Coordinate
from OpenGLContext.scenegraph.cubebackground import CubeBackground as CubeBackground
from OpenGLContext.scenegraph.extrusions import Extrusion as Extrusion
from OpenGLContext.scenegraph.extrusions import PolyCone as PolyCone
from OpenGLContext.scenegraph.extrusions import PolyCylinder as PolyCylinder
from OpenGLContext.scenegraph.fog import Fog as Fog
from OpenGLContext.scenegraph.gear import Gear as Gear
from OpenGLContext.scenegraph.group import Group as Group
from OpenGLContext.scenegraph.imagetexture import ImageTexture as ImageTexture
from OpenGLContext.scenegraph.imagetexture import MMImageTexture as MMImageTexture
from OpenGLContext.scenegraph.imagetexture import PixelTexture as PixelTexture
from OpenGLContext.scenegraph.indexedfaceset import IndexedFaceSet as IndexedFaceSet
from OpenGLContext.scenegraph.indexedlineset import IndexedLineSet as IndexedLineSet
from OpenGLContext.scenegraph.indexedpolygons import IndexedPolygons as IndexedPolygons
from OpenGLContext.scenegraph.inline import Inline as Inline
from OpenGLContext.scenegraph.interpolators import ColorInterpolator as ColorInterpolator
from OpenGLContext.scenegraph.interpolators import CoordinateInterpolator as CoordinateInterpolator
from OpenGLContext.scenegraph.interpolators import OrientationInterpolator as OrientationInterpolator
from OpenGLContext.scenegraph.interpolators import PositionInterpolator as PositionInterpolator
from OpenGLContext.scenegraph.interpolators import ScalarInterpolator as ScalarInterpolator
from OpenGLContext.scenegraph.light import DirectionalLight as DirectionalLight
from OpenGLContext.scenegraph.light import PointLight as PointLight
from OpenGLContext.scenegraph.light import SpotLight as SpotLight
from OpenGLContext.scenegraph.lod import LOD as LOD
from OpenGLContext.scenegraph.material import Material as Material
from OpenGLContext.scenegraph.mouseover import MouseOver as MouseOver
from OpenGLContext.scenegraph.nurbs import Contour2D as Contour2D
from OpenGLContext.scenegraph.nurbs import NurbsCurve as NurbsCurve
from OpenGLContext.scenegraph.nurbs import NurbsCurve2D as NurbsCurve2D
from OpenGLContext.scenegraph.nurbs import NurbsDomainDistanceSample as NurbsDomainDistanceSample
from OpenGLContext.scenegraph.nurbs import NurbsSurface as NurbsSurface
from OpenGLContext.scenegraph.nurbs import NurbsToleranceSample as NurbsToleranceSample
from OpenGLContext.scenegraph.nurbs import Polyline2D as Polyline2D
from OpenGLContext.scenegraph.nurbs import TrimmedSurface as TrimmedSurface
from OpenGLContext.scenegraph.particles import ParticleEmitter as ParticleEmitter
from OpenGLContext.scenegraph.pointset import PointSet as PointSet
from OpenGLContext.scenegraph.quadrics import Cone as Cone
from OpenGLContext.scenegraph.quadrics import Cylinder as Cylinder
from OpenGLContext.scenegraph.quadrics import Sphere as Sphere
from OpenGLContext.scenegraph.scenegraph import SceneGraph as sceneGraph
class FloatUniform1f(_FloatUniform): ...
class FloatUniform2f(_FloatUniform): ...
class FloatUniform3f(_FloatUniform): ...
class FloatUniform4f(_FloatUniform): ...
class FloatUniformm2(_FloatUniform): ...
class FloatUniformm2x3(_FloatUniform): ...
class FloatUniformm2x4(_FloatUniform): ...
class FloatUniformm3(_FloatUniform): ...
class FloatUniformm3x2(_FloatUniform): ...
class FloatUniformm3x4(_FloatUniform): ...
class FloatUniformm4(_FloatUniform): ...
class FloatUniformm4x2(_FloatUniform): ...
class FloatUniformm4x3(_FloatUniform): ...
from OpenGLContext.scenegraph.shaders import GLSLImport as GLSLImport
from OpenGLContext.scenegraph.shaders import GLSLObject as GLSLObject
from OpenGLContext.scenegraph.shaders import GLSLShader as GLSLShader
class IntUniform1i(_IntUniform): ...
class IntUniform2i(_IntUniform): ...
class IntUniform3i(_IntUniform): ...
class IntUniform4i(_IntUniform): ...
from OpenGLContext.scenegraph.shaders import Shader as Shader
from OpenGLContext.scenegraph.shaders import ShaderAttribute as ShaderAttribute
from OpenGLContext.scenegraph.shaders import ShaderBuffer as ShaderBuffer
from OpenGLContext.scenegraph.shaders import ShaderGeometry as ShaderGeometry
from OpenGLContext.scenegraph.shaders import ShaderIndexBuffer as ShaderIndexBuffer
from OpenGLContext.scenegraph.shaders import ShaderSlice as ShaderSlice
from OpenGLContext.scenegraph.shaders import TextureBufferUniform as TextureBufferUniform
from OpenGLContext.scenegraph.shaders import TextureUniform as TextureUniform
from OpenGLContext.scenegraph.shape import Shape as Shape
from OpenGLContext.scenegraph.simplebackground import SimpleBackground as SimpleBackground
from OpenGLContext.scenegraph.spherebackground import SphereBackground as SphereBackground
from OpenGLContext.scenegraph.switch import Switch as Switch
from OpenGLContext.scenegraph.teapot import Teapot as Teapot
from OpenGLContext.scenegraph.text.fontstyle3d import FontStyle as FontStyle
from OpenGLContext.scenegraph.text.fontstyle3d import FontStyle3D as FontStyle3D
from OpenGLContext.scenegraph.text.text import Text as Text
from OpenGLContext.scenegraph.texturetransform import TextureTransform as TextureTransform
from OpenGLContext.scenegraph.timesensor import TimeSensor as TimeSensor
from OpenGLContext.scenegraph.transform import Transform as Transform
from OpenGLContext.scenegraph.viewpoint import Viewpoint as Viewpoint
from vrml.route import IS as IS
from vrml.route import ROUTE as ROUTE
from vrml.vrml97.basenodes import Anchor as Anchor
from vrml.vrml97.basenodes import AudioClip as AudioClip
from vrml.vrml97.basenodes import Color as Color
from vrml.vrml97.basenodes import CylinderSensor as CylinderSensor
from vrml.vrml97.basenodes import ElevationGrid as ElevationGrid
from vrml.vrml97.basenodes import MovieTexture as MovieTexture
from vrml.vrml97.basenodes import NavigationInfo as NavigationInfo
from vrml.vrml97.basenodes import Normal as Normal
from vrml.vrml97.basenodes import NormalInterpolator as NormalInterpolator
from vrml.vrml97.basenodes import PlaneSensor as PlaneSensor
from vrml.vrml97.basenodes import ProximitySensor as ProximitySensor
from vrml.vrml97.basenodes import SphereSensor as SphereSensor
from vrml.vrml97.basenodes import TextureCoordinate as TextureCoordinate
from vrml.vrml97.basenodes import TouchSensor as TouchSensor
from vrml.vrml97.basenodes import VisibilitySensor as VisibilitySensor
from vrml.vrml97.basenodes import WorldInfo as WorldInfo

__all__ = [
    'Anchor',
    'Appearance',
    'AudioClip',
    'AudioEmitter',
    'AudioSource',
    'Background',
    'Billboard',
    'Box',
    'Collision',
    'Color',
    'ColorInterpolator',
    'Cone',
    'Contour2D',
    'Coordinate',
    'CoordinateInterpolator',
    'CubeBackground',
    'Cylinder',
    'CylinderSensor',
    'DirectionalLight',
    'ElevationGrid',
    'Extrusion',
    'FloatUniform1f',
    'FloatUniform2f',
    'FloatUniform3f',
    'FloatUniform4f',
    'FloatUniformm2',
    'FloatUniformm2x3',
    'FloatUniformm2x4',
    'FloatUniformm3',
    'FloatUniformm3x2',
    'FloatUniformm3x4',
    'FloatUniformm4',
    'FloatUniformm4x2',
    'FloatUniformm4x3',
    'Fog',
    'FontStyle',
    'FontStyle3D',
    'GLSLImport',
    'GLSLObject',
    'GLSLShader',
    'Gear',
    'Group',
    'IS',
    'ImageTexture',
    'IndexedFaceSet',
    'IndexedLineSet',
    'IndexedPolygons',
    'Inline',
    'IntUniform1i',
    'IntUniform2i',
    'IntUniform3i',
    'IntUniform4i',
    'LOD',
    'MMImageTexture',
    'Material',
    'MouseOver',
    'MovieTexture',
    'NavigationInfo',
    'Normal',
    'NormalInterpolator',
    'NurbsCurve',
    'NurbsCurve2D',
    'NurbsDomainDistanceSample',
    'NurbsSurface',
    'NurbsToleranceSample',
    'OrientationInterpolator',
    'ParticleEmitter',
    'PixelTexture',
    'PlaneSensor',
    'PointLight',
    'PointSet',
    'PolyCone',
    'PolyCylinder',
    'Polyline2D',
    'PositionInterpolator',
    'ProximitySensor',
    'ROUTE',
    'ScalarInterpolator',
    'Shader',
    'ShaderAttribute',
    'ShaderBuffer',
    'ShaderGeometry',
    'ShaderIndexBuffer',
    'ShaderSlice',
    'Shape',
    'SimpleBackground',
    'Sound',
    'Sphere',
    'SphereBackground',
    'SphereSensor',
    'SpotLight',
    'Switch',
    'Teapot',
    'Text',
    'TextureBufferUniform',
    'TextureCoordinate',
    'TextureTransform',
    'TextureUniform',
    'TimeSensor',
    'TouchSensor',
    'Transform',
    'TrimmedSurface',
    'Viewpoint',
    'VisibilitySensor',
    'WorldInfo',
    'sceneGraph',
]
