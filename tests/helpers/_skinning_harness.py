"""Render a posed skinned figure through each skinning path (a subprocess).

Two jobs, chosen by the first argument:

``compare``
    Render one posed figure with the vertex shader skinning it and again with
    the CPU deform, and report how much of the frame differs. The CPU deform is
    what every reference image was made with, so the shader's job is to agree
    with it.
``uploads``
    Animate a figure for many frames with the shader skinning it and count what
    crossed the bus: the joint palette should be written every frame and the
    vertex buffers not at all.

Both report ``key=value`` lines on stdout.
"""
import os
import sys


def _render(model_path, out_dir, gpu, frames=12):
    """Render the figure posed mid-clip and return the captured RGB array."""
    import numpy as np
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE

    os.environ['OPENGLCONTEXT_GPU_SKINNING'] = '1' if gpu else '0'
    from OpenGLContext import renderoptions
    renderoptions.reset_env_cache()

    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGLContext.scenegraph.basenodes import (
        sceneGraph, Transform, DirectionalLight,
    )
    from OpenGLContext.character.model import CharacterModel

    captured = {}

    class SkinContext(BaseContext):
        def OnInit(self):
            self.model = CharacterModel.load(model_path)
            self.model.play(sorted(self.model.clips)[0], loop=False)
            self.model.update(0.6)
            self.sg = sceneGraph(children=[
                Transform(translation=(0, 0, 0), children=[self.model.group]),
                DirectionalLight(direction=(-0.3, -0.4, -1.0),
                                 color=(1, 1, 1), intensity=2.0),
            ])
            self.platform.setPosition((0, 0, 6))
            self._frame = 0

        def OnIdle(self, *a):
            self.triggerRedraw(1)
            return 1

        def OnDraw(self, *a, **k):
            result = BaseContext.OnDraw(self, *a, **k)
            self._frame += 1
            if self._frame == frames:
                width, height = self.getViewPort()
                raw = glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE)
                captured['pixels'] = np.frombuffer(raw, dtype=np.uint8).copy()
                captured['mesh'] = _first_skinned(self.model)
            return result

    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = str(frames + 1)
    SkinContext.ContextMainLoop()
    return captured


def _first_skinned(model):
    for skin in model.mixer.skins:
        for mesh in getattr(skin, 'meshes', ()):
            return mesh
    return None


def _walk_meshes(node, seen=None):
    seen = seen if seen is not None else set()
    if id(node) in seen:
        return
    seen.add(id(node))
    if getattr(node, 'skin_joints', None) is not None:
        yield node
    for name in ('children', 'geometry'):
        value = getattr(node, name, None)
        if value is None:
            continue
        for child in (value if isinstance(value, (list, tuple)) else [value]):
            yield from _walk_meshes(child, seen)


def _setup(gpu):
    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
    os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
    os.environ['OPENGLCONTEXT_IBL'] = 'off'
    os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    os.environ['OPENGLCONTEXT_HIDDEN'] = '1'
    os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
    os.environ['OPENGLCONTEXT_GPU_SKINNING'] = '1' if gpu else '0'


