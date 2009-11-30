from OpenGLContext import frustum
from OpenGLContext.arrays import *

fail_10e5 = 0
fail_10e4 = 0
fail_10e3 = 0
total = 0

def test( projection, modelview, multiplied, planes ):
    """Test for proper results from the data-set"""
    global fail_10e3
    global fail_10e4
    global fail_10e5
    global total
    total += 1
    projection = reshape( asarray( projection, 'd'), (4,4))
    modelview = reshape( asarray( modelview, 'd'), (4,4))
    temp = frustum.Frustum.fromViewingMatrix( frustum.viewingMatrix(
        projection, modelview,
    ))
    if not allclose( temp.planes, planes, 1.0e-5):
        fail_10e5 += 1
        if not allclose( temp.planes, planes, 1.0e-4):
            fail_10e4 += 1
            if not allclose( temp.planes, planes, 1.0e-3):
                fail_10e3 += 1
                print '\nFAIL:', projection, modelview, planes
            else:
                print '/',
        else:
            print ',',
    else:
        print '.',

def printstats():
    print 'Failures:'
    print fail_10e5, fail_10e4, fail_10e3
    print 'Total:'
    print total