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
from typing import Any

#: Node classes by the name they are registered under, including any a third
#: party added; ``basenodes.NAME`` is the same object.
PROTOTYPES: dict[str, Any]

from OpenGLContext.scenegraph.shaders import FloatUniform as _FloatUniform
from OpenGLContext.scenegraph.shaders import IntUniform as _IntUniform

from OpenGLContext.scenegraph.anchor import Anchor as Anchor
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
from OpenGLContext.scenegraph.cubemaptexture import ComposedCubeMapTexture as ComposedCubeMapTexture
from OpenGLContext.scenegraph.cubemaptexture import GeneratedCubeMapTexture as GeneratedCubeMapTexture
from OpenGLContext.scenegraph.cubemaptexture import ImageCubeMapTexture as ImageCubeMapTexture
from OpenGLContext.scenegraph.environmentlight import EnvironmentLight as EnvironmentLight
from OpenGLContext.scenegraph.extrusions import Extrusion as Extrusion
from OpenGLContext.scenegraph.extrusions import PolyCone as PolyCone
from OpenGLContext.scenegraph.extrusions import PolyCylinder as PolyCylinder
from OpenGLContext.scenegraph.fog import Fog as Fog
from OpenGLContext.scenegraph.fog import LocalFog as LocalFog
from OpenGLContext.scenegraph.gear import Gear as Gear
from OpenGLContext.scenegraph.geometry2d import Arc2D as Arc2D
from OpenGLContext.scenegraph.geometry2d import ArcClose2D as ArcClose2D
from OpenGLContext.scenegraph.geometry2d import Circle2D as Circle2D
from OpenGLContext.scenegraph.geometry2d import Disk2D as Disk2D
from OpenGLContext.scenegraph.geometry2d import Polypoint2D as Polypoint2D
from OpenGLContext.scenegraph.geometry2d import Rectangle2D as Rectangle2D
from OpenGLContext.scenegraph.geometry2d import TriangleSet2D as TriangleSet2D
from OpenGLContext.scenegraph.group import Group as Group
from OpenGLContext.scenegraph.imagebasedlight import ImageBasedLight as ImageBasedLight
from OpenGLContext.scenegraph.imagedata import ImageDataTexture as ImageDataTexture
from OpenGLContext.scenegraph.imagetexture import ImageTexture as ImageTexture
from OpenGLContext.scenegraph.imagetexture import MMImageTexture as MMImageTexture
from OpenGLContext.scenegraph.imagetexture import PixelTexture as PixelTexture
from OpenGLContext.scenegraph.indexedfaceset import IndexedFaceSet as IndexedFaceSet
from OpenGLContext.scenegraph.indexedlineset import IndexedLineSet as IndexedLineSet
from OpenGLContext.scenegraph.indexedpolygons import IndexedPolygons as IndexedPolygons
from OpenGLContext.scenegraph.inline import Inline as Inline
from OpenGLContext.scenegraph.inlinegeometry import InlineGeometry as InlineGeometry
from OpenGLContext.scenegraph.interpolators import ColorInterpolator as ColorInterpolator
from OpenGLContext.scenegraph.interpolators import CoordinateInterpolator as CoordinateInterpolator
from OpenGLContext.scenegraph.interpolators import NormalInterpolator as NormalInterpolator
from OpenGLContext.scenegraph.interpolators import OrientationInterpolator as OrientationInterpolator
from OpenGLContext.scenegraph.interpolators import PositionInterpolator as PositionInterpolator
from OpenGLContext.scenegraph.interpolators import ScalarInterpolator as ScalarInterpolator
from OpenGLContext.scenegraph.light import DirectionalLight as DirectionalLight
from OpenGLContext.scenegraph.light import PointLight as PointLight
from OpenGLContext.scenegraph.light import SpotLight as SpotLight
from OpenGLContext.scenegraph.lod import LOD as LOD
from OpenGLContext.scenegraph.lod import ScreenCoverageLOD as ScreenCoverageLOD
from OpenGLContext.scenegraph.material import Material as Material
from OpenGLContext.scenegraph.meshgeometry import ElevationGrid as ElevationGrid
from OpenGLContext.scenegraph.meshgeometry import IndexedQuadSet as IndexedQuadSet
from OpenGLContext.scenegraph.meshgeometry import IndexedTriangleFanSet as IndexedTriangleFanSet
from OpenGLContext.scenegraph.meshgeometry import IndexedTriangleSet as IndexedTriangleSet
from OpenGLContext.scenegraph.meshgeometry import IndexedTriangleStripSet as IndexedTriangleStripSet
from OpenGLContext.scenegraph.meshgeometry import LineSet as LineSet
from OpenGLContext.scenegraph.meshgeometry import QuadSet as QuadSet
from OpenGLContext.scenegraph.meshgeometry import TriangleFanSet as TriangleFanSet
from OpenGLContext.scenegraph.meshgeometry import TriangleSet as TriangleSet
from OpenGLContext.scenegraph.meshgeometry import TriangleStripSet as TriangleStripSet
from OpenGLContext.scenegraph.mouseover import MouseOver as MouseOver
from OpenGLContext.scenegraph.movietexture import MovieTexture as MovieTexture
from OpenGLContext.scenegraph.multitexture import MultiTexture as MultiTexture
from OpenGLContext.scenegraph.nurbs import Contour2D as Contour2D
from OpenGLContext.scenegraph.nurbs import NurbsCurve as NurbsCurve
from OpenGLContext.scenegraph.nurbs import NurbsCurve2D as NurbsCurve2D
from OpenGLContext.scenegraph.nurbs import NurbsDomainDistanceSample as NurbsDomainDistanceSample
from OpenGLContext.scenegraph.nurbs import NurbsSurface as NurbsSurface
from OpenGLContext.scenegraph.nurbs import NurbsToleranceSample as NurbsToleranceSample
from OpenGLContext.scenegraph.nurbs import Polyline2D as Polyline2D
from OpenGLContext.scenegraph.nurbs import TrimmedSurface as TrimmedSurface
from OpenGLContext.scenegraph.particles import ParticleEmitter as ParticleEmitter
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial as PhysicalMaterial
from OpenGLContext.scenegraph.pointset import PointSet as PointSet
from OpenGLContext.scenegraph.quadrics import Cone as Cone
from OpenGLContext.scenegraph.quadrics import Cylinder as Cylinder
from OpenGLContext.scenegraph.quadrics import Sphere as Sphere
from OpenGLContext.scenegraph.reflector import PlanarReflector as PlanarReflector
from OpenGLContext.scenegraph.renderedtexture import RenderedTexture as RenderedTexture
from OpenGLContext.scenegraph.scenegraph import SceneGraph as sceneGraph
from OpenGLContext.scenegraph.scenegraph import X3DScene as X3DScene
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
from OpenGLContext.scenegraph.texture3d import ComposedTexture3D as ComposedTexture3D
from OpenGLContext.scenegraph.texture3d import ImageTexture3D as ImageTexture3D
from OpenGLContext.scenegraph.texture3d import PixelTexture3D as PixelTexture3D
from OpenGLContext.scenegraph.texturebackground import TextureBackground as TextureBackground
from OpenGLContext.scenegraph.textureprojector import TextureProjector as TextureProjector
from OpenGLContext.scenegraph.textureprojector import TextureProjectorParallel as TextureProjectorParallel
from OpenGLContext.scenegraph.texturetransform import TextureTransform as TextureTransform
from OpenGLContext.scenegraph.timesensor import TimeSensor as TimeSensor
from OpenGLContext.scenegraph.transform import CADPart as CADPart
from OpenGLContext.scenegraph.transform import Transform as Transform
from OpenGLContext.scenegraph.unlitmaterial import UnlitMaterial as UnlitMaterial
from OpenGLContext.scenegraph.viewpoint import OrthoViewpoint as OrthoViewpoint
from OpenGLContext.scenegraph.viewpoint import Viewpoint as Viewpoint
from OpenGLContext.scenegraph.viewpointgroup import ViewpointGroup as ViewpointGroup
from OpenGLContext.scenegraph.x3dgroups import CADAssembly as CADAssembly
from OpenGLContext.scenegraph.x3dgroups import CADFace as CADFace
from OpenGLContext.scenegraph.x3dgroups import CADLayer as CADLayer
from OpenGLContext.scenegraph.x3dgroups import PickableGroup as PickableGroup
from OpenGLContext.scenegraph.x3dgroups import StaticGroup as StaticGroup
from OpenGLContext.scenegraph.x3dpointing import CylinderSensor as CylinderSensor
from OpenGLContext.scenegraph.x3dpointing import PlaneSensor as PlaneSensor
from OpenGLContext.scenegraph.x3dpointing import SphereSensor as SphereSensor
from OpenGLContext.scenegraph.x3dpointing import TouchSensor as TouchSensor
from OpenGLContext.scenegraph.x3druntime import ColorChaser as ColorChaser
from OpenGLContext.scenegraph.x3druntime import ColorDamper as ColorDamper
from OpenGLContext.scenegraph.x3druntime import CoordinateChaser as CoordinateChaser
from OpenGLContext.scenegraph.x3druntime import CoordinateDamper as CoordinateDamper
from OpenGLContext.scenegraph.x3druntime import KeySensor as KeySensor
from OpenGLContext.scenegraph.x3druntime import LoadSensor as LoadSensor
from OpenGLContext.scenegraph.x3druntime import OrientationChaser as OrientationChaser
from OpenGLContext.scenegraph.x3druntime import OrientationDamper as OrientationDamper
from OpenGLContext.scenegraph.x3druntime import PositionChaser as PositionChaser
from OpenGLContext.scenegraph.x3druntime import PositionChaser2D as PositionChaser2D
from OpenGLContext.scenegraph.x3druntime import PositionDamper as PositionDamper
from OpenGLContext.scenegraph.x3druntime import PositionDamper2D as PositionDamper2D
from OpenGLContext.scenegraph.x3druntime import ScalarChaser as ScalarChaser
from OpenGLContext.scenegraph.x3druntime import ScalarDamper as ScalarDamper
from OpenGLContext.scenegraph.x3druntime import StringSensor as StringSensor
from OpenGLContext.scenegraph.x3druntime import TexCoordChaser2D as TexCoordChaser2D
from OpenGLContext.scenegraph.x3druntime import TexCoordDamper2D as TexCoordDamper2D
from OpenGLContext.scenegraph.x3druntime import TimeTrigger as TimeTrigger
from OpenGLContext.scenegraph.zone import Zone as Zone
from OpenGLContext.scenegraph.zone import ZoneAudio as ZoneAudio
from OpenGLContext.scenegraph.zone import ZoneEnvironment as ZoneEnvironment
from OpenGLContext.scenegraph.zone import ZoneGravity as ZoneGravity
from OpenGLContext.scenegraph.zone import ZoneLights as ZoneLights
from OpenGLContext.scenegraph.zone import ZoneMirrors as ZoneMirrors
from OpenGLContext.scenegraph.zone import ZoneReverb as ZoneReverb
from OpenGLContext.scenegraph.zone import ZoneVisibility as ZoneVisibility
from vrml.route import IS as IS
from vrml.route import ROUTE as ROUTE
from vrml.vrml97.basenodes import AudioClip as AudioClip
from vrml.vrml97.basenodes import Color as Color
from vrml.vrml97.basenodes import NavigationInfo as NavigationInfo
from vrml.vrml97.basenodes import Normal as Normal
from vrml.vrml97.basenodes import TextureCoordinate as TextureCoordinate
from vrml.vrml97.basenodes import WorldInfo as WorldInfo
from vrml.x3d.nodes import ColorRGBA as ColorRGBA
from vrml.x3d.nodes import CoordinateDouble as CoordinateDouble
from vrml.x3d.nodes import FillProperties as FillProperties
from vrml.x3d.nodes import LineProperties as LineProperties
from vrml.x3d.nodes import MetadataBoolean as MetadataBoolean
from vrml.x3d.nodes import MetadataDouble as MetadataDouble
from vrml.x3d.nodes import MetadataFloat as MetadataFloat
from vrml.x3d.nodes import MetadataInteger as MetadataInteger
from vrml.x3d.nodes import MetadataSet as MetadataSet
from vrml.x3d.nodes import MetadataString as MetadataString
from vrml.x3d.nodes import MultiTextureCoordinate as MultiTextureCoordinate
from vrml.x3d.nodes import MultiTextureTransform as MultiTextureTransform
from vrml.x3d.nodes import PointProperties as PointProperties
from vrml.x3d.nodes import Tangent as Tangent
from vrml.x3d.nodes import TextureCoordinate3D as TextureCoordinate3D
from vrml.x3d.nodes import TextureCoordinate4D as TextureCoordinate4D
from vrml.x3d.nodes import TextureProperties as TextureProperties
from vrml.x3d.nodes import TextureTransform3D as TextureTransform3D
from vrml.x3d.nodes import TextureTransformMatrix3D as TextureTransformMatrix3D
from vrml.x3d.nodes import TwoSidedMaterial as TwoSidedMaterial
from vrml.x3d.runtime import BooleanFilter as BooleanFilter
from vrml.x3d.runtime import BooleanSequencer as BooleanSequencer
from vrml.x3d.runtime import BooleanToggle as BooleanToggle
from vrml.x3d.runtime import BooleanTrigger as BooleanTrigger
from vrml.x3d.runtime import CoordinateInterpolator2D as CoordinateInterpolator2D
from vrml.x3d.runtime import EaseInEaseOut as EaseInEaseOut
from vrml.x3d.runtime import IntegerSequencer as IntegerSequencer
from vrml.x3d.runtime import IntegerTrigger as IntegerTrigger
from vrml.x3d.runtime import PositionInterpolator2D as PositionInterpolator2D
from vrml.x3d.runtime import SplinePositionInterpolator as SplinePositionInterpolator
from vrml.x3d.runtime import SplinePositionInterpolator2D as SplinePositionInterpolator2D
from vrml.x3d.runtime import SplineScalarInterpolator as SplineScalarInterpolator
from vrml.x3d.runtime import SquadOrientationInterpolator as SquadOrientationInterpolator
from vrml.x3d.sensors import ProximitySensor as ProximitySensor
from vrml.x3d.sensors import TransformSensor as TransformSensor
from vrml.x3d.sensors import VisibilitySensor as VisibilitySensor