def compare(model_path, out_dir):
    """Render both ways in one process and report the difference."""
    import numpy as np
    _setup(True)
    report = {}
    frames = {}

    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGLContext.scenegraph.basenodes import (
        sceneGraph, Transform, DirectionalLight,
    )
    from OpenGLContext.character.model import CharacterModel
    from OpenGLContext.scenegraph import skinning

    class SkinContext(BaseContext):
        def OnInit(self):
            self.models = []
            self.roots = []
            for _ in range(2):
                model = CharacterModel.load(model_path)
                self.models.append(model)
                self.roots.append(Transform(children=[model.group]))
            # The second figure is pinned to the CPU deform; the first takes
            # whatever the renderer offers, which here is the shader.
            for mesh in _walk_meshes(self.models[1].group):
                mesh.skin_on_gpu = False
            self.sg = sceneGraph(children=[
                self.roots[0],
                DirectionalLight(direction=(-0.3, -0.4, -1.0),
                                 color=(1, 1, 1), intensity=2.0),
            ])
            self.platform.setPosition((0, 0, 5))
            self._frame = 0
            self._stage = 0

        def OnIdle(self, *a):
            self.triggerRedraw(1)
            return 1

        def OnDraw(self, *a, **k):
            for model in self.models:
                model.mixer.reset()
                model.play(sorted(model.clips)[0], loop=False)
                model.update(0.9)
            result = BaseContext.OnDraw(self, *a, **k)
            self._frame += 1
            if self._frame in (6, 12):
                width, height = self.getViewPort()
                raw = glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE)
                frames[self._stage] = np.frombuffer(raw, dtype=np.uint8).copy()
                if self._stage == 0:
                    meshes = list(_walk_meshes(self.models[0].group))
                    report['skin_on_gpu'] = int(
                        bool(meshes) and all(m.skin_on_gpu for m in meshes))
                    report['skinning_supported'] = int(
                        skinning.palette_supported())
                    self.sg.children[0] = self.roots[1]
                    self._stage = 1
            return result

    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = '14'

    class Reporting(SkinContext):
        def OnQuit(self, *a, **k):
            _emit(report, frames)
            return SkinContext.OnQuit(self, *a, **k)

    Reporting.ContextMainLoop()
    _emit(report, frames)


def _emit(report, frames):
    import numpy as np
    if 0 in frames and 1 in frames:
        gpu, cpu = frames[0].astype(np.int16), frames[1].astype(np.int16)
        differing = np.abs(gpu - cpu) > 8
        report['differing_fraction'] = float(differing.mean())
        # A frame that is all background would agree trivially; the pose has to
        # have moved something for the comparison to mean anything.
        report['moved'] = int(bool((cpu > 16).any()))
    for key, value in report.items():
        print('%s=%s' % (key, value), flush=True)


def uploads(model_path, out_dir):
    """Animate with the shader skinning and count what was uploaded."""
    _setup(True)
    counts = {'vertex_uploads': 0, 'palette_writes': 0}

    from OpenGLContext.scenegraph import pbrmesh as pbrmesh_mod
    from OpenGLContext.scenegraph import skinning as skinning_mod

    original_update = pbrmesh_mod._MeshGPU.update_dynamic

    def counting_update(self, mesh):
        counts['vertex_uploads'] += 1
        return original_update(self, mesh)

    pbrmesh_mod._MeshGPU.update_dynamic = counting_update

    original_write = skinning_mod.JointPalette.write

    def counting_write(self, base, matrices):
        counts['palette_writes'] += 1
        return original_write(self, base, matrices)

    skinning_mod.JointPalette.write = counting_write

    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGLContext.scenegraph.basenodes import (
        sceneGraph, Transform, DirectionalLight,
    )
    from OpenGLContext.character.model import CharacterModel

    state = {}

    class SkinContext(BaseContext):
        def OnInit(self):
            self.model = CharacterModel.load(model_path)
            self.model.play(sorted(self.model.clips)[0])
            self.sg = sceneGraph(children=[
                Transform(children=[self.model.group]),
                DirectionalLight(direction=(-0.3, -0.4, -1.0),
                                 color=(1, 1, 1), intensity=2.0),
            ])
            self.platform.setPosition((0, 0, 5))

        def OnIdle(self, *a):
            self.model.update(1 / 60.0)
            self.triggerRedraw(1)
            return 1

        def OnDraw(self, *a, **k):
            result = BaseContext.OnDraw(self, *a, **k)
            meshes = list(_walk_meshes(self.model.group))
            state['skin_on_gpu'] = int(bool(meshes)
                                       and all(m.skin_on_gpu for m in meshes))
            return result

        def OnQuit(self, *a, **k):
            _report(state, counts)
            return BaseContext.OnQuit(self, *a, **k)

    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = '40'
    SkinContext.ContextMainLoop()
    _report(state, counts)


def _report(state, counts):
    for key, value in list(state.items()) + list(counts.items()):
        print('%s=%s' % (key, value), flush=True)


def main():
    job = sys.argv[1]
    return {'compare': compare, 'uploads': uploads, 'compute': compute,
            'fallback': fallback, 'blend': blend}[job](sys.argv[2], sys.argv[3])



