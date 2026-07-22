"""Compile/link every reviewed PBR/IBL/shadow shader in a real GL context.

Run as a subprocess by tests/test_shader_includes.py so a driver-level compile
failure (a broken #include splice, a bad uniform, an over-budget sampler set)
is caught the same way the shipping passes would hit it. Creates a surfaceless
EGL context on an EGL device (headless / CI friendly; see the project memory
"headless-gl-validation").

Exit codes: 0 = all programs compiled/linked, 77 = no GL context (skip),
1 = at least one program failed (details on stdout).
"""
import os
import sys
import ctypes

os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

SKIP = 77


def _make_context():
    """Surfaceless EGL context on the first EGL device, or None if unavailable."""
    try:
        from OpenGL.EGL import (
            eglInitialize, eglChooseConfig, eglBindAPI, eglCreateContext,
            eglMakeCurrent, EGL_OPENGL_API, EGL_NO_SURFACE, EGL_NO_CONTEXT,
            EGL_PBUFFER_BIT, EGL_SURFACE_TYPE, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
            EGL_NONE, EGLConfig, EGLint,
        )
        from OpenGL.EGL.EXT.device_base import eglQueryDevicesEXT, EGLDeviceEXT
        from OpenGL.EGL.EXT.platform_device import EGL_PLATFORM_DEVICE_EXT
        from OpenGL.EGL.EXT.platform_base import eglGetPlatformDisplayEXT
    except Exception as err:  # EGL not present in this PyOpenGL build
        print("EGL import failed:", err)
        return None
    try:
        devices = (EGLDeviceEXT * 8)()
        num = EGLint()
        eglQueryDevicesEXT(8, devices, ctypes.byref(num))
        for i in range(num.value):
            dpy = eglGetPlatformDisplayEXT(EGL_PLATFORM_DEVICE_EXT, devices[i], None)
            if not dpy:
                continue
            if not eglInitialize(dpy, None, None):
                continue
            attrs = (EGLint * 7)(
                EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
                EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
                EGL_NONE, 0, 0,
            )
            cfg = (EGLConfig * 1)()
            n = EGLint()
            eglChooseConfig(dpy, attrs, cfg, 1, ctypes.byref(n))
            if not n.value:
                continue
            eglBindAPI(EGL_OPENGL_API)
            ctx = eglCreateContext(dpy, cfg[0], EGL_NO_CONTEXT, None)
            if not ctx:
                continue
            if eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx):
                return dpy
    except Exception as err:
        print("EGL context creation failed:", err)
    return None


def main():
    if _make_context() is None:
        print("no headless GL context available")
        return SKIP

    from OpenGL.GL import shaders as S
    from OpenGL.GL import GL_VERTEX_SHADER, GL_FRAGMENT_SHADER
    from OpenGLContext.passes import shaderpass as SP
    from OpenGLContext.passes.pbrpass import pbr_feature_defines

    fails = []

    def compile_prog(name, vert_src, frag_src):
        try:
            v = S.compileShader(vert_src, GL_VERTEX_SHADER)
            f = S.compileShader(frag_src, GL_FRAGMENT_SHADER)
            S.compileProgram(v, f, validate=False)
            print("PASS", name)
        except Exception as err:
            print("FAIL", name, "\n", str(err)[:1200])
            fails.append(name)

    # Lit shaders across every shadow permutation the driver tiers select.
    for lit, vert in (('pbr.frag', 'pbr.vert'),
                      ('vrml97_lighting.frag', 'vrml97_lighting.vert')):
        vsrc = SP.preprocess_shader(vert)
        for cube in (False, True):
            for n in (1, 2, 3, 4):
                fsrc = SP.load_fragment_source(lit, n, cube)
                compile_prog("%s[cube=%s,n=%d]" % (lit, cube, n), vsrc, fsrc)

    # Constrained per-platform build with every optional lobe compiled out.
    feat = SP.shadow_defines(4, False) + pbr_feature_defines(enabled=[])
    compile_prog("pbr.frag[features-off]", SP.preprocess_shader('pbr.vert'),
                 SP.preprocess_shader('pbr.frag', feat))

    # IBL precompute programs.
    ivert = SP.preprocess_shader('ibl_fullscreen.vert')
    for frag in ('ibl_env.frag', 'ibl_irradiance.frag',
                 'ibl_prefilter.frag', 'ibl_brdf.frag'):
        compile_prog(frag, ivert, SP.preprocess_shader(frag))

    compile_prog("shadow_depth", SP.preprocess_shader('shadow_depth.vert'),
                 SP.preprocess_shader('shadow_depth.frag'))

    # The MAX_SHADOW_LIGHTS>4 tripwire MUST refuse to compile, not silently drop
    # shadows for slots >= 4.
    try:
        S.compileShader(SP.preprocess_shader('pbr.frag',
                        ['#define MAX_SHADOW_LIGHTS 5']), GL_FRAGMENT_SHADER)
        print("FAIL tripwire: MAX_SHADOW_LIGHTS=5 compiled")
        fails.append("tripwire")
    except Exception as err:
        if 'unrolls 4 shadow slots' in str(err):
            print("PASS tripwire (MAX_SHADOW_LIGHTS=5 rejected)")
        else:
            print("FAIL tripwire: wrong error\n", str(err)[:400])
            fails.append("tripwire")

    if fails:
        print("\nFAILED:", ", ".join(fails))
        return 1
    print("\nALL PROGRAMS OK")
    return 0


if __name__ == '__main__':
    sys.exit(main())
