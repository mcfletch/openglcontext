from OpenGLContext.arrays import *
from OpenGLContext.utilities import *
from OpenGLContext.vectorutilities import *
from OpenGLContext.move import viewplatform
import unittest

class TestViewPlatform( unittest.TestCase ):
    """Tests for generic atlas algorithms"""
    def setUp( self ):
        self.vp = viewplatform.ViewPlatform()
        self.vp.setOrientation( (0,1,0,pi/3))
    def test_mv_matrix( self ):
        mv = self.vp.modelMatrix( )
        inv = self.vp.modelMatrix( inverse=True )
        test = array( [20,18,4,1],'f')
        projected = dot( mv, test )
        unprojected = dot( inv, projected )
        assert allclose( unprojected, test ), (test,unprojected)
    def test_proj_matrix( self ):
        mv = self.vp.viewMatrix( )
        inv = self.vp.viewMatrix( inverse=True )
        test = array( [20,18,4,1],'f')
        projected = dot( mv, test )
        unprojected = dot( inv, projected )
        assert allclose( unprojected, test ), (test,unprojected)
    def test_combined_matrix( self ):
        mv = self.vp.matrix( )
        inv = self.vp.matrix( inverse=True )
        test = array( [20,18,4,1],'f')
        projected = dot( mv, test )
        unprojected = dot( inv, projected )
        # there's some inaccuracies, as we are using 'f' throughout...
        assert allclose( unprojected, test, 0.0001 ), (test,unprojected)
    
