"""VRML97 Inline node"""
from vrml.vrml97 import basenodes, nodetypes
from vrml import field, protofunctions, fieldtypes
from OpenGLContext import context

class InlineURLField( fieldtypes.MFString ):
    """Field for managing interactions with an Inline's URL value"""
    fieldType = "MFString"
    def fset( self, client, value, notify=1 ):
        """Set the client's URL, then try to load the scene"""
        value = super(InlineURLField, self).fset( client, value, notify )
        import threading
        threading.Thread(
            name = "Background load of %s"%(value),
            target = client.loadBackground,
            args = ( value, context.Context.allContexts,),
        ).start()
        return value
    def fdel( self, client, notify=1 ):
        """Delete the client's URL, which should delete the scene as well"""
        value = super( InlineURLField, self).fdel( client, notify )
        del client.scenegraph
        return value


class Inline(basenodes.Inline):
    """Inline VRML97 scene based on VRML 97 Inline
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Inline
    """
    scenegraph = None
    def renderedChildren( self, types= (nodetypes.Children, nodetypes.Rendering,) ):
        """Choose child from level that is at appropriate range"""
        if self.scenegraph:
            return self.scenegraph.children
        return []
    url = InlineURLField(
        'url', 1, list
    )
    def loadBackground( self, url, contexts=() ):
        """Load an image from the given url in the background

        url -- SF or MFString URL to load relative to the
            node's root's baseURL

        On success:
            Sets the resulting PIL image to the
            client's image property (triggering an un-caching
            and re-compile if there was a previous image).

            if contexts, iterate through the list calling
            context.triggerRedraw(1)
        """
        try:
            from OpenGLContext.loaders.loader import Loader
        except ImportError:
            pass
        else:
            for u in url:
                try:
                    baseNode = protofunctions.root(self)
                    if baseNode:
                        baseURI = baseNode.baseURI
                    else:
                        baseURI = None
                    
                    result = Loader.load( u, baseURL = baseURI )
                except IOError:
                    pass
                else:
                    print 'loaded', u
                    self.scenegraph = result
                    for context in contexts:
                        c = context()
                        if c:
                            c.triggerRedraw(1)
                    return
        warnings.warn( """Unable to load any scene from the url %s for the node %s"""%( url, str(self)))
        