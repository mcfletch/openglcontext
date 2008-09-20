#!/usr/bin/env python
"""Installs OpenGLContext using setuptools

Run:
	python setup.py install
to install the package from the source archive.
"""
import os, sys
from setuptools import setup
# We don't technically require some of these, but they're so 
# useful leaving them out doesn't make sense...
install_requires = ['PyVRML97','PyOpenGL',]#'TTFQuery']

# Imaging does not like being installed as an egg on Linux 
# in my tests, as the Package is named PIL, not Imaging... blah.
#if sys.platform == 'win32':
#	install_requires.append( 'PIL' )
#else:
#	install_requires.append( 'Imaging' )

def is_package( directory ):
	dir,file = os.path.isdir( directory ), os.path.isfile( os.path.join( directory,'__init__.py' ))
	if dir and file:
		return True
	return False

def find_packages( where='.', rootPackage='OpenGLContext' ):
	"""Grr, why can't you specify current directory?"""
	yield rootPackage
	set = [
		(item,name)
		for (item,name) in [
			(item,os.path.join( where, item ))
			for item in os.listdir( where )
		]
		if is_package( name )
	]
	for item,name in set:
		subPackage = ".".join( (rootPackage, item) )
		for package in find_packages( name, subPackage ):
			yield package


if __name__ == "__main__":
	dataDirectories = [
		"docs",
		os.path.join( "docs","images"),
		os.path.join( "docs","style"),
		os.path.join('tests','wrls'),
		'resources',
	]
	extraArguments = {
		'classifiers': [
			"""License :: OSI Approved :: BSD License""",
			"""Programming Language :: Python""",
			"""Programming Language :: C""",
			"""Topic :: Software Development :: Libraries :: Python Modules""",
			"""Topic :: Multimedia :: Graphics :: 3D Rendering""",
			"""Intended Audience :: Developers""",
			"""Environment :: X11 Applications""",
			"""Environment :: Win32 (MS Windows)""",
		],
		'download_url': "https://sourceforge.net/project/showfiles.php?group_id=5988",
		'keywords': 'PyOpenGL,OpenGL,Context,OpenGLContext,render,3D,TrueType,text,VRML,VRML97,scenegraph',
		'long_description' : """Demonstration and Testing Contexts for PyOpenGL

OpenGLContext includes rendering contexts (including navigation)
for wxPython, PyGame and GLUT, as well as a partial context for
Tkinter.  It also includes support for rendering TrueType fonts,
and a significant subset of VRML97.  It provides fairly extensive
VRML97 scenegraph model.  It also includes the bulk of the tests
used to maintain and extend PyOpenGL.
""",
		'platforms': ['Win32','Linux','OS-X','Posix'],
	}
	### Now the actual set up call
	setup (
		name = "OpenGLContext",
		version = "2.1.0a3",
		description = "Demonstration and testing contexts for PyOpenGL/OpenGL-ctypes",
		author = "Mike C. Fletcher",
		author_email = "mcfletch@users.sourceforge.net",
		url = "http://pyopengl.sourceforge.net/context/",
		license = "BSD-style, see license.txt for details",

		packages = list(find_packages()),
		package_dir = {
			'OpenGLContext':'.',
		},
		install_requires = install_requires,
		
		# need to add executable scripts too...
		zip_safe = False, # data-files are not zip-friendly at the moment..

		include_package_data=True,
		package_data = {
			'OpenGLContext.tests': ['*.jpg','*.bmp','*.png','*.wrl','wrls/*.wrl'],
		},
		options = {
			'sdist': {
				'formats':['gztar','zip'],
			}
		},
		# non python files of examples      
		extras_require = {
			# Numeric support should likely be dropped at some point...
			'numeric':  ["PyVRML97[numeric]"],
			'parsing': ["PyVRML97[parsing]"],
			#'3dfonts': ["TTFQuery"],
		},
		dependency_links = [
			# PyVRML97
			"https://sourceforge.net/project/showfiles.php?group_id=19262",
			# TTFQuery/FontTools-numpy
			"https://sourceforge.net/project/showfiles.php?group_id=84080",
			# Imaging/PIL (PIL doesn't resolve on non-win32 with easy_install otherwise)
			"http://effbot.org/downloads/#Imaging",
		],
		
		entry_points = {
			'gui_scripts': [
				'choosecontext=OpenGLContext.bin.choosecontext:main',
				'vrml_view = OpenGLContext.bin.vrml_view:main',
			],
			'OpenGLContext.context': [
				'pygame=OpenGLContext.pygamecontext:PyGameContext',
				'wx=OpenGLContext.wxcontext:wxContext',
				'glut=OpenGLContext.glutcontext:GLUTContext',
				'tk=OpenGLContext.tkcontext:TkContext',
			],
			'OpenGLContext.interactivecontext': [
				'pygame=OpenGLContext.pygameinteractivecontext:PyGameInteractiveContext',
				'wx=OpenGLContext.wxinteractivecontext:wxInteractiveContext',
				'glut=OpenGLContext.glutinteractivecontext:GLUTInteractiveContext',
				'tk=OpenGLContext.tkinteractivecontext:TkInteractiveContext',
			],
			'OpenGLContext.vrmlcontext': [
				'pygame=OpenGLContext.pygamevrmlcontext:VRMLContext',
				'wx=OpenGLContext.wxvrmlcontext:VRMLContext',
				'glut=OpenGLContext.glutvrmlcontext:VRMLContext',
			],
			'OpenGLContext.loaders': [
				'vrml97=OpenGLContext.loaders.vrml97:defaultHandler',
				'obj=OpenGLContext.loaders.obj:defaultHandler',
			],
			'OpenGLContext.scenegraph.nodes': [
				'Anchor = vrml.vrml97.basenodes:Anchor',
				'Appearance = OpenGLContext.scenegraph.appearance:Appearance',
				'AudioClip = vrml.vrml97.basenodes:AudioClip',
				'Background = OpenGLContext.scenegraph.background:Background',
				'Billboard = OpenGLContext.scenegraph.billboard:Billboard',
				'Box = OpenGLContext.scenegraph.box:Box',
				'Collision = OpenGLContext.scenegraph.collision:Collision',
				'Color = vrml.vrml97.basenodes:Color',
				'ColorInterpolator = OpenGLContext.scenegraph.interpolators:ColorInterpolator',
				'Cone = OpenGLContext.scenegraph.quadrics:Cone',
				'Coordinate = OpenGLContext.scenegraph.coordinate:Coordinate',
				'CoordinateInterpolator = OpenGLContext.scenegraph.interpolators:CoordinateInterpolator',
				'Cylinder = OpenGLContext.scenegraph.quadrics:Cylinder',
				'CylinderSensor = vrml.vrml97.basenodes:CylinderSensor',
				'DirectionalLight = OpenGLContext.scenegraph.light:DirectionalLight',
				'ElevationGrid = vrml.vrml97.basenodes:ElevationGrid',
				'Extrusion = vrml.vrml97.basenodes:Extrusion',
				'Fog = vrml.vrml97.basenodes:Fog',
				'FontStyle = OpenGLContext.scenegraph.text.fontstyle3d:FontStyle',
				'Group = OpenGLContext.scenegraph.group:Group',
				'ImageTexture = OpenGLContext.scenegraph.imagetexture:ImageTexture',
				'IndexedFaceSet = OpenGLContext.scenegraph.indexedfaceset:IndexedFaceSet',
				'IndexedLineSet = OpenGLContext.scenegraph.indexedlineset:IndexedLineSet',
				'Inline = OpenGLContext.scenegraph.inline:Inline',
				'LOD = OpenGLContext.scenegraph.lod:LOD',
				'Material = OpenGLContext.scenegraph.material:Material',
				'MouseOver = OpenGLContext.scenegraph.mouseover:MouseOver',
				'MovieTexture = vrml.vrml97.basenodes:MovieTexture',
				'NavigationInfo = vrml.vrml97.basenodes:NavigationInfo',
				'Normal = vrml.vrml97.basenodes:Normal',
				'NormalInterpolator = vrml.vrml97.basenodes:NormalInterpolator',
				'OrientationInterpolator = OpenGLContext.scenegraph.interpolators:OrientationInterpolator',
				'PixelTexture = OpenGLContext.scenegraph.imagetexture:PixelTexture',
				'PlaneSensor = vrml.vrml97.basenodes:PlaneSensor',
				'PointLight = OpenGLContext.scenegraph.light:PointLight',
				'PointSet = OpenGLContext.scenegraph.pointset:PointSet',
				'PositionInterpolator = OpenGLContext.scenegraph.interpolators:PositionInterpolator',
				'ProximitySensor = vrml.vrml97.basenodes:ProximitySensor',
				'ScalarInterpolator = OpenGLContext.scenegraph.interpolators:ScalarInterpolator',
				'Shape = OpenGLContext.scenegraph.shape:Shape',
				'Sound = vrml.vrml97.basenodes:Sound',
				'Sphere = OpenGLContext.scenegraph.quadrics:Sphere',
				'SphereSensor = vrml.vrml97.basenodes:SphereSensor',
				'SpotLight = OpenGLContext.scenegraph.light:SpotLight',
				'Switch = OpenGLContext.scenegraph.switch:Switch',
				'Text = OpenGLContext.scenegraph.text.text:Text',
				'TextureCoordinate = vrml.vrml97.basenodes:TextureCoordinate',
				'TextureTransform = OpenGLContext.scenegraph.texturetransform:TextureTransform',
				'TimeSensor = OpenGLContext.scenegraph.timesensor:TimeSensor',
				'TouchSensor = vrml.vrml97.basenodes:TouchSensor',
				'Transform = OpenGLContext.scenegraph.transform:Transform',
				'Viewpoint = OpenGLContext.scenegraph.viewpoint:Viewpoint',
				'VisibilitySensor = vrml.vrml97.basenodes:VisibilitySensor',
				'WorldInfo = vrml.vrml97.basenodes:WorldInfo',
				
				'sceneGraph = OpenGLContext.scenegraph.scenegraph:SceneGraph',
				'IndexedPolygons = OpenGLContext.scenegraph.indexedpolygons:IndexedPolygons',
				'FontStyle3D = OpenGLContext.scenegraph.text.fontstyle3d:FontStyle3D',
				'SimpleBackground = OpenGLContext.scenegraph.simplebackground:SimpleBackground',
				'CubeBackground = OpenGLContext.scenegraph.cubebackground:CubeBackground',
				'SphereBackground = OpenGLContext.scenegraph.spherebackground:SphereBackground',
				'MMImageTexture = OpenGLContext.scenegraph.imagetexture:MMImageTexture',
				
				'Contour2D = OpenGLContext.scenegraph.nurbs:Contour2D',
				'NurbsCurve = OpenGLContext.scenegraph.nurbs:NurbsCurve',
				'NurbsCurve2D = OpenGLContext.scenegraph.nurbs:NurbsCurve2D',
				'NurbsDomainDistanceSample = OpenGLContext.scenegraph.nurbs:NurbsDomainDistanceSample',
				'NurbsSurface = OpenGLContext.scenegraph.nurbs:NurbsSurface',
				'NurbsToleranceSample = OpenGLContext.scenegraph.nurbs:NurbsToleranceSample',
				'Polyline2D = OpenGLContext.scenegraph.nurbs:Polyline2D',
				'TrimmedSurface = OpenGLContext.scenegraph.nurbs:TrimmedSurface',
			],
		},
		**extraArguments
	)
