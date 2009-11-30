"""Common implementation for grouping-type nodes"""
from OpenGL.GL import *
from vrml.vrml97 import nodetypes
from vrml import node, field
from OpenGLContext.scenegraph import boundingvolume
from pydispatch.dispatcher import connect 
import weakref

class ChildrenSensitiveField( node.MFNode ):
    """Field sub-class/mix-in for checking children for sensitivity"""
    fieldType = "MFNode"
    def checkSensitive( self, client, value ):
        """Check value to see if there are any sensor children"""
        client.sensitive = 0
        for child in value:
            if isinstance( child, nodetypes.PointingSensor ):
                client.sensitive = 1
                break
        return value
    def fset( self, client, value, notify=1 ):
        """On set, do regular set, then check for sensitivity"""
        value = super( ChildrenSensitiveField, self).fset( client, value, notify )
        return self.checkSensitive(client,value)
    def fdel( self, client, notify=1):
        """On del, do regular del, then check for sensitivity"""
        value = super( ChildrenSensitiveField, self).fset( client, value, notify )
        client.sensitive = 0
        return value

def _cacheClear( signal, sender, subsignal=None, subvalue=None ):
    (typ,field) = signal 
    cache = field.getCache( sender )
    if cache is not None:
        if subsignal is not None:
            # just update the cache with the single change...
            if subsignal == 'new':
                for key,current in cache.items():
                    if isinstance( subvalue, key ):
                        current.append( subvalue )
            elif subsignal == 'del':
                for key,current in cache.items():
                    if subvalue in current:
                        current.remove( subvalue )
        else:
            cache.clear()

class ChildrenTypedField( ChildrenSensitiveField ):
    """Field sub-class/mix-in for iterating over children by node-types"""
    fieldType = "MFNode"
    def getCache( self,client ):
        cache_key = '__typed_children_%s__'%(self.name,)
        cache = getattr( client, cache_key, None )
        if cache is None:
            cache = {}
            setattr( client, cache_key, cache )
            connect( 
                _cacheClear,
                signal = ('set',self),
                sender = client,
                weak = False,
            )
        return cache
    def byType( self, client, types ):
        cache = self.getCache(client)
        new = cache.get( types )
        if new is None:
            new = [
                x for x in self.fget( client ) 
                if isinstance(x,types)
            ]
            cache[ types ] = new 
        return new

class Grouping(object):
    """Light-weight grouping object based on VRML 97 Group Node

    Attributes of note within Grouping objects:

        children -- list of renderable objects with
            ChildrenSensitiveField implementation that
            sets the parent to sensitive if there is
            a PointingSensor child

    Note that this is a Mix-in class for Node classes
    """
    sensitive = field.newField( " sensitive", "SFBool", 0, 0)
    children = ChildrenTypedField( 'children', 1, [])
    def renderedChildren( self, types= (nodetypes.Children, nodetypes.Rendering,) ):
        """List all children which are instances of given types"""
        return self.__class__.children.byType( self, types )
    def visible( self, frustum=None, matrix=None, occlusion=0, mode=None ):
        """Check whether this grouping node intersects frustum

        frustum -- the bounding volume frustum with a planes
            attribute which defines the plane equations for
            each active clipping plane
        matrix -- the active OpenGL transformation matrix for
            this node, used to determine the transforms for
            the grouping-node's bounding volumes.  Is calculated
            from current OpenGL state if not provided.
        """
        
        return self.boundingVolume(mode).visible( frustum, matrix, occlusion=occlusion, mode=mode )

    def boundingVolume( self, mode ):
        """Calculate the bounding volume for this node

        The bounding volume for a grouping node is
        the union of it's children's nodes, and is
        dependent on the children of the node's
        bounding nodes, as well as the children field
        of the node.
        """
        current = boundingvolume.getCachedVolume( self )
        if current is not None:
            return current
        # need to create a new volume and make it depend
        # on the appropriate fields...
        volumes = []
        dependencies = [(self,'children')]
        unbounded = 0
        for child in self.children:
            try:
                if hasattr(child, 'boundingVolume'):
                    volume = child.boundingVolume(mode)
                    volumes.append( volume )
                    dependencies.append( (volume, None) )
                else:
                    unbounded = 1
                    break
            except boundingvolume.UnboundedObject:
                unbounded = 1
        try:
            volume = boundingvolume.BoundingBox.union( volumes, None )
        except boundingvolume.UnboundedObject:
            unbounded = 1
        if unbounded:
            volume = boundingvolume.UnboundedVolume()
        return boundingvolume.cacheVolume( self, volume, dependencies )
    