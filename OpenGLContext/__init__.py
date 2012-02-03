'''Rendering contexts for various GUI libraries, scene graph
geometry objects, and PyOpenGL testing code

The OpenGLContext project provides a simplified environment
for writing OpenGL code with PyOpenGL.  This simplified
environment abstracts the GUI library interfaces for a
large number of GUI libraries to allow the easy creation of
cross platform and cross-GUI-OpenGL programs.

The project also provides simplified geometry display
primitives to allow new developers to concentrate on the
particular task in which they are interested rather than
forcing them to re-implement basic geometry display
mechanisms.

Taking advantage of this simplified environment, we have
provided a number of testing modules.  These testing
modules should operate under any of the fully functional
GUI contexts (note that there are unfinished contexts).
'''

__version__ = "2.2.0a2"
__author__ = "Michael Colin Fletcher"
__license__ = "BSD-Style, see license.txt for details and exceptions"

from OpenGLContext.plugins import Context,InteractiveContext,VRMLContext,Loader,Node

Context( 'pygame', 'OpenGLContext.pygamecontext.PyGameContext' )
Context( 'wx', 'OpenGLContext.wxcontext.wxContext' )
Context( 'glut', 'OpenGLContext.glutcontext.GLUTContext' )
InteractiveContext( 'pygame', 'OpenGLContext.pygameinteractivecontext.PygameInteractiveContext' )
InteractiveContext( 'wx', 'OpenGLContext.wxinteractivecontext.wxInteractiveContext' )
InteractiveContext( 'glut', 'OpenGLContext.glutinteractivecontext.GLUTInteractiveContext' )
VRMLContext( 'pygame', 'OpenGLContext.pygamevrmlcontext.VRMLContext' )
VRMLContext( 'wx', 'OpenGLContext.wxvrmlcontext.VRMLContext' )
VRMLContext( 'glut', 'OpenGLContext.glutvrmlcontext.VRMLContext' )

try:
    import OpenGLContext_qt
except ImportError, err:
    pass

Loader( 'vrml97', 'OpenGLContext.loaders.vrml97.defaultHandler', ['.wrl','.wrz','.vrml','model/vrml','x-world/x-vrml','.wrl.gz'] )
Loader( 'obj', 'OpenGLContext.loaders.obj.defaultHandler', ['.obj'] )

