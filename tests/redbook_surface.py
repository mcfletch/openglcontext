#! /usr/bin/env python
"""Draws a NURBS surface with GLU

surface.c
This program draws a NURBS surface in the shape of a 
symmetrical hill.  The 'c' keyboard key allows you to 
toggle the visibility of the control points themselves.  
Note that some of the control points are hidden by the  
surface itself.


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
"""

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGLContext.arrays import *
import string, time, StringIO
from OpenGLContext.scenegraph import shape, indexedfaceset, material, appearance, light, transform

class TestContext( BaseContext ):
    initialPosition = (0,0,5) # set initial camera position, tutorial does the re-positioning
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )

        glClearColor (0.0, 0.0, 0.0, 0.0);
        glMaterialfv(GL_FRONT, GL_DIFFUSE, array([0.7, 0.7, 0.7, 1.0],'f'));
        glMaterialfv(GL_FRONT, GL_SPECULAR, array([1.0, 1.0, 1.0, 1.0],'f'));
        glMaterialfv(GL_FRONT, GL_SHININESS, array([100.0],'f'));

        glEnable(GL_AUTO_NORMAL);
        glEnable(GL_NORMALIZE);

        knots= array ([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0], "f")
        glPushMatrix();
        try:
            glRotatef(330.0, 1.,0.,0.);
            glScalef (0.5, 0.5, 0.5);

            gluBeginSurface(self.theNurb);
            controlPoints = self.controlPoints
            try:
                gluNurbsSurface(
                    self.theNurb,
                    knots, knots,
                    controlPoints,
                    GL_MAP2_VERTEX_3
                );
            finally:
                gluEndSurface(self.theNurb);
        finally:
            glPopMatrix();



    def OnInit( self ):
        self.showPoints = 0
        self.theNurb = gluNewNurbsRenderer();
        self.controlPoints = self.buildControlPoints()
        gluNurbsProperty(self.theNurb, GLU_SAMPLING_TOLERANCE, 25.0);
        gluNurbsProperty(self.theNurb, GLU_DISPLAY_MODE, GLU_FILL);
    def buildControlPoints( self ):
        ctlpoints = zeros( (4,4,3), 'f')
        for u in range( 4 ):
            for v in range( 4):
                ctlpoints[u][v][0] = 2.0*(u - 1.5)
                ctlpoints[u][v][1] = 2.0*(v - 1.5);
                if (u == 1 or u ==2) and (v == 1 or v == 2):
                    ctlpoints[u][v][2] = 3.0;
                else:
                    ctlpoints[u][v][2] = -3.0;
        return ctlpoints



if __name__ == "__main__":
    TestContext.ContextMainLoop()


