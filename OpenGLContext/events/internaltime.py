"""Track a (potentially scaled) time with respect to an external time"""
from timeevents import *

class InternalTime(object):
    """Track an internal time.

    Internal times allow for fractional and absolute reporting
    of a current time with a given duration. The internal time
    potentially has a transformation applied to the incoming time
    values, which allows for time reversal, slowdown and speed up.
    """
    def __init__(
        self, duration=1.0, repeating=0, multiplier = 1.0,
        current=None, currentCount=None,
        discreteOnly=0
    ):
        """Initialise (but don't start) the timer
        
        duration -- length in seconds (float) for a single cycle
        repeating -- if 1, will not stop when hit duration, but will repeat forever
            elif positive count > 1, will repeat X times duration
        multiplier -- the time multiplier
            1.0 -> real-time, .1 -> slow-mo, -1.0 -> rewind
        current -- current internal time, lets you start at other than 0 seconds
            use resume to do the restarting
        currentCount -- the current count for repeats, lets you start partway
            through the set
        discreteOnly -- suppress the generation of fractional events...
        """
        self.duration = float(duration)
        if not duration:
            raise ValueError( """%s given %s as a duration, cannot have NULL duration"""%(duration))
        self.active = 0
        self.lastRealTime = None
        self.count = currentCount or 0
        self.repeating = repeating
        self.multiplier = multiplier
        self.discreteOnly = discreteOnly
        if current is not None:
            self.current = float(current)
        else:
            self._resetCurrent()
    def __repr__( self ):
        return """<%s active=%s duration=%s repeating=%s multiplier=%s discreteOnly=%s>"""%(
            self.__class__.__name__,
            self.active,
            self.duration,
            self.repeating,
            self.multiplier,
            self.discreteOnly,
        )
        
    def getCurrent( self ):
        """Get current internal time

        You could pass this to another internal time
        that's dependent on this time as "realTime"
        """
        return self.current
    def getFraction( self ):
        """Get current internal time as fraction of duration.
        """
        return self.current/ self.duration
    def getExternal( self ):
        """Get the last "external" time passed to the timer"""
        return self.lastRealTime
    
    def start( self, realTime):
        """Start the timer from 0 for forward multipliers, duration for reverse multipliers"""
        self.active = 1
        self.lastRealTime = realTime
        self._resetCurrent()
        self.count = self.count + 1
        return [ StartEvent( self ) ]
    def pause( self, realTime):
        """Pause the timer, use resume to continue

        Note: does not create a FractionalEvent
        """
        self.active = 0
        return [ PauseEvent( self ) ]
    def resume( self, realTime):
        """Continue a paused timer

        Note: does not create a FractionalEvent
        """
        self.active = 1
        self.lastRealTime = realTime
        return [ ResumeEvent( self ) ]
    def stop( self, realTime):
        """Stop this cycle (reset current fraction)"""
        if self.active:
            self.active = 0
            self._resetCurrent()
            return [ FractionalEvent(self), StopEvent( self ) ]
        return []
    
    def poll( self, realTime):
        """Called by system/clients to determine if there are any waiting events"""
        if self.active:
            delta = realTime-self.lastRealTime
            self.lastRealTime = realTime
            self.current = self.current + (delta* self.multiplier)
            if self._naturalFinish():
                if self.repeating:
                    return self._period( realTime )
                else:
                    return self._finish(realTime)
            elif not self.discreteOnly:
                return [FractionalEvent( self )]
        return ( )

    # internal utility functions
    def _naturalFinish( self ):
        """Determine if there has been a "natural finish" of the timer"""
        return (
            (self.multiplier > 0 and self.current >= self.duration) or
            (self.multiplier < 0 and self.current <= 0)
        )
    def _repeats( self ):
        """Does the timer repeat, 0-no, 1-yes, >1-yes, count times"""
        return (self.repeating > 0)
        
    def _finish( self, realTime ):
        """Set in active and return finalization events"""
        self.active = 0
        if self.discreteOnly:
            return [ StopEvent( self ), ]
        else:
            return [ FractionalEvent (self), StopEvent( self ), ]
    def _period( self, realTime ):
        """Interpret a cycle/period boundary, returning appropriate messages"""
        messages = []
        if self._repeats() and (self.count < self.repeating or self.repeating == 1):
            # repeat forever, or not yet done
            self._resetCurrent( 0 )
            if not self.discreteOnly:
                messages.append( FractionalEvent( self ))
            self.count = self.count + 1
            messages.append( CycleEvent( self ))
        else:
            # we're finished!
            return self._finish( realTime )
        return messages
    def _resetCurrent( self, restart = 1 ):
        """Reset the current cycle

        restart -- whether to return to the start of the cycle,
            or merely to reset the overall cycle count
        """
        if restart:
            if self.multiplier < 0.0:
                self.current = self.duration
            else:
                self.current = 0.0
        else:
            difference = round(abs(self.current % self.duration), 4)
            self.current = difference


            