__all__ = [
    'Anchor',
    'Appearance',
    'Arc2D',
    'ArcClose2D',
    'AudioClip',
    'AudioEmitter',
    'AudioSource',
    'Background',
    'Billboard',
    'BooleanFilter',
    'BooleanSequencer',
    'BooleanToggle',
    'BooleanTrigger',
    'Box',
    'CADAssembly',
    'CADFace',
    'CADLayer',
    'CADPart',
    'Circle2D',
    'Collision',
    'Color',
    'ColorChaser',
    'ColorDamper',
    'ColorInterpolator',
    'ColorRGBA',
    'ComposedCubeMapTexture',
    'ComposedTexture3D',
    'Cone',
    'Contour2D',
    'Coordinate',
    'CoordinateChaser',
    'CoordinateDamper',
    'CoordinateDouble',
    'CoordinateInterpolator',
    'CoordinateInterpolator2D',
    'CubeBackground',
    'Cylinder',
    'CylinderSensor',
    'DirectionalLight',
    'Disk2D',
    'EaseInEaseOut',
    'ElevationGrid',
    'EnvironmentLight',
    'Extrusion',
    'FillProperties',
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
    'GeneratedCubeMapTexture',
    'Group',
    'IS',
    'ImageBasedLight',
    'ImageCubeMapTexture',
    'ImageDataTexture',
    'ImageTexture',
    'ImageTexture3D',
    'IndexedFaceSet',
    'IndexedLineSet',
    'IndexedPolygons',
    'IndexedQuadSet',
    'IndexedTriangleFanSet',
    'IndexedTriangleSet',
    'IndexedTriangleStripSet',
    'Inline',
    'InlineGeometry',
    'IntUniform1i',
    'IntUniform2i',
    'IntUniform3i',
    'IntUniform4i',
    'IntegerSequencer',
    'IntegerTrigger',
    'KeySensor',
    'LOD',
    'LineProperties',
    'LineSet',
    'LoadSensor',
    'LocalFog',
    'MMImageTexture',
    'Material',
    'MetadataBoolean',
    'MetadataDouble',
    'MetadataFloat',
    'MetadataInteger',
    'MetadataSet',
    'MetadataString',
    'MouseOver',
    'MovieTexture',
    'MultiTexture',
    'MultiTextureCoordinate',
    'MultiTextureTransform',
    'NavigationInfo',
    'Normal',
    'NormalInterpolator',
    'NurbsCurve',
    'NurbsCurve2D',
    'NurbsDomainDistanceSample',
    'NurbsSurface',
    'NurbsToleranceSample',
    'OrientationChaser',
    'OrientationDamper',
    'OrientationInterpolator',
    'OrthoViewpoint',
    'ParticleEmitter',
    'PhysicalMaterial',
    'PickableGroup',
    'PixelTexture',
    'PixelTexture3D',
    'PlanarReflector',
    'PlaneSensor',
    'PointLight',
    'PointProperties',
    'PointSet',
    'PolyCone',
    'PolyCylinder',
    'Polyline2D',
    'Polypoint2D',
    'PositionChaser',
    'PositionChaser2D',
    'PositionDamper',
    'PositionDamper2D',
    'PositionInterpolator',
    'PositionInterpolator2D',
    'ProximitySensor',
    'QuadSet',
    'ROUTE',
    'Rectangle2D',
    'RenderedTexture',
    'ScalarChaser',
    'ScalarDamper',
    'ScalarInterpolator',
    'ScreenCoverageLOD',
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
    'SplinePositionInterpolator',
    'SplinePositionInterpolator2D',
    'SplineScalarInterpolator',
    'SpotLight',
    'SquadOrientationInterpolator',
    'StaticGroup',
    'StringSensor',
    'Switch',
    'Tangent',
    'Teapot',
    'TexCoordChaser2D',
    'TexCoordDamper2D',
    'Text',
    'TextureBackground',
    'TextureBufferUniform',
    'TextureCoordinate',
    'TextureCoordinate3D',
    'TextureCoordinate4D',
    'TextureProjector',
    'TextureProjectorParallel',
    'TextureProperties',
    'TextureTransform',
    'TextureTransform3D',
    'TextureTransformMatrix3D',
    'TextureUniform',
    'TimeSensor',
    'TimeTrigger',
    'TouchSensor',
    'Transform',
    'TransformSensor',
    'TriangleFanSet',
    'TriangleSet',
    'TriangleSet2D',
    'TriangleStripSet',
    'TrimmedSurface',
    'TwoSidedMaterial',
    'UnlitMaterial',
    'Viewpoint',
    'ViewpointGroup',
    'VisibilitySensor',
    'WorldInfo',
    'X3DScene',
    'Zone',
    'ZoneAudio',
    'ZoneEnvironment',
    'ZoneGravity',
    'ZoneLights',
    'ZoneMirrors',
    'ZoneReverb',
    'ZoneVisibility',
    'sceneGraph',
]
