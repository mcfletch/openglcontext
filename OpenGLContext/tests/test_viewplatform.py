from typing import Any
import unittest

from OpenGLContext.arrays import allclose, array, dot, pi
from OpenGLContext.move import viewplatform
from OpenGLContext.scenegraph import light

class TestViewPlatform( unittest.TestCase ):
    """Tests for generic atlas algorithms"""
    def setUp( self ) -> None:
        self.vp = viewplatform.ViewPlatform()
        self.vp.setOrientation( (0,1,0,pi/3))
        self.light = light.SpotLight( 
            location = (20,4,3),
            direction = (-8,0,0),
        )
    def _are_inverse( self, forward: Any, inverse: Any ) -> None:
        test = array( [20,18,4,1],'f')
        projected = dot( forward, test )
        unprojected = dot( inverse, projected )
        assert allclose( unprojected, test, 0.0001 ), (test,unprojected)
    
    def test_mv_matrix( self ) -> None:
        mv = self.vp.modelMatrix( )
        inv = self.vp.modelMatrix( inverse=True )
        self._are_inverse( mv, inv )
    def test_proj_matrix( self ) -> None:
        mv = self.vp.viewMatrix( )
        inv = self.vp.viewMatrix( inverse=True )
        self._are_inverse( mv, inv )
    def test_combined_matrix( self ) -> None:
        mv = self.vp.matrix( )
        inv = self.vp.matrix( inverse=True )
        self._are_inverse( mv, inv )
    def test_light_view( self ) -> None:
        mv = self.light.viewMatrix( )
        inv = self.light.viewMatrix( inverse=True )
        self._are_inverse( mv, inv )
        
