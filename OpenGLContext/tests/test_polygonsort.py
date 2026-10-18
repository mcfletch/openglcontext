import types
import unittest

from OpenGLContext.arrays import allclose, array
from OpenGLContext.events.mouseevents import projected
from OpenGLContext.scenegraph.polygonsort import *
from OpenGLContext.move import viewplatform

class TestPolygonSort( unittest.TestCase ):
    """Tests for generic atlas algorithms"""
    def setUp( self ) -> None:
        self.vp = viewplatform.ViewPlatform()
        self.vp.setPosition( (0,0,10) )
        self.pMatrix = self.vp.viewMatrix().astype('d')
        self.mvMatrix = self.vp.modelMatrix().astype('d')
        self.viewPort = array([0,0,300,300],'f')
    def test_distances( self ) -> None:
        """The distance is the window depth a single point projects to"""
        view = types.SimpleNamespace(
            modelViewMatrix=self.mvMatrix, projectionMatrix=self.pMatrix,
            viewport=self.viewPort)
        expected = projected(view, (0, 0, 0))[2]
        d = distances(
            array([[0,0,0,1]],'f'),
            self.mvMatrix,
            self.pMatrix,
            self.viewPort,
        )
        assert allclose( d[0], expected), (d,expected)
    def test_project( self ) -> None:
        """Test projection function"""
        expected = [150.0, 150.0, 0.97000581]
        d = project(
            array([[0,0,0,1]],'f'),
            self.mvMatrix,
            self.pMatrix,
            self.viewPort,
        )
        assert allclose( d[0], expected), (d,expected)
