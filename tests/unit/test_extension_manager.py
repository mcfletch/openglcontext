"""The extension lists a context's ExtensionManager reports."""
import subprocess
import sys


def test_with_no_glu_library_there_are_no_glu_extensions():
    script = '\n'.join([
        'from OpenGL import platform',
        'platform.PLATFORM.GLU = None',
        'from OpenGLContext.extensionmanager import ExtensionManager',
        'print(ExtensionManager().listGLU())',
    ])
    done = subprocess.run([sys.executable, '-c', script],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip() == '[]'
