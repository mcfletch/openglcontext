OpenGLContext 2.0

Changelog:

2.0.0c1 -> 2.1.0a1

	PyOpenGL 3.x compatibility

	Support for Numpy

	PyVRML97 project split back out into separate project

	A few more tests/demos
	
	Register and look up node-types explicitly using plug-in framework.
	
	Register and look up context-types explicitly using plug-in framework.
	
	Expose scripts for vrml_view and choosecontext.

2.0.0b1 -> 2.0.0c1

Refactoring and code cleanup:

	Major scripts moved to the bin subdirectory.
	
	Contexts now have classmethods for their "main" functions.
	
	Scripts to choose the default context class and font.
	
	Application data directory now hidden on non-Win32 platforms
	(.OpenGLContext instead of OpenGLContext).
	
	Mechanism for specifying context attributes (size, depth,
	buffer type, etceteras).  See the 
		contextdefinition.ContextDefinition
	Node-class for details.
	
	Default getScenegraph implementation of getattr(self,'sg',None).

	Force flush before swap buffers (attempt to compensate for 
	rendering artefacts on Linux).

Non-standard MouseOver node for constructing buttons.

	PyGame interactivity fixes
	
		Work on making the PyGame interactions, particularly keyboard
		repeats, act in the same way as the keyboard interactions under
		wxPython and GLUT
		
	wxTestingContext icons
	
		wxPython testing context now has icons set for the frame so that
		it isn't showing the (ugly) default windows icons.
		
	A few more tests/demos
	
		wx_with_controls.py -- demo of wxPython context + interacting
			control outside the context
			
		arbwindowpos.py -- ARB extension for pixel-level positioning of
			bitmap position within the rendering window
			
	Resources directory w/ OpenGLContext icons for easy import
	
	Dispatcher module completely factored out into the SourceForge 
	pydispatcher project.
	
	Switched registerCallback to using class-methods, switched demo 
	to using those methods to allow non-context-dependent registration 
	of mouse events.
	
	Refactoring of mouse-based events, addition of code to allow 
	"captured" and "bubbling" events (parent recieves events 
	before/after children and can cancel further propagation).
	
	Bug Fixes:
	
		Try ImageTexture stub when PIL not available
		
		Workaround for strange bug with wxPython where the main thread 
		appears as two different objects, depending on whether it's in 
		a callback or not.
	
		Test for bugs in PyOpenGL's feedback mode operation
		
	Additionally, some work has been done on the browser sub-package,
	but it is still not finished to even prototype stages yet.  It may,
	however, be useful as a source of sample code to some people.

2.0.0a4 -> 2.0.0b1

	Optimization and accelerator modules:
	
		The entire rendering pipeline has been noticeably sped up,
		with a number of key performance bottlenecks rewritten
		using C modules (which should compile on any Python+Numeric
		setup).

	Frustum Culling:
	
		Bounding box calculation for common geometry types, including
		caching and automatic updating of bounding boxes.
		
		Frustum extraction from model view matrix.
	
	Polygonal and Bitmap Text (TTF):
	
		Use of (new) ttfquery package based on the fonttools package
		allows scanning for system fonts (or fonts in a given directory)
		and doing primitive face-name matching for those fonts.  Uses
		direct extraction of font outlines for polygonal text.
	
		Context customization point for setup
		
		Eliminated BitmapText node, use FontStyle.format ='bitmap' 
		instead.
		
	All rendering methods and functions are now given a "mode"
	argument, and generally pass that argument to the functions 
	they call to provide access to the current renderpass, context,
	etc.
		
	GLE-based extrusion geometry types added
	
	Added object for managing initialized extensions for a given
	context

	Added some utility mechanisms for dealing with parametric 
	equations of planes expressed as 4-item arrays.
	
	Switch to using Mip-mapped textures by default
	
	Polygon tessellation code reworked and generalized (used
	by the polygonal text engine, for instance).
	
	Added (disabled) code to use display lists instead of array 
	geometry for rendering indexed face sets.
	
	Broke out vertex and polygon classes from IFS module
	
	wxPython context:

		Added wants-chars style to work properly in panels
		
		wxPython context should also be somewhat more stable,
		particularly when used with Python 2.2.3.  Workarounds for
		Python 2.2.2 bugs are still in place, but they do not
		guarantee that no errors will occur, merely reduce the
		likelihood when using Python 2.2.2.
		
		Added ability to provide an OpenGL attribList for wxContext.

	Bug Fixes (too many to list everything):
	
		Textures and display-lists in particular have significant
		bug fixes checked in.  Many of these were simply making
		the objects context-specific.  Also caught strange bug where
		display list creation is returning 0 rather than raising
		exceptions.
		
		Textured transparent geometry (i.e. geometry whose textures
		have Alpha channels) are now rendered during the transparent 
		rendering pass, rather than the opaque rendering pass.
		
		Fix for unlit textured geometry not showing white as base colour.
		
		TextureTransform logic bug eliminated (was occasionally leaving 
		the texture transform active).
				
		The cache API is now  easier to use, and hopefully will not
		be triggering Python 2.2.2 errors anymore.
		
		Python 2.3 compatibility revisions
		
		Removed premature optimisation which was eliminating USE'd 
		transparent shapes even though the matrices were different.
		
		Fix for build_normalPerVertex to properly build the normals 
		(produces true smoothing, rather than the rather strange 
		looking results of the previous version).
		

