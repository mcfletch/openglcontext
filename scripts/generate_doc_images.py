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

Each model is rendered in its own subprocess by ``oglc-view --capture``: one GL
context per process is the robust way to render a batch, and running the viewer
itself is what keeps these images the same pictures a reader gets by opening the
model. That path needs a display (or an offscreen GL platform, e.g.
``PYOPENGL_PLATFORM=egl``).
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
# Frames to render before the capture, so the adaptive analytic-sky IBL has
# settled into the same state it settles into live.
FRAMES = 24
# Fit factor: below 1 pulls the camera in, so the model fills more of the frame
# than its bounding sphere alone would ask for.
MARGIN = 0.92

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
# Parent: builds the job list and spawns a viewer per model.
# --------------------------------------------------------------------------- #
def _spawn(model, out, framing=None, cam=None):
    """Render one model with ``oglc-view --capture`` and save it as a JPEG.

    The viewer already knows how to open a model, light it, frame it, let the
    analytic-sky IBL settle and write one clean frame.  Running it is what keeps
    these images the same pictures a reader gets by typing ``oglc-view`` at the
    model themselves; all that is left here is the docs' own house style, which
    is a fixed width and JPEG rather than PNG.
    """
    from PIL import Image
    cmd = [sys.executable, '-m', 'OpenGLContext.bin.view', model,
           '--size', '%dx680' % WIDTH, '--frames', str(FRAMES),
           '--background', 'sky']
    if cam is not None:
        cmd += ['--camera', str(cam)]
    else:
        yaw, elevation, tilt = framing if framing else (-0.6, 0.1, 0.05)
        # '--yaw=' form, so a leading '-' in a framing value is not read as a flag
        cmd += ['--no-cameras', '--margin', str(MARGIN), '--yaw=%s' % yaw,
                '--elevation=%s' % elevation, '--tilt=%s' % tilt]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ok = False
    with tempfile.TemporaryDirectory() as scratch:
        png = os.path.join(scratch, 'capture.png')
        result = subprocess.run(cmd + ['--capture', png], timeout=300)
        ok = result.returncode == 0 and os.path.exists(png)
        if ok:
            _save_jpeg(Image.open(png), out)
    print('  %s %s' % ('ok  ' if ok else 'FAIL', os.path.relpath(out, REPO)))
    return ok


def _save_jpeg(image, out):
    """Downscale to the docs' width and write ``out`` as a JPEG."""
    image = image.convert('RGB')
    if image.width > WIDTH:
        image = image.resize((WIDTH, round(image.height * WIDTH / image.width)))
    image.save(out, quality=JPEG_QUALITY)


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
    for name, framing in GLTF_DEMOS:
        try:
            model = _download_sample(name)
        except Exception as err:
            print('  FAIL download %s: %s' % (name, err))
            continue
        _spawn(model, os.path.join(out_dir, '%s.jpg' % name), framing=framing)


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
    parser.add_argument('--gltf-only', action='store_true',
                        help='render only the glTF sample gallery')
    parser.add_argument('--parthenon', metavar='GLB',
                        help='path to a Parthenon .glb (default: auto-detect '
                             'the sibling project)')
    args = parser.parse_args()

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
