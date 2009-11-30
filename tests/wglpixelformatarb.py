from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL import WGL

names = [
    'WGL_ACCELERATION_ARB',
    'WGL_ACCUM_ALPHA_BITS_ARB',
    'WGL_ACCUM_BITS_ARB',
    'WGL_ACCUM_BLUE_BITS_ARB',
    'WGL_ACCUM_GREEN_BITS_ARB',
    'WGL_ACCUM_RED_BITS_ARB',
    'WGL_ALPHA_BITS_ARB',
    'WGL_ALPHA_SHIFT_ARB',
    'WGL_AUX_BUFFERS_ARB',
    'WGL_BLUE_BITS_ARB',
    'WGL_BLUE_SHIFT_ARB',
    'WGL_COLOR_BITS_ARB',
    'WGL_DEPTH_BITS_ARB',
    'WGL_DOUBLE_BUFFER_ARB',
    'WGL_DRAW_TO_BITMAP_ARB',
    'WGL_DRAW_TO_WINDOW_ARB',
    'WGL_GREEN_BITS_ARB',
    'WGL_GREEN_SHIFT_ARB',
    'WGL_NEED_PALETTE_ARB',
    'WGL_NEED_SYSTEM_PALETTE_ARB',
    'WGL_NUMBER_OVERLAYS_ARB',
    'WGL_NUMBER_PIXEL_FORMATS_ARB',
    'WGL_NUMBER_UNDERLAYS_ARB',
    'WGL_PIXEL_TYPE_ARB',
    'WGL_RED_BITS_ARB',
    'WGL_RED_SHIFT_ARB',
    'WGL_SHARE_ACCUM_ARB',
    'WGL_SHARE_DEPTH_ARB',
    'WGL_SHARE_STENCIL_ARB',
    'WGL_STENCIL_BITS_ARB',
    'WGL_STEREO_ARB',
    'WGL_SUPPORT_GDI_ARB',
    'WGL_SUPPORT_OPENGL_ARB',
    'WGL_SWAP_LAYER_BUFFERS_ARB',
    'WGL_SWAP_METHOD_ARB',
    'WGL_TRANSPARENT_ALPHA_VALUE_ARB',
    'WGL_TRANSPARENT_ARB',
    'WGL_TRANSPARENT_BLUE_VALUE_ARB',
    'WGL_TRANSPARENT_GREEN_VALUE_ARB',
    'WGL_TRANSPARENT_INDEX_VALUE_ARB',
    'WGL_TRANSPARENT_RED_VALUE_ARB',
]
chooseNames = [
    'WGL_NO_ACCELERATION_ARB',
    'WGL_GENERIC_ACCELERATION_ARB',
    'WGL_FULL_ACCELERATION_ARB',
    'WGL_SWAP_EXCHANGE_ARB',
    'WGL_SWAP_COPY_ARB',
    'WGL_SWAP_UNDEFINED_ARB',
    'WGL_TYPE_RGBA_ARB',
    'WGL_TYPE_COLORINDEX_ARB',
]

class TestContext( BaseContext ):
    def OnInit( self ):
        module = self.extensions.initExtension( "WGL.ARB.pixel_format" )
        if module:
            self.TestMethod( module.wglGetPixelFormatAttribivARB )
            self.TestMethod( module.wglGetPixelFormatAttribfvARB )
    def TestMethod( self, method ):
        print 'Starting method', method
        module = self.extensions.initExtension( "WGL.ARB.pixel_format" )
        hdc = WGL.wglGetCurrentDC()
        items = [(name,getattr( module, name)) for name in names ]
        failures = []
        for item in items:
            try:
                result = method(
                    hdc,
                    WGL.GetPixelFormat(hdc),
                    0,
                    [item[1],],
                )
            except WindowsError, err:
                failures.append((item,err))
            else:
                print '%20s\t%r'%( item[0], result)
        if failures:
            print 'FAILURES'
            for ((name,value),err) in failures:
                print name, value, '->', err

        items = [ getattr(module,name) for name in names ]
        try:
            result = method(
                hdc,
                WGL.GetPixelFormat(hdc),
                0,
                items,
            )
        except WindowsError, err:
            print method, 'failed on getting full set'
        else:
            print method, result
        


if __name__ == "__main__":
    TestContext.ContextMainLoop()