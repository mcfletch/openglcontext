from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext import frustum, utilities
from OpenGLContext.arrays import *
from OpenGL.GL import *
import traceback

def testPN2P():
    """Tests that utilities functions operate as expected"""
    for point, normal, expected in [
        ((0,0,0), (0,1,0), (0,1,0,0)),
        ((0,0,0), (0,-2,0), (0,-1,0,0)),
        ((0,0,0), (-1,0,0), (-1,0,0,0)),
        ((0,1,0), (-1,0,0), (-1,0,0,0)),
        ((0,-1,0), (-1,0,0), (-1,0,0,0)),
        ((0,-2,-1), (-100,0,0), (-1,0,0,0)),
        ((0,-2,1), (-8,0,0), (-1,0,0,0)),
    ]:
        a,b,c,d = utilities.pointNormal2Plane( point, normal )
        assert (a,b,c,d) == expected, """Point=%s,normal=%s,expected=%s, got %s"""%(
            point, normal, expected, (a,b,c,d),
        )
        # next check is dependent on all points going through origin
        p,n = utilities.plane2PointNormal( (a,b,c,d) )
        x,y,z = utilities.normalise( normal )
        assert allclose( (p,n), ((0,0,0), (x,y,z))), """Point=%s,normal=%s,got %s"""%(
            point, normal, (p,n),
        )


def testExclusion():
    """Test that bounding volumes are properly excluded"""
    f = frustum.Frustum( planes = [
        utilities.pointNormal2Plane( (0,0,0), (-1,0,0) ), # through origin, facing left
    ])
    v = boundingvolume.AABoundingBox(
        center = (-3,0,0),
        size = (1,1,1),
    )
    assert v.visible( f, identity(4,'d'))
    v = boundingvolume.AABoundingBox(
        center = (3,0,0),
        size = (1,1,1),
    )
    assert not v.visible( f, identity(4,'d'))
    # test right at the border of the box...
    v = boundingvolume.AABoundingBox(
        center = (.5,0,0),
        size = (1,1,1),
    )
    assert v.visible( f, identity(4,'d'))


if __name__ == '__main__':
    testPN2P()
    testExclusion()
    # now test the stuff that needs a run-time context...
    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    class TestContext( BaseContext ):
        currentImage = 0
        currentSize = 0
        def Viewpoint( self, mode = None ):
            glMatrixMode(GL_PROJECTION);
            # load the identity matrix (reset the view)
            # calculate a 3D perspective view
            print '___________________________'
            from OpenGL.GL import glFrustum
            for near in (.2,1.,3.,4.,5.,19.):
                print 'near', near
                for far in arange(20.0,2**31,1000):
                    try:
                        glLoadIdentity()
                        glFrustum( -20,20, -20,20, near, far )
                        f = frustum.Frustum.fromViewingMatrix()
                        farCurrent,nearCurrent = f.planes[-2:]
##						nearCurrent,farCurrent = round(nearCurrent,5),round(farCurrent,5)
                        farCurrent = round(farCurrent[-1],4)
                        nearCurrent = round(nearCurrent[-1],4)
                        deltaFar = abs(farCurrent-far)
                        deltaNear = abs( nearCurrent+near)
                        assert deltaFar < abs(far/100), "Far was %s, should have been ~ %s, delta was %s"%(farCurrent,far, deltaFar)
                        assert deltaNear < abs(near/100), "Near was %s, should have been ~ %s, delta was %s"%(nearCurrent,near,deltaNear)
                    except:
                        traceback.print_exc()
                        print '  max far reached', far
                        try:
                            print '  frustum planes', f.planes
                        except:
                            pass
                        break
            glMatrixMode(GL_MODELVIEW);
    TestContext.ContextMainLoop()
    