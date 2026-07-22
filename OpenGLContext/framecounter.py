"""Simple node holding Frame-counting values"""
from vrml import node, field
from OpenGL.GL import *

# Prefer the texture-atlas (shader) font for on-screen display: it renders in
# both core and compatibility profiles and needs no GLUT display. The GLUT
# bitmap font is only safe on a GLUT context (its routines segfault otherwise),
# so it is used solely as a fallback and only when the context provides GLUT.
try:
    from OpenGLContext.scenegraph.text import shaderfont as _shaderfont
    if not _shaderfont.is_available():
        _shaderfont = None
except ImportError:
    _shaderfont = None
try:
    from OpenGLContext.scenegraph.text import glutfont as _glutfont
except ImportError:
    _glutfont = None


class FrameCounter( node.Node ):
    """Simple node holding Frame-counting values

    This node is used to hold information about the amount
    of time required to render frames for the context.
    """
    PROTO = 'FrameCounter'
    count = field.newField( 'count', 'SFInt32', 1, 0)
    totalTime = field.newField( 'totalTime', 'SFFloat', 1, 0.0)
    lastTime = field.newField( 'lastTime', 'SFFloat', 1, 0.0)
    display = field.newField( 'display', 'SFBool', 1, True)
    _font = None
    # Window of recent frame durations for the displayed rate. A *cumulative*
    # average (count/totalTime) bakes in one-off stalls forever -- a synchronous
    # model load (network + decode) or the first-frame shader compile lands in a
    # timed frame and permanently drags the number down. A windowed median
    # reflects current rendering speed and shrugs off those outliers.
    _recent = None
    _RECENT_WINDOW = 90

    def font( self, context ):
        if self._font is None:
            from OpenGLContext.scenegraph.basenodes import FontStyle
            style = FontStyle(size=1.0)
            if _shaderfont is not None:
                self._font = _shaderfont.ShaderBitmapFont(style, size=16)
            elif _glutfont is not None and getattr(context, 'providesGLUT', False):
                self._font = _glutfont.GLUTBitmapFont(style)
        return self._font

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
    
    def Render( self, context ):
        """Render the frame-counter to the screen"""
        font = self.font(context)
        if font is None:
            return  # No font available
        margin = 30
        tx,ty = context.getViewPort()
        if tx and ty:
            glPushAttrib( GL_ALL_ATTRIB_BITS )
            try:
                glDisable( GL_DEPTH_TEST )
                glDisable( GL_LIGHTING )
                glMatrixMode( GL_PROJECTION )
                glLoadIdentity()
                glOrtho( 0, tx, 0, ty, -1, 1 )
                glMatrixMode( GL_MODELVIEW )
                glLoadIdentity()
                glColor4f( 1.0,1.0,1.0, 1.0)
                try:
                    glTranslated( 10,margin*2,0.0 )
                    count,_avg,last = self.summary()
                    avg = self.recentFps()
                    last *= 1000
                    font.render(
                        'fps avg:%0.1f\ncurr ms: %0.0f'%(avg,last)
                    )
                finally:
                    glEnable( GL_DEPTH_TEST )
                    glLoadIdentity()
            finally:
                glPopAttrib()