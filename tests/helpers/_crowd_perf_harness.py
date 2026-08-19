"""How many animated figures a frame will carry (invoked as a subprocess).

The acceptance instrument for the character-scaling work: a field of skinned
figures, each animating on its own clock, rendered offscreen for a fixed number
of frames, with the frame split into the two halves that scale differently --
the **animation** (sampling clips, blending, composing the skeleton, building
joint matrices) and the **draw** (submitting the meshes and letting the GPU
skin them).

    python tests/helpers/_crowd_perf_harness.py FIGURES [FRAMES] [options]

Options are ``key=value`` and settle what is being measured:

    skinning=gpu|cpu     where linear-blend skinning runs (default gpu)
    write=exposed|all    how much of each pose reaches the scenegraph
    joints=57            bones per figure
    vertices=4096        skinned vertices per figure
    shadows=0|1          whether the figures cast shadows
    clip_share=1         figures per distinct clip phase (crowd dedupe)

Reports one JSON object on the last line of stdout.
"""
import cProfile
import io
import json
import math
import os
import pstats
import sys
import time


def _options(argv):
    options = {'skinning': 'gpu', 'write': 'exposed', 'joints': 57,
               'vertices': 4096, 'shadows': 0, 'clip_share': 1,
               'crowd': 1, 'budget': 0, 'profile': 0, 'compute': 1,
               'finish': 1}
    for item in argv:
        if '=' not in item:
            continue
        key, value = item.split('=', 1)
        options[key] = value if key in ('skinning', 'write') else int(value)
    return options


def main():
    figures = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    options = _options(sys.argv[3:])

    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
    os.environ['OPENGLCONTEXT_SHADOWS'] = str(options['shadows'])
    os.environ['OPENGLCONTEXT_IBL'] = 'off'
    os.environ['OPENGLCONTEXT_BLOOM'] = '0'
    os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    os.environ.setdefault('OPENGLCONTEXT_HIDDEN', '1')
    os.environ.setdefault('OPENGLCONTEXT_NO_VSYNC', '1')
    os.environ['OPENGLCONTEXT_GPU_SKINNING'] = \
        '1' if options['skinning'] == 'gpu' else '0'

    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(os.path.dirname(here)))
    sys.path.insert(0, os.path.dirname(here))

    from OpenGL.GL import glFinish
    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGLContext.scenegraph.basenodes import (
        sceneGraph, Transform, DirectionalLight,
    )
    from OpenGLContext.character.crowd import Crowd
    from OpenGLContext.character.model import CharacterModel
    from OpenGLContext.loaders.gltf import load_gltf, parse_gltf
    from helpers._crowd_asset import crowd_character_glb

    timings = {'update': [], 'draw': []}
    built = {}
    profiler = cProfile.Profile() if options['profile'] else None

    def build():
        """One parse, one scenegraph per figure, laid out on a grid."""
        start = time.perf_counter()
        document = parse_gltf(crowd_character_glb(
            joints=options['joints'], vertices=options['vertices']))
        models, roots = [], []
        columns = int(math.ceil(math.sqrt(figures)))
        names = None
        for index in range(figures):
            model = CharacterModel(load_gltf(document=document))
            model.mixer.pose_write = options['write']
            if names is None:
                names = sorted(model.clips)
            model.play(names[index % len(names)])
            # Every figure on its own clock, so no two are posed alike unless
            # clip_share says to make them so -- which is what a crowd dedupe
            # would exploit and what its absence has to be measured against.
            phase = (index // options['clip_share']) * 0.037
            model.mixer.layers[0].tracks[0].time = phase % 1.0
            gx, gz = (index % columns) - columns / 2.0, (index // columns) * 1.4
            roots.append(Transform(translation=(gx * 1.2, -1.0, -gz),
                                   children=[model.group]))
            models.append(model)
        built['seconds'] = time.perf_counter() - start
        if options['crowd']:
            crowd = Crowd(compute=bool(options['compute']))
            for model in models:
                crowd.add(model)
            built['crowd'] = crowd
        return models, sceneGraph(children=roots + [
            DirectionalLight(direction=(-0.3, -0.5, -1.0), color=(1, 1, 1),
                             intensity=2.0),
        ])

    def report():
        out = {'figures': figures, 'frames': len(timings['draw']),
               'build_seconds': round(built.get('seconds', 0.0), 3)}
        for name, samples in timings.items():
            ordered = sorted(samples)
            out['%s_ms' % name] = (round(ordered[len(ordered) // 2], 4)
                                   if ordered else 0.0)
        total = out['update_ms'] + out['draw_ms']
        out['frame_ms'] = round(total, 4)
        out['fps'] = round(1000.0 / total, 1) if total else 0.0
        out.update({k: v for k, v in options.items()})
        print(json.dumps(out), flush=True)
        if profiler is not None:
            report = io.StringIO()
            pstats.Stats(profiler, stream=report).sort_stats('tottime').print_stats(18)
            print(report.getvalue(), flush=True)

    class CrowdContext(BaseContext):
        def OnInit(self):
            try:
                import glfw
                glfw.swap_interval(0)
            except Exception:
                pass
            self.models, self.sg = build()
            self.platform.setPosition((0, 2, 14))
            self._frame = 0

        def OnIdle(self, *a):
            self.triggerRedraw(1)
            return 1

        def OnQuit(self, *a, **k):
            report()
            return BaseContext.OnQuit(self, *a, **k)

        def OnDraw(self, *a, **k):
            started = time.perf_counter()
            crowd = built.get('crowd')
            if crowd is not None:
                crowd.update(1 / 60.0, budget=options['budget'] or None,
                             mode=self)
            else:
                for model in self.models:
                    model.update(1 / 60.0)
            posed = time.perf_counter()
            if profiler is not None and self._frame > 12:
                profiler.enable()
                result = BaseContext.OnDraw(self, *a, **k)
                profiler.disable()
            else:
                result = BaseContext.OnDraw(self, *a, **k)
            if options['finish']:
                glFinish()
            done = time.perf_counter()
            if self._frame > 12:        # past shader compile and buffer upload
                timings['update'].append((posed - started) * 1000.0)
                timings['draw'].append((done - posed) * 1000.0)
            self._frame += 1
            return result

    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = str(frames + 14)
    CrowdContext.ContextMainLoop()
    report()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