2.0.0a3 -> 2.0.0a4

	PROTOs:

		Initial support for prototyped nodes added, which
		allows for loading a wider swath of VRML content. No
		support for EXTERNPROTO as-of-yet.

		Refactored vrml.vrml97.prototypes into vrml.route and
		vrml.vrml97.script modules

	Events:

		Partial rework of the mouse-events API to allow the
		events to be handled during the event-cascade,
		addition of support for event-cascade deferal of event
		processing to eventhandler mix-in and Context classes.

		Addition of support in the event base class for tracking
		visited node/field combinations, calling of base-class
		initializer from the sub-class initializer's.

		ROUTEs are now active for fields

		IS mappings now work for PROTO fields (sub-class of ROUTE)

		Introduction of Event class in the vrml package, should
		become the base-class for OpenGLContext.events.event

	Cleanup of bugs in Shape,  Switch and WGLFont where corner-
	cases were not properly caught (e.g. no geometry, whichChoice
	out-of-bounds, no text on a line)

	IndexedFaceSet:
		
		Reworked generation code extensively, now supports
		colour-per-face and normal-per-face modes of VRML97

		Added a few sanity checks as well.

	PixelTexture node added.

	Preliminary Cylinder and Cone implementations.

	Stub implementations of LOD, Inline and Billboard nodes.

	Fix for transparent-geometry rendering (depth-buffer-testing
	enabled).

	Consolidated vrml.node and vrml.vrml97.node into vrml.node
	Moved fieldtypes to vrml package instead of VRML97 package

	Made default testing-context preference-sequence wx, Pygame,
	then GLUT

	Made all Bindable types also act as Children, since they are
	present in the scenegraph hierarchy.

	Fix for parsing hexidecimal-encoded SFImage fields (as seen
	in PixelTextures).

	Work-around for Python 2.2.2 calling of receiver methods in
	dispatcher.

	Considerably more robust getField implementation in
	protofunctions

2.0.0a2 -> 2.0.0a3

	Major Documentation updates (almost all doc-strings are
	updated in all modules).
	
	Loaders:

		Fixed bug with local-file loading where a local-file combined 
		with the url ../ would give a result of: z:../ , we now create 
		a file-path url in cases where a local-file is loaded.
		
		Moved vrml2pklgz script to loaders module.
		
		Re-added "dump" method to VRML97 loader.

	ViewPlatform:
	
		Fix for the straighten method
		
		Elimination of distance attribute
		
		Switch to new-style classes
		
		Loosening of the API for setPosition and setOrientation
		
		Fix for bug in the "forward" method
		
		Mix-in:
		
			Eliminated trackball attribute and unProject method, 
			commented out the unused slider interface

	Minor tweaks/optimisations to vectorutilities.

	Nodes:
	
		Changed Node.externalURL back to a simple attribute value
		of the class (bug-fix)
	
		Made SFNode and MFNode donate rootSceneGraph to children
		without them when values are set.
		
		Eliminated unused WeakMFNode field-type
		
		Fixed bug in WeakField implementation (returned a weak 
		reference)
		
		Added a bound field to CubeBackground.
		
		Fixed inheritence for WeakSFNode, eliminated cube-background 
		work-around for rootSceneGraph tracking.
	
		Texture/ImageTexture:
	
			Refactored PIL texture conversions
			
			Fixed typo/copying bug in Texture.__del__
			
			Fix for image loading (default baseURI re-instated), 
			reduced levels on a number of log messages
			
		Fix for cube-background render when last glColor set
		the color to black.
		
		Added fields Background to shadow those in CubeBackground 
		which prevent ImageTexture objects being linearised to 
		VRML97 where they shouldn't be.
	
	Complete rework of the field.Field implementation to 
	eliminate the seperate "fieldtype" objects in favour
	of making fieldtypes the actual type (class) of the 
	field.  [ MAJOR CHANGE ]

	Unused methods deleted from OverallPass
	
	Fixed bug in the builtin( ) function, it would only properly
	report for Nodes before, instead of working for both Nodes or
	prototypes/classes.
	
	Events:
	
		Eliminated use of Start and Stop Timer Events as 
		parents for Pause and Resume events
	
		InternalTime's now generate FractionalEvents in a few
		more places.

		Moved the examine manager to the events package
		
		EventManger.registerCallback raises NotImplementedError
		instead of SystemError if a sub-class doesn't implement
		the method.
		
		Minor cleanup in Event and EventHandler classes

	Switch a few classes to being new-style classes.

	Testing Code:
		
		ambient_only made a sub-class of the vrml_view test
		
		Removed obsolete glut stencil buffer test script
			
	
2.0.0a1 -> 2.0.0a2

	Made scenegraph.regDefName de-register references to the 
	object by it's previous defName if possible.

	Added PROTO name declaration to BitmapText

	Changed NurbsTrimmedSurface name to TrimmedSurface to 
	follow the nurbs-extension naming scheme

	Added "standardPrototype" function to loaders.vrml97 to
	allow for programmatic registry of standardPrototypes for
	the loader

	Documentation updates.
	
	A few setup and manifest changes.
	
	Added a texture-specific log to the debug/logs module.

	Addition of "root" protofunction for getting the root
	scenegraph for a node (doesn't currently support 
	automatically setting the root field for children, however)

	Elimination of weakref dicts for implementating scenegraph, 
	uses protofunctions instead

	Elimination of "DEF" and "PROTO" references in favour of
	protofunctions.defName and protofunctions.protoName

	Image and Texture Loading:
	
		Initial support for loading textures across the network,
		basically it's the original VRML97 loader with a bit of
		refactoring to support both images and scenes.
		
		Caching textures (only creating a single OpenGL texture
		if there are multiple ImageTextures which use the same 
		PIL image)
		
		PIL paletted texture -> RGB
		
		PIL resize of non-power-of-two textures

	IFS Tesellation -- commented out debugging code
	when IFS runs out of vertex indices before it
	runs out of other indices, just considers itself
	done now (lets some malformed content load)
	
	.cvsignore files added throughout
	
	Added missing attribution for glprint test
	
		