def compute(model_path, out_dir):
    """Compare the palettes a compute shader writes with the ones numpy does."""
    _setup(True)
    import numpy as np
    from OpenGL.GL import (
        GL_TEXTURE_BUFFER, glBindBuffer, glGetBufferSubData,
    )
    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGLContext.scenegraph.basenodes import (
        sceneGraph, Transform, DirectionalLight,
    )
    from OpenGLContext.character.crowd import Crowd
    from OpenGLContext.character.model import CharacterModel
    from OpenGLContext.character import gpuskeleton
    from OpenGLContext.loaders.gltf import load_gltf, parse_gltf
    from OpenGLContext.scenegraph.skinning import MATRIX_FLOATS, palette_for

    report = {}

    class ComputeContext(BaseContext):
        def OnInit(self):
            document = parse_gltf(open(model_path, 'rb').read())
            self.models = [CharacterModel(load_gltf(document=document))
                           for _ in range(4)]
            self.crowd = Crowd()
            for index, model in enumerate(self.models):
                model.mixer.pose_write = 'exposed'
                model.play(sorted(model.clips)[0])
                model.mixer.layers[0].tracks[0].time = 0.17 * index
                self.crowd.add(model)
            self.sg = sceneGraph(children=[
                Transform(translation=(index * 1.5 - 2, 0, 0),
                          children=[model.group])
                for index, model in enumerate(self.models)
            ] + [DirectionalLight(direction=(-0.3, -0.4, -1.0),
                                  color=(1, 1, 1), intensity=2.0)])
            self.platform.setPosition((0, 0, 8))
            self._frame = 0

        def OnIdle(self, *a):
            self.triggerRedraw(1)
            return 1

        def OnDraw(self, *a, **k):
            self.crowd.update(1 / 60.0, mode=self)
            result = BaseContext.OnDraw(self, *a, **k)
            self._frame += 1
            if self._frame == 8:
                self._measure()
            return result

        def _measure(self):
            report['compute_available'] = int(gpuskeleton.compute_is_available())
            report['compute_ran'] = int(self.crowd._skeleton is not None)
            palette = palette_for(self)
            if palette is None or self.crowd._skeleton is None:
                return
            glBindBuffer(GL_TEXTURE_BUFFER, palette.buffer)
            raw = glGetBufferSubData(GL_TEXTURE_BUFFER, 0,
                                     palette.used * MATRIX_FLOATS * 4)
            glBindBuffer(GL_TEXTURE_BUFFER, 0)
            read = np.frombuffer(bytes(raw), dtype='<f4').reshape(-1, 4, 4)
            worst = 0.0
            checked = 0
            for model in self.models:
                for wanted, plan in zip(model.mixer.joint_matrices(),
                                       model.mixer._skin_plans, strict=True):
                    for mesh in plan[0].meshes:
                        base = palette.reserved_base(mesh)
                        if base is None:
                            continue
                        got = read[base:base + len(wanted)]
                        worst = max(worst, float(
                            np.abs(got - wanted.astype('f4')).max()))
                        checked += len(wanted)
            report['matrices_checked'] = checked
            report['worst_difference'] = worst

        def OnQuit(self, *a, **k):
            _report({}, report)
            return BaseContext.OnQuit(self, *a, **k)

    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = '10'
    ComputeContext.ContextMainLoop()
    _report({}, report)