Node( 'Anchor', 'vrml.vrml97.basenodes.Anchor' )
Node( 'Appearance', 'OpenGLContext.scenegraph.appearance.Appearance' )
Node( 'AudioClip', 'vrml.vrml97.basenodes.AudioClip' )
Node( 'Background', 'OpenGLContext.scenegraph.background.Background' )
Node( 'Billboard', 'OpenGLContext.scenegraph.billboard.Billboard' )
Node( 'Box', 'OpenGLContext.scenegraph.box.Box' )
Node( 'Collision', 'OpenGLContext.scenegraph.collision.Collision' )
Node( 'Color', 'vrml.vrml97.basenodes.Color' )
Node( 'ColorInterpolator', 'OpenGLContext.scenegraph.interpolators.ColorInterpolator' )
Node( 'Cone', 'OpenGLContext.scenegraph.quadrics.Cone' )
Node( 'Coordinate', 'OpenGLContext.scenegraph.coordinate.Coordinate' )
Node( 'CoordinateInterpolator', 'OpenGLContext.scenegraph.interpolators.CoordinateInterpolator' )
Node( 'Cylinder', 'OpenGLContext.scenegraph.quadrics.Cylinder' )
Node( 'CylinderSensor', 'vrml.vrml97.basenodes.CylinderSensor' )
Node( 'DirectionalLight', 'OpenGLContext.scenegraph.light.DirectionalLight' )
Node( 'ElevationGrid', 'vrml.vrml97.basenodes.ElevationGrid' )
Node( 'Extrusion', 'vrml.vrml97.basenodes.Extrusion' )
Node( 'Fog', 'vrml.vrml97.basenodes.Fog' )
Node( 'FontStyle', 'OpenGLContext.scenegraph.text.fontstyle3d.FontStyle' )
Node( 'Gear', 'OpenGLContext.scenegraph.gear.Gear' )
Node( 'Group', 'OpenGLContext.scenegraph.group.Group' )
Node( 'ImageTexture', 'OpenGLContext.scenegraph.imagetexture.ImageTexture' )
Node( 'IndexedFaceSet', 'OpenGLContext.scenegraph.indexedfaceset.IndexedFaceSet' )
Node( 'IndexedLineSet', 'OpenGLContext.scenegraph.indexedlineset.IndexedLineSet' )
Node( 'Inline', 'OpenGLContext.scenegraph.inline.Inline' )
Node( 'LOD', 'OpenGLContext.scenegraph.lod.LOD' )
Node( 'Material', 'OpenGLContext.scenegraph.material.Material' )
Node( 'MouseOver', 'OpenGLContext.scenegraph.mouseover.MouseOver' )
Node( 'MovieTexture', 'vrml.vrml97.basenodes.MovieTexture' )
Node( 'NavigationInfo', 'vrml.vrml97.basenodes.NavigationInfo' )
Node( 'Normal', 'vrml.vrml97.basenodes.Normal' )
Node( 'NormalInterpolator', 'vrml.vrml97.basenodes.NormalInterpolator' )
Node( 'OrientationInterpolator', 'OpenGLContext.scenegraph.interpolators.OrientationInterpolator' )
Node( 'PixelTexture', 'OpenGLContext.scenegraph.imagetexture.PixelTexture' )
Node( 'PlaneSensor', 'vrml.vrml97.basenodes.PlaneSensor' )
Node( 'PointLight', 'OpenGLContext.scenegraph.light.PointLight' )
Node( 'PointSet', 'OpenGLContext.scenegraph.pointset.PointSet' )
Node( 'PositionInterpolator', 'OpenGLContext.scenegraph.interpolators.PositionInterpolator' )
Node( 'ProximitySensor', 'vrml.vrml97.basenodes.ProximitySensor' )
Node( 'ScalarInterpolator', 'OpenGLContext.scenegraph.interpolators.ScalarInterpolator' )
Node( 'Shape', 'OpenGLContext.scenegraph.shape.Shape' )
Node( 'Sound', 'vrml.vrml97.basenodes.Sound' )
Node( 'Sphere', 'OpenGLContext.scenegraph.quadrics.Sphere' )
Node( 'SphereSensor', 'vrml.vrml97.basenodes.SphereSensor' )
Node( 'SpotLight', 'OpenGLContext.scenegraph.light.SpotLight' )
Node( 'Switch', 'OpenGLContext.scenegraph.switch.Switch' )
Node( 'Teapot', 'OpenGLContext.scenegraph.teapot.Teapot' )
Node( 'Text', 'OpenGLContext.scenegraph.text.text.Text' )
Node( 'TextureCoordinate', 'vrml.vrml97.basenodes.TextureCoordinate' )
Node( 'TextureTransform', 'OpenGLContext.scenegraph.texturetransform.TextureTransform' )
Node( 'TimeSensor', 'OpenGLContext.scenegraph.timesensor.TimeSensor' )
Node( 'TouchSensor', 'vrml.vrml97.basenodes.TouchSensor' )
Node( 'Transform', 'OpenGLContext.scenegraph.transform.Transform' )
Node( 'Viewpoint', 'OpenGLContext.scenegraph.viewpoint.Viewpoint' )
Node( 'VisibilitySensor', 'vrml.vrml97.basenodes.VisibilitySensor' )
Node( 'WorldInfo', 'vrml.vrml97.basenodes.WorldInfo' )
Node( 'sceneGraph', 'OpenGLContext.scenegraph.scenegraph.SceneGraph' )
Node( 'IndexedPolygons', 'OpenGLContext.scenegraph.indexedpolygons.IndexedPolygons' )
Node( 'FontStyle3D', 'OpenGLContext.scenegraph.text.fontstyle3d.FontStyle3D' )
Node( 'SimpleBackground', 'OpenGLContext.scenegraph.simplebackground.SimpleBackground' )
Node( 'CubeBackground', 'OpenGLContext.scenegraph.cubebackground.CubeBackground' )
Node( 'SphereBackground', 'OpenGLContext.scenegraph.spherebackground.SphereBackground' )
Node( 'MMImageTexture', 'OpenGLContext.scenegraph.imagetexture.MMImageTexture' )
Node( 'Contour2D', 'OpenGLContext.scenegraph.nurbs.Contour2D' )
Node( 'NurbsCurve', 'OpenGLContext.scenegraph.nurbs.NurbsCurve' )
Node( 'NurbsCurve2D', 'OpenGLContext.scenegraph.nurbs.NurbsCurve2D' )
Node( 'NurbsDomainDistanceSample', 'OpenGLContext.scenegraph.nurbs.NurbsDomainDistanceSample' )
Node( 'NurbsSurface', 'OpenGLContext.scenegraph.nurbs.NurbsSurface' )
Node( 'NurbsToleranceSample', 'OpenGLContext.scenegraph.nurbs.NurbsToleranceSample' )
Node( 'Polyline2D', 'OpenGLContext.scenegraph.nurbs.Polyline2D' )
Node( 'TrimmedSurface', 'OpenGLContext.scenegraph.nurbs.TrimmedSurface' )

for suffix in ('1f','2f','3f','4f','m2','m3','m4','m2x3','m3x2','m2x4','m4x2','m3x4','m4x3'):
    Node( 'FloatUniform'+suffix,'OpenGLContext.scenegraph.shaders.FloatUniform'+suffix )
for suffix in ('1i','2i','3i','4i'):
    Node( 'IntUniform'+suffix,'OpenGLContext.scenegraph.shaders.IntUniform'+suffix )
Node( 'TextureUniform','OpenGLContext.scenegraph.shaders.TextureUniform' )
Node( 'TextureBufferUniform','OpenGLContext.scenegraph.shaders.TextureBufferUniform' )
Node( 'GLSLShader','OpenGLContext.scenegraph.shaders.GLSLShader' )
Node( 'GLSLObject','OpenGLContext.scenegraph.shaders.GLSLObject' )
Node( 'GLSLImport','OpenGLContext.scenegraph.shaders.GLSLImport' )

Node( 'ShaderAttribute','OpenGLContext.scenegraph.shaders.ShaderAttribute' )
Node( 'ShaderBuffer','OpenGLContext.scenegraph.shaders.ShaderBuffer' )
Node( 'ShaderIndexBuffer','OpenGLContext.scenegraph.shaders.ShaderIndexBuffer' )
Node( 'ShaderSlice','OpenGLContext.scenegraph.shaders.ShaderSlice' )

Node( 'Shader','OpenGLContext.scenegraph.shaders.Shader' )
Node( 'ROUTE','vrml.route.ROUTE' )
Node( 'IS','vrml.route.IS' )
