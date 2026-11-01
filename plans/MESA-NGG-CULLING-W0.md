# radeonsi: NGG culling draws a back-facing triangle that has a vertex at clip w = 0

A report written for Mesa's issue tracker
(<https://gitlab.freedesktop.org/mesa/mesa/-/issues>). Not filed.

## Environment

- GPU: AMD Radeon 8060S Graphics (gfx1151, RDNA 3.5), kernel amdgpu, DRM 3.64
- Mesa 25.2.8 (Ubuntu package 25.2.8-0ubuntu0.24.04.2), radeonsi, LLVM 20.1.2
- Linux 7.0.0-38-generic, Ubuntu 24.04, Wayland
- Seen through EGL surfaceless (below) and GLFW windows on Wayland alike

## Summary

With `GL_CULL_FACE` enabled, a back-facing triangle with one vertex exactly
on the plane through the eye (clip-space w = 0) is rasterized once
radeonsi's vertex-stage (NGG) culling is active for the shader.
`AMD_DEBUG=nonggc` culls it. llvmpipe culls it. Moving the vertex 0.01 units
off the plane culls it.

## Steps to reproduce

The program below draws a closed cone of 80 triangles, wound CCW from
outside, with the eye at the origin looking down -Z. The cone's axis is Y
and its centre is the eye, so the apex (0, 10, 0) and the base centre
(0, -10, 0) have eye-space z = 0 and clip w = 0. Every triangle uses one of
those two vertices. From inside, every triangle is back-facing, so with
`glCullFace(GL_BACK)` the frame should stay black. It draws ten frames and
prints the green channel of the centre pixel of each.

```sh
cc -o ngg_w0 ngg_w0.c -lEGL -lOpenGL -lm
./ngg_w0            # vertices at w = 0
./ngg_w0 0.01       # the cone moved 0.01 along z: no vertex at w = 0
AMD_DEBUG=nonggc ./ngg_w0
```

```c
/* radeonsi NGG culling: a back-facing triangle with a vertex at clip w == 0 is drawn.
 *
 * Build: cc -o ngg_w0 ngg_w0.c -lEGL -lOpenGL -lm
 * Run:   ./ngg_w0 [z-offset]
 *
 * A closed cone (apex up, CCW from outside) is centred on the eye, so its apex
 * and base centre lie in the eye plane: clip w == 0 for those two vertices.
 * Seen from inside, every triangle is back-facing and GL_CULL_FACE/GL_BACK
 * should leave the frame black. The centre pixel is printed for each frame.
 */
#define GL_GLEXT_PROTOTYPES 1
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/gl.h>
#include <GL/glext.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#define N 40
#define SIZE 96

static const char *vs_src =
    "#version 330 core\n"
    "layout(location = 0) in vec3 position;\n"
    "uniform mat4 mvp;\n"
    "void main() { gl_Position = mvp * vec4(position, 1.0); }\n";
static const char *fs_src =
    "#version 330 core\n"
    "out vec4 colour;\n"
    "void main() { colour = vec4(0.0, 1.0, 0.0, 1.0); }\n";

static GLuint shader(GLenum kind, const char *src)
{
    GLuint s = glCreateShader(kind);
    GLint ok = 0;
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { fprintf(stderr, "compile failed\n"); exit(2); }
    return s;
}

int main(int argc, char **argv)
{
    float dz = argc > 1 ? (float)atof(argv[1]) : 0.0f;
    PFNEGLGETPLATFORMDISPLAYEXTPROC get_display =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    EGLDisplay dpy = get_display(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, NULL);
    EGLint major, minor;
    const EGLint context_attribs[] = {
        EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 3,
        EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL_NONE};
    if (!eglInitialize(dpy, &major, &minor)) { fprintf(stderr, "no EGL\n"); return 2; }
    eglBindAPI(EGL_OPENGL_API);
    /* EGL_KHR_no_config_context: the frame is drawn to a framebuffer object. */
    EGLContext ctx = eglCreateContext(dpy, EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT, context_attribs);
    if (ctx == EGL_NO_CONTEXT) { fprintf(stderr, "no context: 0x%x\n", eglGetError()); return 2; }
    if (!eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx)) {
        fprintf(stderr, "not current: 0x%x\n", eglGetError()); return 2;
    }
    const GLubyte *renderer = glGetString(GL_RENDERER);
    if (!renderer) { fprintf(stderr, "no GL_RENDERER\n"); return 2; }
    printf("%s\n", (const char *)renderer);

    GLuint fbo, rbo[2];
    glGenFramebuffers(1, &fbo);
    glGenRenderbuffers(2, rbo);
    glBindRenderbuffer(GL_RENDERBUFFER, rbo[0]);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, SIZE, SIZE);
    glBindRenderbuffer(GL_RENDERBUFFER, rbo[1]);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, SIZE, SIZE);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, rbo[0]);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, rbo[1]);
    glViewport(0, 0, SIZE, SIZE);

    /* Cone: apex (0, 10, 0), base centre (0, -10, 0), base radius 3. */
    float points[(N + 2) * 3];
    unsigned indices[N * 6];
    points[0] = 0; points[1] = 10; points[2] = dz;
    points[3] = 0; points[4] = -10; points[5] = dz;
    for (int i = 0; i < N; i++) {
        float a = 2.0f * (float)M_PI * i / N;
        points[6 + 3 * i] = 3.0f * sinf(a);
        points[7 + 3 * i] = -10.0f;
        points[8 + 3 * i] = 3.0f * cosf(a) + dz;
        unsigned v0 = 2 + i, v1 = 2 + (i + 1) % N;
        unsigned *t = indices + 6 * i;
        t[0] = 0; t[1] = v0; t[2] = v1;   /* side, CCW from outside */
        t[3] = 1; t[4] = v1; t[5] = v0;   /* base, CCW from outside */
    }
    GLuint vao, buffers[2];
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(2, buffers);
    glBindBuffer(GL_ARRAY_BUFFER, buffers[0]);
    glBufferData(GL_ARRAY_BUFFER, sizeof(points), points, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, NULL);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, buffers[1]);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(indices), indices, GL_STATIC_DRAW);

    GLuint program = glCreateProgram();
    glAttachShader(program, shader(GL_VERTEX_SHADER, vs_src));
    glAttachShader(program, shader(GL_FRAGMENT_SHADER, fs_src));
    glLinkProgram(program);
    glUseProgram(program);

    /* gluPerspective(45, 1, 0.1, 100), column-major; eye at the origin looking down -Z. */
    float f = 1.0f / tanf(22.5f * (float)M_PI / 180.0f), n = 0.1f, far = 100.0f;
    float mvp[16] = {f, 0, 0, 0,  0, f, 0, 0,
                     0, 0, (far + n) / (n - far), -1,  0, 0, 2 * far * n / (n - far), 0};
    glUniformMatrix4fv(glGetUniformLocation(program, "mvp"), 1, GL_FALSE, mvp);

    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CCW);
    glEnable(GL_DEPTH_TEST);
    int drawn = 0;
    for (int frame = 0; frame < 10; frame++) {
        unsigned char pixel[4];
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glDrawElements(GL_TRIANGLES, N * 6, GL_UNSIGNED_INT, NULL);
        glReadPixels(SIZE / 2, SIZE / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
        printf("frame %d: centre green %d\n", frame, pixel[1]);
        drawn |= pixel[1] != 0;
        usleep(20000);   /* lets the driver's culling shader variant finish compiling */
    }
    printf(drawn ? "FAIL: back faces drawn\n" : "ok: back faces culled\n");
    return drawn;
}
```

## Observed

```text
$ ./ngg_w0
Radeon 8060S Graphics (radeonsi, gfx1151, LLVM 20.1.2, DRM 3.64, 7.0.0-38-generic)
frame 0: centre green 0
frame 1: centre green 255
...
frame 9: centre green 255
FAIL: back faces drawn
```

Frame 0 is culled. Every frame after it draws the inside of the cone. Ten of
ten runs fail.

## Expected

Every frame black, as with each of these, ten of ten runs:

- `AMD_DEBUG=nonggc ./ngg_w0`
- `./ngg_w0 0.01` (no vertex at w = 0)
- `LIBGL_ALWAYS_SOFTWARE=1 ./ngg_w0` (llvmpipe)

Facing is defined for a triangle with a w = 0 vertex. The homogeneous
determinant of its three (x, y, w) rows has the sign the triangle's clipped
remainder has in window space, and here every one of those remainders is
back-facing.

## Further observations

- `glCullFace(GL_FRONT_AND_BACK)` in place of `GL_BACK` draws the same
  frame, which should be black whatever the triangles' facing.
- Frame 0 is right because the first draw of a shader starts with NGG culling
  off; the culled variant is compiled once a draw passes 128 vertices
  (`ngg_cull_vert_threshold`). Where that variant is ready for the first draw,
  for example a second context compiling the same source while the first is
  open, the first frame is wrong too.
- A vertex at w = 1e-40 behaves as w = 0 (a float32 denormal). At w = 1e-30
  the cone is culled.
- Writing `gl_ClipDistance` in the vertex shader, or not, makes no difference.

## Where it appears to come from

Reading Mesa 25.2.8:

- `cull_face_triangle()` in `src/amd/common/nir/ac_nir_cull.c` computes the
  determinant from w-divided positions and returns "not culled" when it is not
  finite ("Don't reject NaN and +/-infinity ... Just trust fixed-function HW to
  handle these cases correctly"). A vertex at w = 0 makes x/w and y/w
  infinite or NaN.
- `si_update_shaders()` in `src/gallium/drivers/radeonsi/si_state_draw.cpp`
  sets `fixed_func_face_culling_needed = !NGG || !si_shader_culling_enabled(hw_vs)`,
  and `si_pm4_emit_rasterizer()` (`si_state.c`) drops `PA_SU_SC_MODE_CNTL`'s
  `CULL_FRONT`/`CULL_BACK` bits when it is false.

So a triangle the shader leaves for the fixed-function hardware reaches a
rasterizer whose face culling is off. Keeping the cull bits set while shader
culling is active, or deciding facing for such triangles in the shader from
the homogeneous determinant, would cull it.

## Workaround

`AMD_DEBUG=nonggc` in the environment before the process creates its first
context. OpenGLContext's test session sets it where a probe finds this fault
(`OpenGLContext/testing/drivercull.py`, `docs/testing.rst`, section "Back faces
with a vertex at clip w = 0").
