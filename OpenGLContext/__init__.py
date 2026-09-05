'''A 3D engine on PyOpenGL: scenes, a renderer, and a window to put it in

OpenGLContext renders 3D scenes with PyOpenGL, in a window belonging to
whichever GUI toolkit the application already uses.  GLFW, GLUT, Pygame,
wxPython and Qt/PySide are all supported; GLFW is the one to reach for with
the core profile.  A context can own the whole window or sit as one canvas
inside a larger application.

    from OpenGLContext.viewer import ViewerContext, ViewerOptions

    class MyViewer(ViewerContext):
        options = ViewerOptions(source='model.glb')

    MyViewer.ContextMainLoop()

What it holds:

    scenegraph   VRML97-style nodes, plus the metallic/roughness material
                 and mesh the glTF loader produces
    loaders      glTF 2.0/GLB, VRML97, Wavefront OBJ and streamed 3D Tiles
    passes       The core-profile and compatibility render passes, physically
                 based rendering, image-based lighting, shadows, instancing
    move         Walking, flying, swimming and mouse-look, with collision
    physics      Rigid bodies, colliders, gravity zones and triggers
    audio        Sound placed in the scene and heard from where you stand
    ui           Panels, widgets and a settings screen over the live frame
    viewer       The embeddable viewer that `oglc-view` is a command line for

It is also the primary suite of test cases PyOpenGL is verified against.

Documentation is under `docs/`, indexed by `docs/documentation.html`.
'''

__version__ = "3.0.0a3"
__author__ = "Michael Colin Fletcher"
__license__ = "BSD-Style, see license.txt for details and exceptions"

from OpenGLContext.plugins import Context,InteractiveContext,VRMLContext,Loader,Node,Adapter

Context( 'pygame', 'OpenGLContext.pygamecontext.PygameContext' )
Context( 'wx', 'OpenGLContext.wxcontext.wxContext' )
Context( 'glut', 'OpenGLContext.glutcontext.GLUTContext' )
Context( 'glfw', 'OpenGLContext.glfwcontext.GLFWContext' )
# Offscreen: no window, no display server.  One class fills the interactive slot
# too, because a context nothing can click on has no separate interactive form.
Context( 'egl', 'OpenGLContext.eglcontext.EGLContext' )
InteractiveContext( 'pygame', 'OpenGLContext.pygameinteractivecontext.PygameInteractiveContext' )
InteractiveContext( 'wx', 'OpenGLContext.wxinteractivecontext.wxInteractiveContext' )
InteractiveContext( 'glut', 'OpenGLContext.glutinteractivecontext.GLUTInteractiveContext' )
InteractiveContext( 'glfw', 'OpenGLContext.glfwinteractivecontext.GLFWInteractiveContext' )
InteractiveContext( 'egl', 'OpenGLContext.eglcontext.EGLContext' )
VRMLContext( 'pygame', 'OpenGLContext.pygamevrmlcontext.VRMLContext' )
VRMLContext( 'wx', 'OpenGLContext.wxvrmlcontext.VRMLContext' )
VRMLContext( 'glut', 'OpenGLContext.glutvrmlcontext.VRMLContext' )
VRMLContext( 'glfw', 'OpenGLContext.glfwvrmlcontext.VRMLContext' )
VRMLContext( 'egl', 'OpenGLContext.eglvrmlcontext.VRMLContext' )

# Imported for its side effect: the package registers the Qt backend with the
# registries above as it loads.  Absent unless the separate OpenGLContext-qt
# distribution is installed, which is the whole of what makes qt selectable.
try:
    import OpenGLContext_qt      # noqa: F401
except ImportError:
    pass

Loader( 'vrml97', 'OpenGLContext.loaders.vrml97.defaultHandler', ['.wrl','.wrz','.vrml','model/vrml','x-world/x-vrml','.wrl.gz'] )
Loader( 'obj', 'OpenGLContext.loaders.obj.defaultHandler', ['.obj'] )

# What `oglc-view` can open, keyed by file suffix and content type. One viewer
# serves every format; the adapter is chosen from the source itself.
Adapter( 'gltf', 'OpenGLContext.viewer.adapters.gltf.GLTFAdapter', ['.gltf','.glb','model/gltf+json','model/gltf-binary'] )
Adapter( 'vrml97', 'OpenGLContext.viewer.adapters.vrml.VRMLAdapter', ['.wrl','.wrz','.vrml','.wrl.gz','model/vrml','x-world/x-vrml'] )
Adapter( 'obj', 'OpenGLContext.viewer.adapters.obj.OBJAdapter', ['.obj','.obj.gz','model/obj'] )
# A tileset is any .json, so the registry only claims the conventional name; a
# document under another name is recognised by its content (adapters._sniff).
Adapter( 'tiles3d', 'OpenGLContext.viewer.adapters.tiles.TilesAdapter', ['tileset.json'] )

Node( 'Anchor', 'vrml.vrml97.basenodes.Anchor' )
Node( 'Appearance', 'OpenGLContext.scenegraph.appearance.Appearance' )
Node( 'AudioEmitter', 'OpenGLContext.scenegraph.audio.AudioEmitter' )
Node( 'AudioSource', 'OpenGLContext.scenegraph.audio.AudioSource' )
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
Node( 'Extrusion', 'OpenGLContext.scenegraph.extrusions.Extrusion' )
Node( 'Fog', 'OpenGLContext.scenegraph.fog.Fog' )
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
Node( 'PolyCone', 'OpenGLContext.scenegraph.extrusions.PolyCone' )
Node( 'PolyCylinder', 'OpenGLContext.scenegraph.extrusions.PolyCylinder' )
Node( 'PointLight', 'OpenGLContext.scenegraph.light.PointLight' )
Node( 'ParticleEmitter', 'OpenGLContext.scenegraph.particles.ParticleEmitter' )
Node( 'PointSet', 'OpenGLContext.scenegraph.pointset.PointSet' )
Node( 'PositionInterpolator', 'OpenGLContext.scenegraph.interpolators.PositionInterpolator' )
Node( 'ProximitySensor', 'vrml.vrml97.basenodes.ProximitySensor' )
Node( 'ScalarInterpolator', 'OpenGLContext.scenegraph.interpolators.ScalarInterpolator' )
Node( 'Shape', 'OpenGLContext.scenegraph.shape.Shape' )
Node( 'Sound', 'OpenGLContext.scenegraph.audio.Sound' )
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
Node( 'ShaderGeometry','OpenGLContext.scenegraph.shaders.ShaderGeometry' )

Node( 'Shader','OpenGLContext.scenegraph.shaders.Shader' )
Node( 'ROUTE','vrml.route.ROUTE' )
Node( 'IS','vrml.route.IS' )
