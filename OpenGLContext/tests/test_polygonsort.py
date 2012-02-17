from OpenGLContext.arrays import *
from OpenGLContext.scenegraph.polygonsort import *
from OpenGLContext.move import viewplatform
from OpenGL.GLU import gluProject
import unittest

class TestPolygonSort( unittest.TestCase ):
    """Tests for generic atlas algorithms"""
    def setUp( self ):
        self.vp = viewplatform.ViewPlatform()
        self.vp.setPosition( (0,0,10) )
        self.pMatrix = self.vp.viewMatrix().astype('d')
        self.mvMatrix = self.vp.modelMatrix().astype('d')
        self.viewPort = array([0,0,300,300],'f')
    def test_distances( self ):
        """Test distance calculation function
        
        Originally was using gluProject, we check to be sure 
        that we return the same value as gluProject used to 
        produce...
        """
        glu = gluProject( 
            0,0,0, 
            self.mvMatrix, self.pMatrix, 
            self.viewPort.astype('i') 
        )
        expected = glu[2]
        d = distances(
            array([[0,0,0,1]],'f'),
            self.mvMatrix,
            self.pMatrix,
            self.viewPort,
        )
        assert allclose( d[0], expected), (d,expected)
    def test_project( self ):
        """Test projection function"""
        #glu = gluProject( 0,0,0, self.mvMatrix, self.pMatrix, self.viewPort )
        expected = [150.0, 150.0, 0.97000581]
        d = project(
            array([[0,0,0,1]],'f'),
            self.mvMatrix,
            self.pMatrix,
            self.viewPort,
        )
        assert allclose( d[0], expected), (d,expected)
