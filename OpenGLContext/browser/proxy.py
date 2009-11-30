from vrml import field
class Proxy( object ):
    """Wrapper for a field"""
    def __init__(
        self, base,
    ):
        """Initialize the proxy object"""
        self.base = base
    def __get__( self, client, *arguments, **named ):
        """Retrieve value, and call getter(value, *arguments, **named)"""
        result = self.base.__get__( client, *arguments, **named )
        name = 'get_'+self.base.name
        if hasattr( client, name):
            getattr( client, name)( result, self.base, *arguments,**named)
        return result
    def __set__( self, client, value, *arguments, **named ):
        """Set value, and call setter(value, *arguments, **named)"""
        result = self.base.__set__( client, value, *arguments, **named )
        name = 'set_'+self.base.name
        if hasattr( client, name):
            getattr( client, name)( value, self.base, *arguments,**named)
        return result
    def __delete__( self, client, *arguments, **named ):
        """Delete value, call deller( value, *arguments, **named)"""
        result = self.base.__set__( client, *arguments, **named )
        name = 'del_'+self.base.name
        if hasattr( client, name):
            getattr( client, name)( result, self.base, *arguments,**named)
        return result


def proxyField( *arguments, **named ):
    """Create a new proxied field"""
    base = field.newField( *arguments, **named )
    return Proxy( base )
    
##class Forwarder( object ):
##	"""Mechanism for forwarding a set to a given sub-object"""
##	def __get__( self, client = None ):
##		if client is None:
##			return self
##		else:
##			return self.__class__( self.definition, client )
##	def __init__( self, definition, client=None ):
##		self.definition = definition
##		self.client = client
##	def __call__( self, *arguments, **named ):
##		if self.client is None and arguments:
##			client = arguments[0]
##			arguments = arguments[1:]
##		elif self.client is None:
##			raise TypeError( """Unbound forwarder not passed a client object as first argument""" )
##		else:
##			client = self.client
##		for attribute in self.definition:
##			
    