"""VRML97 Switch node"""
import weakref

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
        # What the switch is already showing, so the first assignment naming it
        # is recognised as the no-op it is -- and so turning the switch off is
        # recognised as a change away from it.
        chosen = self._chosen()
        self._announced = weakref.ref( chosen ) if chosen is not None else None
        dispatcher.connect( 
            self._onSwitchChange, 
            signal=('set',self.__class__.whichChoice), 
            sender=self 
        )
    def _chosen( self ):
        """The child `whichChoice` names, or None when it names nothing"""
        if self.whichChoice < 0 or self.whichChoice >= len(self.choice):
            return None
        return self.choice[self.whichChoice]
    def _onSwitchChange( self, value ):
        """Tell the world when the switch's child has changed

        The watcher fires on every assignment to `whichChoice`, and
        level-of-detail assigns it each frame from the viewer's distance, so
        most assignments name the child already being drawn. The signal reports
        a change of child: an assignment that chooses the same one is not one,
        and announcing it would wake every receiver for nothing.

        Held weakly, so remembering what was announced does not keep a child
        alive after the switch has let go of it.
        """
        value = self._chosen()
        announced = self._announced() if self._announced is not None else None
        if value is announced:
            return
        self._announced = weakref.ref( value ) if value is not None else None
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
    