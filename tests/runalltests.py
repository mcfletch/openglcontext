#! /usr/bin/env python
"""Script to run the "standard" set of OpenGLContext scripts (in this directory)"""
import os,sys,subprocess,datetime, webbrowser, glob
from OpenGLContext import testingcontext
PYTHON = sys.executable
TEST_RUNNER = 'oglc-test'
SUCCESS_RETURN_CODE = 0
HERE = os.path.dirname(__file__)

def runTest( name ):
    """Execute a single test using gltest.py"""
    full_name = os.path.abspath( name )
    returnCode = subprocess.call(
        [ TEST_RUNNER, full_name ],
        shell = False,
        cwd = os.path.dirname( full_name ),
    )
    return returnCode

STOP_SET = set([
    'runalltests.py',
    'frust_test_module.py',
    'numpyfields.py',
    'wx_multiple_contexts.py',
    'wx_with_controls.py',
    'wx_font.py',
    'nehe6_convolve.py', # modern drivers don't include the functionality...
    'profile_view.py',
    'pygame_font.py',
    'pygame_textureatlas.py',
    'savepostscript.py', # removed functionality
])
if sys.platform != 'win32':
    STOP_SET.add('wgl_font.py')
    STOP_SET.add('wgl_bitmap_font.py')
    STOP_SET.add('wglpixelformatarb.py')
    STOP_SET.add('glprint.py')

def get_scripts():
    scripts = sorted([
        x for x in glob.glob( os.path.join( HERE, '*.py' ))
        if (
            not os.path.basename(x).startswith( '_' )
            and 
            not os.path.basename(x) in STOP_SET
        )
    ])
    return scripts

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
        main(get_scripts())
