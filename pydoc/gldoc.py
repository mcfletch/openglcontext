"""DefaultFormatter subclass providing automatic OpenGL function name links"""
from pydoc2 import *
from find_gldoc import findName

class GLFormatter( DefaultFormatter):
    """Adds automatic link creation for OpenGL call references"""
    def namelink(self, name, *dicts):
        """Adds support for OpenGL name resolution"""
        link = findName( name )
        if link:
            return '<a href="%s">%s</a>' % (link, name)
        return apply( DefaultFormatter.namelink, ( self, name,)+dicts )