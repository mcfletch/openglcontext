"""VRML97 Switch node"""
from vrml.vrml97 import basenodes, nodetypes
from OpenGLContext.scenegraph import boundingvolume
from pydispatch import dispatcher
SWITCH_CHANGE_SIGNAL = 'switch-choice-change'

class Switch(basenodes.Switch):
    """Switch node based on VRML 97 Switch
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Switch
    """
    def __init__( self, *args, **named ):
        """Setup watcher for whichChoice and children"""
        super(Switch,self).__init__( *args, **named )
        dispatcher.connect( 
            self._onSwitchChange, 
            signal=('set',self.__class__.whichChoice), 
            sender=self 
        )
    def _onSwitchChange( self ):
        """Generate signal telling the world that switch's child has changed"""
        if self.whichChoice < 0 or self.whichChoice >= len(self.choice):
            value = None 
        else:
            value = self.choice[self.whichChoice]
        dispatcher.send(
            sender = self,
            signal = SWITCH_CHANGE_SIGNAL,
            value = value,
        )
    def renderedChildren( self, types= (nodetypes.Children, nodetypes.Rendering,) ):
        """Children is not the source, choice is"""
        if self.whichChoice < 0 or self.whichChoice >= len(self.choice):
            return []
        else:
            node = self.choice[self.whichChoice]
            if isinstance( node, types):
                return [node]
            return []
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
        dependencies = [(self,'choice'),(self,'whichChoice')]
        unbounded = 0
        for child in self.renderedChildren():
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
    