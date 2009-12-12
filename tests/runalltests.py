#! /usr/bin/env python
"""Script to run the "standard" set of OpenGLContext scripts (in this directory)"""
import OpenGLContext,os,sys,subprocess,datetime, webbrowser
from OpenGLContext import testingcontext
PYTHON = sys.executable
TEST_RUNNER = os.path.join( os.path.dirname( OpenGLContext.__file__ ), 'bin','gltest.py' )
SUCCESS_RETURN_CODE = 0

def runTest( name ):
    """Execute a single test using gltest.py"""
    full_name = os.path.abspath( name )
    returnCode = subprocess.call(
        [ PYTHON, TEST_RUNNER, full_name ],
        shell = False,
        cwd = os.path.dirname( full_name ),
    )
    return returnCode

scripts = """addnodes.py
arbocclusionquery.py
arbpointparameters.py
arbwindowpos.py
ativertexarrayobject.py
backgroundobject.py
boxobject.py
boxtextured.py
coneobject.py
cubeback_rot.py
cubebackgroundobject.py
cylinderobject.py
dek_surf.py
dek_texturesurf.py
feedback_mode.py
gearobject.py
getteximage.py
glarrayelement.py
gldrawarrays.py
gldrawarrays_string.py
gldrawelements.py
gldrawelements_list.py
gldrawelements_string.py
gldrawpixels.py
gldrawpixelssynth.py
glelathe.py
glget_with_fonts.py
glhistogram.py
glinterleavedarrays.py
glu_tess.py
glu_tess2.py
glut_bitmap_font.py
glut_font.py
glut_fullscreen.py
glutbitmapcharacter.py
glutmousewheel.py
glvertex.py
heightmap.py
indexedfaceset_lit_npf.py
indexedfaceset_lit_npv.py
indexedfacesetobject.py
indexedlinesetobject.py
lightobject.py
materialobject.py
molehill.py
mouseover.py
multitexture_1.py
nehe1.py
nehe2.py
nehe3.py
nehe4.py
nehe5.py
nehe6.py
nehe6_convolve.py
nehe6_multi.py
nehe6_timer.py
nehe7.py
nehe8.py
node_modify.py
nurbsobject.py
particles_simple.py
pbodemo.py
point_and_click.py
pointsetobject.py
polygonal_text.py
redbook_alpha.py
redbook_alpha3D.py
redbook_surface.py
redbook_surface_cb.py
redbook_trim.py
selectrendermode.py
selectrendermode_threads.py
shader_1.py
shader_2.py
shader_2_c_void_p.py
shader_3.py
shader_4.py
shader_5.py
shader_6.py
shader_7.py
shader_8.py
shader_9.py
shader_10.py
shader_11.py
shader_12.py
shader_sphere.py
shader_spike.py
shadergeometry.py
shaderobjects.py
shaders.py
shadow_1.py
shadow_2.py
simplebox.py
simplerotate.py
solid_font.py
spherebackgroundobject.py
spincube.py
teapotobject.py
textureobject.py
timesensorobject.py
transparentsorted.py""".split()

examine_file = """<html><head>
    <title>Test Results</title>
    <style type="text/css">
        body {
            color: black;
            background-color: white;
        }
        .failed {
            color: red;
            font-weight: bold;
        }
        .skipped {
            background-color: #c0c0c0;
        }
        .success {
            color: green;
        }
    </style>
</head><body>
<div class="metadata">%(date)s</div>
<table class="test-results"><thead><tr><th>Script</th><th>Reference</th><th>Current</th></tr></thead>
<tbody>
    %(rows)s
</tbody>
</table>
</body>
</html>"""
row_template = """<tr class="%(success)s">
    <th>%(script)s</th>
    <td><img src="%(script)s-ref.png" /></td>
    <td><img src="%(script)s-new.png" /></td>
</tr>"""


def main(scripts):
    date = datetime.datetime.now().isoformat()
    failures = []
    skips = []
    rows = []
    for script in scripts:
        result = runTest( script )
        script = os.path.splitext(os.path.basename( script ))[0]
        if result:
            if result == testingcontext.REQUIRED_EXTENSION_MISSING:
                success = 'skipped'
                skips.append( script )
            else:
                success = 'failed'
                failures.append( script )
        else:
            success = 'succeeded'
        rows.append( row_template%locals())
    rows = "\n".join( rows )
    open( os.path.join('test-results','index.html'), 'w').write( examine_file %locals())
    if failures or skips:
        if failures:
            sys.stderr.write( 'FAILED:\n' )
            sys.stderr.write( "\n".join( failures ))
            sys.stderr.write( '\n' )
        if skips:
            sys.stderr.write( 'Skipped:\n' )
            sys.stderr.write( "\n".join( skips ))
            sys.stderr.write( '\n' )
    else:
        sys.stderr.write( 'Success' )
        sys.stderr.write( '\n' )
    webbrowser.open_new_tab( os.path.join('test-results','index.html' ))


if __name__ == "__main__":
    if sys.argv[1:]:
        main( sys.argv[1:] )
    else:
        main(scripts)
