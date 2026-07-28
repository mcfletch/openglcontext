"""How long the last frames took, measured but never drawn.

This node records frame durations; **showing** them is the developer overlay's
job (:mod:`OpenGLContext.ui.debugoverlay`), which reads this through a
registered provider.  Keeping the measurement here and the drawing there is
what lets a core-profile context report its frame rate at all: the display this
node used to do went through fixed-function calls that a core profile does not
have.
"""
from vrml import node, field


class FrameCounter( node.Node ):
    """Simple node holding Frame-counting values

    This node is used to hold information about the amount
    of time required to render frames for the context.
    """
    PROTO = 'FrameCounter'
    count = field.newField( 'count', 'SFInt32', 1, 0)
    totalTime = field.newField( 'totalTime', 'SFFloat', 1, 0.0)
    lastTime = field.newField( 'lastTime', 'SFFloat', 1, 0.0)
    # Window of recent frame durations for the displayed rate. A *cumulative*
    # average (count/totalTime) bakes in one-off stalls forever -- a synchronous
    # model load (network + decode) or the first-frame shader compile lands in a
    # timed frame and permanently drags the number down. A windowed median
    # reflects current rendering speed and shrugs off those outliers.
    _recent = None
    _RECENT_WINDOW = 90

    def addFrame( self, duration ):
        """Add the duration of a single frame to the counter

        This method does *not* send field changed events, so
        should not trigger a refresh of the scene, which is
        important, as it will be called after *every* frame.
        """
        self.__class__.count.fset( self, self.count + 1, notify=0)
        self.__class__.totalTime.fset( self, self.totalTime + duration, notify=0)
        self.__class__.lastTime.fset( self, duration, notify=0)
        r = self._recent
        if r is None:
            r = self._recent = []
        r.append( duration )
        if len(r) > self._RECENT_WINDOW:
            del r[: -self._RECENT_WINDOW]
        return duration

    def recentFps( self ):
        """Median frame rate over the recent window (ignores load/compile spikes)."""
        r = self._recent
        if r:
            ordered = sorted( r )
            median = ordered[len(ordered) // 2]
            if median > 0:
                return round( 1.0 / median, 4 )
        return self.summary()[1]

    def summary( self ):
        """Give a summary of framerates

        returns (count, average fps, last frame-time)

        ``average fps`` is the *cumulative* lifetime rate; for a live display use
        :meth:`recentFps`, which is windowed and outlier-resistant.
        """
        if self.count:
            reallySmall = 0.00000000001
            return (
                self.count,
                round(float( self.count)/(self.totalTime or reallySmall), 4),
                self.lastTime
            )
        return (0,0,0)
