#! /usr/bin/env python
"""Demonstration of effect of blending geometry in 3D

/*
 * Copyright (c) 1993-1999, Silicon Graphics, Inc.
 * ALL RIGHTS RESERVED 
 * Permission to use, copy, modify, and distribute this software for 
 * any purpose and without fee is hereby granted, provided that the above
 * copyright notice appear in all copies and that both the copyright notice
 * and this permission notice appear in supporting documentation, and that 
 * the name of Silicon Graphics, Inc. not be used in advertising
 * or publicity pertaining to distribution of the software without specific,
 * written prior permission. 
 *
 * THE MATERIAL EMBODIED ON THIS SOFTWARE IS PROVIDED TO YOU "AS-IS"
 * AND WITHOUT WARRANTY OF ANY KIND, EXPRESS, IMPLIED OR OTHERWISE,
 * INCLUDING WITHOUT LIMITATION, ANY WARRANTY OF MERCHANTABILITY OR
 * FITNESS FOR A PARTICULAR PURPOSE.  IN NO EVENT SHALL SILICON
 * GRAPHICS, INC.  BE LIABLE TO YOU OR ANYONE ELSE FOR ANY DIRECT,
 * SPECIAL, INCIDENTAL, INDIRECT OR CONSEQUENTIAL DAMAGES OF ANY
 * KIND, OR ANY DAMAGES WHATSOEVER, INCLUDING WITHOUT LIMITATION,
 * LOSS OF PROFIT, LOSS OF USE, SAVINGS OR REVENUE, OR THE CLAIMS OF
 * THIRD PARTIES, WHETHER OR NOT SILICON GRAPHICS, INC.  HAS BEEN
 * ADVISED OF THE POSSIBILITY OF SUCH LOSS, HOWEVER CAUSED AND ON
 * ANY THEORY OF LIABILITY, ARISING OUT OF OR IN CONNECTION WITH THE
 * POSSESSION, USE OR PERFORMANCE OF THIS SOFTWARE.
 * 
 * US Government Users Restricted Rights 
 * Use, duplication, or disclosure by the Government is subject to
 * restrictions set forth in FAR 52.227.19(c)(2) or subparagraph
 * (c)(1)(ii) of the Rights in Technical Data and Computer Software
 * clause at DFARS 252.227-7013 and/or in similar or successor
 * clauses in the FAR or the DOD or NASA FAR Supplement.
 * Unpublished-- rights reserved under the copyright laws of the
 * United States.  Contractor/manufacturer is Silicon Graphics,
 * Inc., 2011 N.  Shoreline Blvd., Mountain View, CA 94039-7311.
 *
 * OpenGL(R) is a registered trademark of Silicon Graphics, Inc.
 */

/*
 *  alpha3D.c
 *  This program demonstrates how to intermix opaque and
 *  alpha blended polygons in the same scene, by using 
 *  glDepthMask.  Press the 'a' key to animate moving the 
 *  transparent object through the opaque object.  Press 
 *  the 'r' key to reset the scene.
 */
"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import context
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
from OpenGLContext.arrays import array
import string, time

class Timer:
    def __init__( self, cycle = 8.0):
        self.startTime = time.time()
        self.cycle = cycle
    def fraction( self ):
        return ((time.time() - self.startTime)% self.cycle)/self.cycle


class TestContext( BaseContext ):
    """Red Book alpha.c
    Demonstrates the effects of alpha blending
    Copyright (c) 1993-1999, Silicon Graphics, Inc. ALL RIGHTS RESERVED 
    """
    initialPosition = (0,0,10)
    def OnInit( self ):
        """Setup running params"""

        glMaterialfv(GL_FRONT, GL_SPECULAR, array((1.0, 1.0, 1.0, 0.15),'f') );
        glMaterialfv(GL_FRONT, GL_SHININESS, array((100.0, ),'f') );

        self.sphereList = glGenLists(1);
        if not self.sphereList:
            raise SystemError("""Unable to generate display list using glGenLists""")
        glNewList(self.sphereList, GL_COMPILE);
        glutSolidSphere (0.4, 16, 16);
        glEndList();

        self.cubeList = glGenLists(1);
        glNewList(self.cubeList, GL_COMPILE);
        glutSolidCube (0.6);
        glEndList();
        self.solidZ = 8.0
        self.solidTimer = Timer( 8.0 )
        self.transparentZ = -8.0
        self.transparentTimer = Timer( 4.0 )
        self.animating = 1
        self.startTime = time.time()

        self.addEventHandler( "keypress", name = 'a', function = self.OnAnimate )
        print 'Press "a" to stop animation\nNote: r key has no effect'

    def Lights( self, mode = None ):
        """Setup global illumination"""
        
        glLightfv(GL_LIGHT0, GL_POSITION, array( (0.5, 0.5, 1.0, 0.0),'f') );
        glEnable(GL_LIGHTING);
        glEnable(GL_LIGHT0);
    def Background( self, mode = 0):
        """Demo's use of GL_ONE assumes that background is black"""
        glClearColor(0,0,0,1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )
    def OnAnimate( self, event):
        self.animating = not self.animating
        
    def updatePositions( self ):
        if self.animating:
            self.solidZ = self.solidTimer.fraction() * 16 - 8.0
            self.transparentZ = -(self.transparentTimer.fraction() * 16 - 8.0)
##			print 'positions', self.solidZ, self.transparentZ
    def OnIdle( self, ):
        if self.animating:
            self.triggerRedraw(1)
            return 1
            
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        self.updatePositions()

        glPushMatrix ();
        glTranslatef (-0.15, -0.15, self.solidZ);
        glMaterialfv(GL_FRONT, GL_EMISSION, array(( 0.0, 0.0, 0.0, 1.0),'f'), );
        glMaterialfv(GL_FRONT, GL_DIFFUSE, array((0.75, 0.75, 0.0, 1.0),'f'), );
        glCallList (self.sphereList);
        glPopMatrix ();

        glPushMatrix ();
        glTranslatef (0.15, 0.15, self.transparentZ);
        glRotatef (15.0, 1.0, 1.0, 0.0);
        glRotatef (30.0, 0.0, 1.0, 0.0);
        glMaterialfv(GL_FRONT, GL_EMISSION,array( ( 0.0, 0.3, 0.3, 0.6),'f') );
        glMaterialfv(GL_FRONT, GL_DIFFUSE,array( ( 0.0, 0.8, 0.8, 0.8),'f') );
        glEnable (GL_BLEND);
        glDepthMask (GL_FALSE);
        glBlendFunc (GL_SRC_ALPHA, GL_ONE); # note assumption that background is black...
        glCallList (self.cubeList);
        glDepthMask (GL_TRUE);
        glDisable (GL_BLEND);
        glPopMatrix ();

if __name__ == "__main__":
    TestContext.ContextMainLoop()