def fallback(model_path, out_dir):
    """Check the processor path engages for a mesh that would otherwise batch.

    A mesh drawn in an instanced batch has no draw of its own, so where it is
    skinned has to be settled before the batch is formed; settled at its first
    draw it would never be settled at all, and the renderer would go on
    skinning in the shader whatever it had been asked for.
    """
    _setup(False)
    from OpenGLContext import renderoptions
    renderoptions.reset_env_cache()

    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGLContext.scenegraph.basenodes import (
        sceneGraph, Transform, DirectionalLight,
    )
    from OpenGLContext.character.model import CharacterModel
    from OpenGLContext.loaders.gltf import load_gltf, parse_gltf

    state = {}

    class FallbackContext(BaseContext):
        def OnInit(self):
            document = parse_gltf(open(model_path, 'rb').read())
            self.models = [CharacterModel(load_gltf(document=document))
                           for _ in range(6)]
            for index, model in enumerate(self.models):
                model.play(sorted(model.clips)[0])
                model.mixer.layers[0].tracks[0].time = 0.11 * index
            self.sg = sceneGraph(children=[
                Transform(translation=(index * 1.2 - 3, 0, 0),
                          children=[model.group])
                for index, model in enumerate(self.models)
            ] + [DirectionalLight(direction=(-0.3, -0.4, -1.0),
                                  color=(1, 1, 1), intensity=2.0)])
            self.platform.setPosition((0, 0, 8))
            self._frame = 0

        def OnIdle(self, *a):
            for model in self.models:
                model.update(1 / 60.0)
            self.triggerRedraw(1)
            return 1

        def OnDraw(self, *a, **k):
            result = BaseContext.OnDraw(self, *a, **k)
            self._frame += 1
            if self._frame == 6:
                meshes = list(_walk_meshes(self.models[0].group))
                state['meshes'] = len(meshes)
                state['skin_on_gpu'] = int(any(m.skin_on_gpu for m in meshes))
                state['deforms_vertices'] = int(
                    all(m.deforms_vertices for m in meshes))
                state['moved'] = int(all(
                    not _at_rest(m) for m in meshes))
            return result

        def OnQuit(self, *a, **k):
            _report(state, {})
            return BaseContext.OnQuit(self, *a, **k)

    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = '8'
    FallbackContext.ContextMainLoop()
    _report(state, {})


def _at_rest(mesh):
    import numpy as np
    return mesh._base_positions is None or np.allclose(
        mesh.positions, mesh._base_positions, atol=1e-6)


