"""Functions for acquiring and instantiating available testing contexts

Testing modules can use these abstract functions to allow for
automatic adaptation to new interactive contexts.  You should
not use this module for real world applications, as it is
unlikely that nontrivial code will be completely stable across
all interactive context classes."""

PREFERENCELIST = ('pygame', 'wx', 'glut', 'tk' )
import traceback, string, os
from OpenGLContext.debug.logs import context_log as log
try:
	from OpenGLContext import context
	userPreference = context.Context.getDefaultContextType()
	if userPreference in PREFERENCELIST:
		PREFERENCELIST = (userPreference,)+ tuple([x for x in PREFERENCELIST if x !=userPreference])
except IOError, err:
	pass
print 'PREFERENCELIST',  PREFERENCELIST

def getInteractive( preferenceList= None ):
	"""Retrieve the preferred testing context:
		returns BaseContext (a class) and a MainFunction which starts the GUI event loop
	"""
	if preferenceList is None:
		preferenceList = PREFERENCELIST
	
	entrypoints = context.Context.getContextTypes()
	for preference in preferenceList:
		for entrypoint in entrypoints:
			if entrypoint.name == preference:
				try:
					cls = context.Context.getContextType( entrypoint )
				except ImportError, err:
					log.warn( """Failed loading testing context %r: %s""", entrypoint.name, err )
				else:
					if cls:
						def mainLoop( cls, *args, **named ):
							return cls.ContextMainLoop( *args, **named )
						return cls, mainLoop
	raise ImportError ("""Could not import a suitable vrml context for the preference set %s""" % ( preferenceList,) )
