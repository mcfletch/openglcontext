#! /usr/bin/env python
"""Regenerate the rendered screenshots embedded in the OpenGLContext docs.

Two galleries are produced with the core-profile PBR renderer:

* ``docs/images/gltf/`` -- one shot of each curated Khronos glTF sample model.
  The models are downloaded on demand (and cached) from the Khronos
  glTF-Sample-Models repository, so this needs network access the first time.
* ``docs/images/parthenon/`` -- one shot from each baked camera in a Parthenon
  ``.glb``. This is only produced when the model is available (it lives in the
  sibling ``parthenon`` project, not in this repository).

Run it after a change that could alter rendered output, so the images in the
docs stay honest:

    python scripts/generate_doc_images.py                 # everything available
    python scripts/generate_doc_images.py --gltf-only
    python scripts/generate_doc_images.py --parthenon ../parthenon/parthenon.glb

Each model is rendered in its own subprocess: one GL context per process is the
robust way to render a batch. The script re-invokes itself with ``--worker`` to
do the actual rendering; that path needs a display (or an offscreen GL platform,
e.g. ``PYOPENGL_PLATFORM=egl``).
"""
import argparse
import os
import subprocess
import sys
import tempfile
from urllib.request import urlretrieve

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DOCS_IMAGES = os.path.join(REPO, 'docs', 'images')
CACHE = os.path.join(tempfile.gettempdir(), 'oglc-gltf-samples')

# Output width; renders are downscaled to this and saved as JPEG.
WIDTH = 1100
JPEG_QUALITY = 88

# Curated subset of the sample gallery for the docs. The framing (yaw, elevation,
# tilt) comes from the shared per-scene metadata (OpenGLContext.loaders.gltf_demos)
# so the doc images and the regression captures frame each model identically.
from OpenGLContext.loaders import gltf_demos as _demos

_DOC_GALLERY = [
    'DamagedHelmet', 'WaterBottle', 'BoomBox', 'MetalRoughSpheres',
    'BarramundiFish', 'Duck', 'IridescentDishWithOlives',
]
GLTF_DEMOS = [
    (name, (_demos.scene_for(name).yaw, _demos.scene_for(name).elevation,
            _demos.scene_for(name).tilt))
    for name in _DOC_GALLERY
]

# Demo test-scripts to capture whole (they set their own camera and scene). Each
# is (module, output-basename, frames-before-capture); rendered with the built-in
# auto-exit screenshot mechanism.
DEMO_SCRIPTS = [
    ('shadow_demo', 'shadow_demo', 24),
]


# --------------------------------------------------------------------------- #
# Worker: renders exactly one model in its own GL context.
# --------------------------------------------------------------------------- #
def _run_worker(model, out, eye=None, cam=None):
    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
    os.environ.setdefault('OPENGLCONTEXT_SHADOWS', '1')
    os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    os.environ.setdefault('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '24')
    os.environ.setdefault('OPENGLCONTEXT_SHADOW_CASCADES', '3')
    os.environ.setdefault('OPENGLCONTEXT_IBL_INTENSITY', '0.4')

    from math import pi, sin
    import numpy as np
    from PIL import Image
    from OpenGL.GL import (
        glReadPixels, glGetIntegerv, glReadBuffer,
        GL_VIEWPORT, GL_RGB, GL_UNSIGNED_BYTE, GL_BACK,
    )
    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph.basenodes import sceneGraph, Transform
    from OpenGLContext.loaders import gltf
    from OpenGLContext.bin import gltf_view

    BaseContext = testingcontext.getInteractive()

    class CaptureContext(BaseContext):
        def OnInit(self):
            # scene.group is the model's root Transform (one child Transform per
            # glTF node); scene.getDEF(name) reaches an individual node.
            scene = gltf.load_gltf(model)
            cx, cy, cz = scene.center
            radius = scene.radius or 1.0
            cams = list(getattr(scene, 'cameras', None) or [])
            n_lights = gltf_view._count_lights(scene.group)
            lights = [] if n_lights else self._default_lights(radius)

            if cam is not None and cams:
                node = Transform(children=[scene.group])
                self.sg = sceneGraph(
                    children=[gltf_view.TestContext._sky(), node] + lights)
                pose = cams[cam % len(cams)]
                near = pose.get('near') or radius * 0.02
                far = pose.get('far') or radius * 20.0
                self.platform.setFrustum(pose.get('fov') or (pi / 3.2), None,
                                         near, far)
                self.platform.setPosition(tuple(pose['position']))
                self.platform.setOrientation(
                    gltf_view._orientation(pose['forward'], pose['up']))
                return

            yaw, elev, tilt = eye if eye else (-0.6, 0.1, 0.05)
            centred = Transform(translation=(-cx, -cy, -cz),
                                children=[scene.group])
            node = Transform(rotation=(0, 1, 0, yaw), children=[centred])
            self.sg = sceneGraph(
                children=[gltf_view.TestContext._sky(), node] + lights)
            fov = pi / 3.2
            distance = radius / max(1e-3, sin(fov / 2.0)) * 0.92
            self.platform.setFrustum(fov, None, max(1e-4, radius * 0.02),
                                     radius * 60.0)
            self.platform.setPosition((0.0, radius * elev, distance))
            self.platform.setOrientation((1, 0, 0, tilt))

        _default_lights = gltf_view.TestContext._default_lights

        def OnIdle(self, *a):
            self.triggerRedraw(1)
            return 1

        def SwapBuffers(self):
            # Save every frame (last write wins): the analytic-sky IBL settles
            # over several frames, and auto-exit may not return cleanly.
            try:
                _x, _y, w, h = (int(v) for v in glGetIntegerv(GL_VIEWPORT))
                glReadBuffer(GL_BACK)
                px = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
                arr = np.flipud(
                    np.frombuffer(px, dtype=np.uint8).reshape(h, w, 3)).copy()
                im = Image.fromarray(arr, 'RGB')
                if im.width > WIDTH:
                    im = im.resize((WIDTH, round(im.height * WIDTH / im.width)))
                im.save(out, quality=JPEG_QUALITY)
            except Exception:
                import traceback
                traceback.print_exc()
            return super().SwapBuffers()

    CaptureContext.ContextMainLoop(size=(WIDTH, 680))


# --------------------------------------------------------------------------- #
# Parent: builds the job list and spawns a worker per model.
# --------------------------------------------------------------------------- #
def _spawn(model, out, eye=None, cam=None):
    cmd = [sys.executable, os.path.abspath(__file__), '--worker', model, out]
    if cam is not None:
        cmd += ['--cam', str(cam)]
    elif eye is not None:
        # '--eye=' form so a leading '-' in a framing value isn't parsed as a flag
        cmd += ['--eye=%s,%s,%s' % eye]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    result = subprocess.run(cmd, timeout=300)
    ok = result.returncode == 0 and os.path.exists(out)
    print('  %s %s' % ('ok  ' if ok else 'FAIL', os.path.relpath(out, REPO)))
    return ok


def _download_sample(name):
    from OpenGLContext.loaders import gltf
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, '%s.glb' % name)
    if not os.path.exists(path):
        url = gltf.sample_model_url(name)
        print('  downloading %s' % name)
        urlretrieve(url, path)
    return path


