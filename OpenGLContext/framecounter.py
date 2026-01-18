"""Simple node holding Frame-counting values"""
from vrml import node, field
from OpenGL.GL import *

# Try to get a working font - prefer glutfont, fall back to shaderfont
_font_module = None
try:
    from OpenGLContext.scenegraph.text import glutfont
    _font_module = glutfont
except ImportError:
    try:
        from OpenGLContext.scenegraph.text import shaderfont
        if shaderfont.is_available():
            _font_module = shaderfont
    except ImportError:
        pass


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

    def font( self, context ):
        if not self._font and _font_module is not None:
            from OpenGLContext.scenegraph.basenodes import FontStyle
            if hasattr(_font_module, 'GLUTBitmapFont'):
                self._font = _font_module.GLUTBitmapFont(FontStyle(size=1.0))
            elif hasattr(_font_module, 'ShaderBitmapFont'):
                self._font = _font_module.ShaderBitmapFont(FontStyle(size=1.0), size=16)
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
        return duration
    def summary( self ):
        """Give a summary of framerates

        returns (count, average fps, last frame-time)
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
                    count,avg,last = self.summary()
                    last *= 1000
                    font.render(
                        'fps avg:%0.1f\ncurr ms: %0.0f'%(avg,last)
                    )
                finally:
                    glEnable( GL_DEPTH_TEST )
                    glLoadIdentity()
            finally:
                glPopAttrib()