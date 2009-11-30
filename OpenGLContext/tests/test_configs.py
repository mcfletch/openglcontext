from OpenGLContext.contextdefinition import ContextDefinition
import unittest, ConfigParser,os
from OpenGLContext import arrays

sample_ini = os.path.join(
    os.path.dirname( __file__ ),
    'sample.ini'
)

class TestContextDefinition( unittest.TestCase ):
    def test_from_config( self ):
        cfg = ConfigParser.ConfigParser()
        cfg.read( sample_ini )
        cd = ContextDefinition.fromConfig( cfg )
        assert arrays.allclose(cd.size, [600,600] ), cd.size 
        assert cd.title == "Test Context", cd.title 
        assert cd.doubleBuffer == False, cd.doubleBuffer
        assert cd.depthBuffer == 16, cd.depthBuffer
        assert cd.accumulationBuffer == 16
        assert cd.stencilBuffer == 16
        assert cd.rgb == False
        assert cd.alpha == False 
        assert cd.multisampleBuffer == 16
        assert cd.multisampleSamples == 4
        assert cd.stereo == 23