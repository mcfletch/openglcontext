"""Script to automatically generate OpenGLContext documentation"""
import gldoc, pydoc2

if __name__ == "__main__":
	excludes = [
		"OpenGL.GL",
		"OpenGL.GLU",
		"OpenGL.GLUT",
		"OpenGL.GLE",
		"OpenGL.GLX",
		"wxPython.wx",
		"Numeric",
		"numpy",
		"_tkinter",
		"Tkinter",
		"math",
		"string",
		"pygame",
		"pygame.locals",
	]
	stops = [
		"OpenGL.Demo.NeHe",
		"OpenGL.Demo.GLE",
		"OpenGL.Demo.da",
	]

	modules = [
		"OpenGLContext",
		"wxPython.glcanvas",
		"vrml",
		'logging',
		"OpenGL",
		"ttfquery",
		"simpleparse",
		"fontTools",
		"numpy",
		"Numeric",
	]	
	pydoc2.PackageDocumentationGenerator(
		baseModules = modules,
		destinationDirectory = ".",
		exclusions = excludes,
		recursionStops = stops,
		formatter = gldoc.GLFormatter(),
	).process ()
	
