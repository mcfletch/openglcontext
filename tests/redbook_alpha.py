#! /usr/bin/env python
"""Demonstration of effect of rendering order on blended polys

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
 *  alpha.c
 *  This program draws several overlapping filled polygons
 *  to demonstrate the effect order has on alpha blending results.
 *  Use the 't' key to toggle the order of drawing polygons.
 */
"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import context
from OpenGL.GL import *
from OpenGLContext.arrays import array
import string


class TestContext( BaseContext ):
    """Red Book alpha.c
    Demonstrates the effects of alpha blending
    Copyright (c) 1993-1999, Silicon Graphics, Inc. ALL RIGHTS RESERVED 
    """
    initialPosition = (0,0,2)
    def OnInit( self ):
        self.leftFirst = 1
        self.addEventHandler( 'keypress', name='f', function = self.OnSwitch )
        print 'Press "f" to switch polygon order'
    def OnSwitch( self, event ):
        """Switch order of triangles"""
        self.leftFirst = not self.leftFirst
        self.triggerRedraw(1)
    def SetupDisplay( self, mode = None ):
        """Setup display for display for the given mode"""
        ### NOTE:
        ### required because the context enables by default!
        glDisable(GL_DEPTH_TEST);
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glEnable (GL_BLEND);
        glDisable( GL_LIGHTING )
        glBlendFunc (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glShadeModel (GL_FLAT);

        if self.leftFirst:
            self.left();
            self.right();
        else:
            self.right();
            self.left();


    def left( self ):
        """draw yellow triangle on LHS of screen"""
        glBegin (GL_TRIANGLES);
        glColor4f(1.0, 1.0, 0.0, 0.5);
        glVertex3f(0.1, 0.9, 0.0);
        glVertex3f(0.1, 0.1, 0.0);
        glVertex3f(0.7, 0.5, 0.0);
        glEnd();
    def right( self ):
        """draw cyan triangle on RHS of screen"""
        glBegin (GL_TRIANGLES);
        glColor4f(0.0, 1.0, 1.0, 0.5);
        glVertex3f(0.9, 0.9, 0.0); 
        glVertex3f(0.3, 0.5, 0.0); 
        glVertex3f(0.9, 0.1, 0.0); 
        glEnd();


if __name__ == "__main__":
    TestContext.ContextMainLoop()