def blend(model_path, out_dir):
    """Compare the pose a compute shader blends with the one numpy blends."""
    _setup(True)
    import numpy as np
    from OpenGL.GL import (
        GL_SHADER_STORAGE_BUFFER, glBindBuffer, glGetBufferSubData,
    )
    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGLContext.scenegraph.basenodes import (
        sceneGraph, Transform, DirectionalLight,
    )
    from OpenGLContext.character.crowd import Crowd
    from OpenGLContext.character.model import CharacterModel
    from OpenGLContext.loaders.gltf import load_gltf, parse_gltf

    report = {}

    class BlendContext(BaseContext):
        def OnInit(self):
            document = parse_gltf(open(model_path, 'rb').read())
            self.models = [CharacterModel(load_gltf(document=document))
                           for _ in range(5)]
            self.crowd = Crowd()
            # Every figure alike in *shape* -- the same number of clips -- so
            # the crowd answers them in one group and one pose buffer, and
            # unalike in everything else: different clips, clocks and weights.
            wanted = int(os.environ.get('BLEND_TRACKS', '2'))
            equipped = int(os.environ.get('BLEND_EQUIPPED', '0'))
            masked = int(os.environ.get('BLEND_MASKED', '0'))
            names = None
            for index, model in enumerate(self.models):
                model.mixer.pose_write = 'exposed'
                names = names or sorted(model.clips)
                model.play(names[index % len(names)])
                if wanted > 1:
                    model.play(names[(index + 1) % len(names)], fade=0.5)
                    model.mixer.layers[0].tracks[0].weight = 0.35 + 0.1 * index
                    model.mixer.layers[0].tracks[-1].weight = 0.65 - 0.1 * index
                for position, track in enumerate(model.mixer.layers[0].tracks):
                    track.time = 0.13 * index + 0.07 * position
                if masked:
                    # A second layer over the first, moving the upper joints
                    # only -- a figure firing while it runs.
                    upper = frozenset(range(masked, model.mixer.rig.n))
                    layer = model.mixer.layer('upper', mask=upper,
                                              weight=0.8 if index % 2 else 1.0)
                    layer.play(names[(index + 2) % len(names)])
                    layer.tracks[0].time = 0.09 * index
                if equipped:
                    # Something hung on a deep joint, which is what makes the
                    # scenegraph need that joint and the ones down to it.
                    from OpenGLContext.character.attachment import attach
                    from OpenGLContext.scenegraph.transform import Transform \
                        as HeldTransform
                    rig = model.mixer.rig
                    attach(rig.transforms[min(equipped, rig.n - 1)],
                           HeldTransform())
                self.crowd.add(model)
            self.sg = sceneGraph(children=[
                Transform(translation=(index * 1.5 - 3, 0, 0),
                          children=[model.group])
                for index, model in enumerate(self.models)
            ] + [DirectionalLight(direction=(-0.3, -0.4, -1.0),
                                  color=(1, 1, 1), intensity=2.0)])
            self.platform.setPosition((0, 0, 9))
            self._frame = 0

        def OnIdle(self, *a):
            self.triggerRedraw(1)
            return 1

        def OnDraw(self, *a, **k):
            # Frames the crowd blends on the GPU are the ones that owe no
            # bounds refresh; drive it to one of those and read it back.
            self.crowd.update(0.0, mode=self)
            result = BaseContext.OnDraw(self, *a, **k)
            self._frame += 1
            if self._frame == 9:
                self._measure()
            return result

        def _measure(self):
            skeleton = self.crowd._skeleton
            report['blend_ran'] = int(
                skeleton is not None and bool(skeleton.clip_index))
            if not report['blend_ran']:
                return
            joints = skeleton.joints_per_figure
            count = len(self.models)
            buffer = skeleton._buffers['pose']
            wanted = count * joints * 3 * 16
            report['pose_capacity'] = buffer.capacity
            report['pose_wanted'] = wanted
            report['writable'] = len(self.models[0].mixer._writable())
            if buffer.capacity < wanted:
                return
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffer.name)
            raw = glGetBufferSubData(GL_SHADER_STORAGE_BUFFER, 0, wanted)
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0)
            read = np.frombuffer(bytes(raw), dtype='<f4').reshape(
                count, joints, 3, 4)
            worst = {'translation': 0.0, 'rotation': 0.0, 'scale': 0.0}
            for figure, model in enumerate(self.models):
                wanted = model.mixer.pose()
                for layer in model.mixer.layers:
                    if layer.weight and layer.tracks:
                        model.mixer._apply_layer(layer, wanted, {})
                for path, (name, width) in enumerate(
                        (('translation', 3), ('rotation', 4), ('scale', 3))):
                    got = read[figure, :, path, :width]
                    mine = np.asarray(wanted[path])[:, :width]
                    if name == 'rotation':
                        # A quaternion and its negation are one rotation.
                        flip = np.sign(np.sum(got * mine, axis=1))[:, None]
                        flip[flip == 0] = 1.0
                        got = got * flip
                    worst[name] = max(worst[name],
                                      float(np.abs(got - mine).max()))
            report['joints_checked'] = count * joints
            for name, value in worst.items():
                report['worst_%s' % name] = value
            self._check_written()

        def _check_written(self):
            """Are the joints the scenegraph reads where the whole blend puts them?

            Those are worked out here rather than on the GPU -- a few joints, not
            the skeleton -- so what they have to match is the pose the processor
            would have arrived at for the whole figure.
            """
            import numpy as np
            from OpenGLContext.loaders.gltf.animation import quat_xyzw_to_vrml_rows

            worst = 0.0
            checked = 0
            for model in self.models:
                mixer = model.mixer
                written = mixer._writable()
                if not len(written):
                    continue
                wanted = mixer.pose()
                for layer in mixer.layers:
                    if layer.weight and layer.tracks:
                        mixer._apply_layer(layer, wanted, {})
                axis_angle = quat_xyzw_to_vrml_rows(wanted[1][written])
                for index, slot in enumerate(written):
                    node = mixer.rig.transforms[int(slot)]
                    for got, mine in (
                            (node.translation, wanted[0][int(slot)]),
                            (node.rotation, axis_angle[index]),
                            (node.scale, wanted[2][int(slot)])):
                        worst = max(worst, float(
                            np.abs(np.asarray(got, dtype='d') - mine).max()))
                    checked += 1
            report['written_joints'] = checked
            report['worst_written'] = worst

        def OnQuit(self, *a, **k):
            _report({}, report)
            return BaseContext.OnQuit(self, *a, **k)

    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = '11'
    BlendContext.ContextMainLoop()
    _report({}, report)

if __name__ == '__main__':
    raise SystemExit(main() or 0)
