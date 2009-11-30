"""VRML97 TimeSensor node"""
from vrml.vrml97 import basenodes, nodetypes
from vrml import protofunctions
from OpenGLContext.events import timer
from vrml import cache
from pydispatch import dispatcher

class TimeSensor(basenodes.TimeSensor):
    """TimeSensor node based on VRML 97 TimeSensor
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#TimeSensor


    TimeSensor is the VRML97 node which generated time-based
    events.  These are normally used to run animations or,
    with scripts, to provide higher-level interactivity.
    """
    def getTimer( self, context ):
        """Retrieve the timer for this time-sensor"""
        timerObject = context.cache.getData( self, key='timer' )
        if timerObject is None:
            timerObject = timer.Timer(
                duration = self.cycleInterval,
                repeating = self.loop,
            )
            holder = context.cache.holder(
                self,
                key = "timer",
                data = timerObject,
            )
            for name in ("cycleInterval", "loop"):
                field = protofunctions.getField( self, name )
                holder.depend( self, field )
            timerObject.register( context )
            timerObject.start ()
            timerObject.addEventHandler( 
                "fraction", function = self.onFraction 
            )
            timerObject.addEventHandler( "cycle", function = self.onCycle )
        return timerObject
    def bind( self, context ):
        """Bind this time-sensor to a particular context"""
        self.getTimer(context)
        return True
    def onFraction( self, event ):
        """Handle a fractional event from our Timer"""
        self.fraction_changed = event.fraction()
        self.time = event.value()
    def onCycle( self, event ):
        """Handle a cycle event from our Timer"""
        self.cycleTime = event.value()