"""Compile/link every reviewed PBR/IBL/shadow shader in a real GL context.

Run as a subprocess by tests/unit/test_shader_includes.py so a driver-level
compile failure (a broken #include splice, a bad uniform, an over-budget sampler
set) is caught the same way the shipping passes would hit it.  The context is
:class:`OpenGLContext.eglcontext.EGLContext`, the engine's offscreen backend, so
this needs no display and picks its EGL device by the same rules a shipped
application would.

Exit codes: 0 = all programs compiled/linked, 77 = no GL context (skip),
1 = at least one program failed (details on stdout).
"""
import os
import sys

os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

SKIP = 77


def _make_context():
    """The engine's offscreen context, or None where EGL cannot provide one.

    Every way of not having a context ends here.  The exit codes say
    ``0 = compiled, 77 = no GL context, 1 = a program failed``, so a machine
    whose EGL is absent, whose driver lacks the device extensions, or whose
    display cannot be initialised has to reach 77: reporting any of those as 1
    says a shader does not compile, which is a different and untrue claim.
    """
    try:
        from OpenGLContext.eglcontext import EGLContext, EGLContextError
    except Exception as err:
        print("EGL context unavailable:", err)
        return None
    try:
        context = EGLContext(size=(64, 64))
    except EGLContextError as err:
        print("EGL context creation failed:", err)
        return None
    except Exception as err:
        print("no EGL context available:", err)
        return None
    context.setCurrent()
    return context


def main():
    context = _make_context()
    if context is None:
        print("no headless GL context available")
        return SKIP
    try:
        return _check(context)
    finally:
        # However the checks ended, including a failure part-way through them.
        context.unsetCurrent()
        context.close()


def _check(context):
    """Compile and link every reviewed program, and report what failed."""
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