def _capture_script(module, out, frames):
    """Run a demo test-script whole and grab a frame via the auto-exit capture."""
    import tempfile
    from PIL import Image
    tests_dir = os.path.join(REPO, 'tests')
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ)
        env.setdefault('OPENGLCONTEXT_PROFILE', 'core')
        env.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
        env.setdefault('OPENGLCONTEXT_SHADOWS', '1')
        env['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
        env['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = str(frames)
        env['OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR'] = td
        env['OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME'] = 'cap'
        # Import the module and run it at a fixed window size (larger than the
        # default) so the captured frame downscales cleanly.
        code = ('import sys; sys.path.insert(0, %r); import %s as m; '
                'm.TestContext.ContextMainLoop(size=(%d, %d))'
                % (tests_dir, module, WIDTH, 680))
        try:
            subprocess.run([sys.executable, '-c', code], timeout=300, env=env)
        except Exception as err:
            print('  FAIL %s: %s' % (module, err))
            return
        png = os.path.join(td, 'cap.png')
        if not os.path.exists(png):
            print('  FAIL %s (no capture produced)' % os.path.relpath(out, REPO))
            return
        im = Image.open(png).convert('RGB')
        if im.width > WIDTH:
            im = im.resize((WIDTH, round(im.height * WIDTH / im.width)))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        im.save(out, quality=JPEG_QUALITY)
        print('  ok   %s' % os.path.relpath(out, REPO))


def _demo_gallery():
    print('Demo scripts -> docs/images/')
    for module, name, frames in DEMO_SCRIPTS:
        _capture_script(module, os.path.join(DOCS_IMAGES, '%s.jpg' % name), frames)


def _gltf_gallery():
    print('glTF sample gallery -> docs/images/gltf/')
    out_dir = os.path.join(DOCS_IMAGES, 'gltf')
    for name, eye in GLTF_DEMOS:
        try:
            model = _download_sample(name)
        except Exception as err:
            print('  FAIL download %s: %s' % (name, err))
            continue
        _spawn(model, os.path.join(out_dir, '%s.jpg' % name), eye=eye)


def _parthenon_gallery(model):
    from OpenGLContext.loaders import gltf
    print('Parthenon cameras -> docs/images/parthenon/')
    scene = gltf.load_gltf(model)          # parse only, no GL context needed
    cams = list(getattr(scene, 'cameras', None) or [])
    if not cams:
        print('  no baked cameras in %s' % model)
        return
    out_dir = os.path.join(DOCS_IMAGES, 'parthenon')
    for i, pose in enumerate(cams):
        name = pose.get('name') or ('camera-%02d' % i)
        _spawn(model, os.path.join(out_dir, '%s.jpg' % name), cam=i)


def _find_parthenon():
    for rel in ('../parthenon/parthenon.glb', '../../parthenon/parthenon.glb'):
        p = os.path.normpath(os.path.join(REPO, rel))
        if os.path.exists(p):
            return p
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--worker', nargs=2, metavar=('MODEL', 'OUT'),
                        help=argparse.SUPPRESS)
    parser.add_argument('--eye', help=argparse.SUPPRESS)
    parser.add_argument('--cam', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--gltf-only', action='store_true',
                        help='render only the glTF sample gallery')
    parser.add_argument('--parthenon', metavar='GLB',
                        help='path to a Parthenon .glb (default: auto-detect '
                             'the sibling project)')
    args = parser.parse_args()

    if args.worker:
        eye = tuple(float(v) for v in args.eye.split(',')) if args.eye else None
        _run_worker(args.worker[0], args.worker[1], eye=eye, cam=args.cam)
        return

    _gltf_gallery()
    if not args.gltf_only:
        _demo_gallery()
        model = args.parthenon or _find_parthenon()
        if model and os.path.exists(model):
            _parthenon_gallery(model)
        else:
            print('Parthenon model not found; skipping (pass --parthenon PATH '
                  'to include it).')


if __name__ == '__main__':
    main()
