"""Draw a knocked-down ragdoll figure once it has settled (a subprocess).

``python _ragdoll_draw_harness.py MODEL OUT_PNG`` loads the figure in
``MODEL`` (``tests/unit/_character_assets.ragdoll_figure_glb``), knocks it
down on a floor and steps until every bone is asleep, then draws a few
frames in whichever window system ``OPENGLCONTEXT_BACKEND`` names, with
skinning where ``OPENGLCONTEXT_GPU_SKINNING`` puts it. The last frame read
back is written to ``OUT_PNG``.

It reports ``key=value`` lines on stdout:

``settled``
    1 when every bone was asleep before the frames were drawn.
``skin_on_gpu``
    1 when the vertex shader did the skinning.
``worst_skin_error``
    The farthest any skin vertex is drawn from where its bone's ragdoll
    body puts it, metres: each vertex's rest offset from its joint, carried
    by that bone's world pose.
``bone_vertices``
    How many vertices that comparison covered.
``hips_height``
    The pelvis body's height above the floor, metres.
"""
import os
import sys

import numpy as np
from OpenGL.GL import GL_RGB, GL_UNSIGNED_BYTE, glReadPixels
from PIL import Image

#: The world's step, the knock-down's impulse on the chest (N s), and how long it may take to settle.
STEP = 1.0 / 60.0
BLOW = (0.0, 0.0, -40.0)
SETTLE_SECONDS = 10.0
FRAMES = 6


def _setup():
    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
    os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
    os.environ['OPENGLCONTEXT_IBL'] = 'off'
    os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    os.environ['OPENGLCONTEXT_HIDDEN'] = '1'
    os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = str(FRAMES + 2)


def skin_error(figure):
    """The worst distance of a vertex from its bone's body, metres, and how many vertices were measured.

    Only vertices weighted to a joint that is itself a ragdoll bone are
    measured: a body's frame is its joint's world frame at rest, so the
    vertex belongs at its rest offset from the joint, turned and carried by
    the body.
    """
    from OpenGLContext.physics.ragdolls import quat_rotate
    mixer = figure.mixer
    rig = mixer.rig
    poses = figure.ragdoll.poses()
    rest_worlds = rig.world_matrices(*rig.rest_pose())
    bone_of_slot = {int(slot): row for row, slot in enumerate(figure.rig.slots)}
    worst, counted = 0.0, 0
    for skin, slots, _bind, mesh_slot in mixer._skin_plans:  # noqa: SLF001 the mixer's per-skin joint slots, which no public call lists
        for mesh in skin.meshes:
            drawn = np.asarray(mesh.posed_positions(), dtype='d')
            rest = np.asarray(mesh._base_positions, dtype='d')  # noqa: SLF001 the bind-pose vertices a skinned mesh keeps
            if mesh_slot >= 0:
                place = rest_worlds[mesh_slot]
                drawn = drawn @ place[:3, :3] + place[3, :3]
                rest = rest @ place[:3, :3] + place[3, :3]
            joints = np.asarray(mesh.skin_joints)[:, 0]
            for joint, slot in enumerate(slots.tolist()):
                row = bone_of_slot.get(int(slot))
                if row is None:
                    continue
                mine = joints == joint
                if not mine.any():
                    continue
                offsets = rest[mine] - rest_worlds[slot][3, :3]
                frame = np.linalg.inv(rest_worlds[slot][:3, :3])
                local = offsets @ frame
                turned = quat_rotate(np.tile(poses.orientation[row], (len(local), 1)), local)
                wanted = turned + poses.position[row]
                worst = max(worst, float(np.linalg.norm(drawn[mine] - wanted, axis=1).max()))
                counted += int(mine.sum())
    return worst, counted


def main():
    model_path, out_png = sys.argv[1], sys.argv[2]
    _setup()
    from OpenGLContext.character.model import CharacterModel
    from OpenGLContext.character.ragdoll import RagdollFigure
    from OpenGLContext.context import Context as BaseContext
    from OpenGLContext.contextdefinition import ContextDefinition
    from OpenGLContext.physics import PhysicsDefinition, Proxy
    from OpenGLContext.scenegraph.basenodes import (
        Appearance, Box, DirectionalLight, Group, Material, Shape, Transform, sceneGraph,
    )

    report = {}
    frames = []

    class RagdollDrawContext(BaseContext):
        contextDefinition = ContextDefinition(physics=PhysicsDefinition(
            mode='inline', tickHz=120.0, maxCatchUp=0.1, colliders='explicit'))
        initialPosition = (2.2, 1.6, 2.2)
        initialOrientation = (-0.3, 1.0, 0.12, 0.8)
        #: What an offscreen window system draws; a window stops at the auto-exit count.
        frameCount = FRAMES

        def OnInit(self):
            model = CharacterModel.load(model_path)
            model.play('stand')
            floor = Transform(translation=(0.0, -0.5, 0.0), children=[Shape(
                geometry=Box(size=(8.0, 1.0, 8.0)),
                appearance=Appearance(material=Material(diffuseColor=(0.4, 0.45, 0.5))))])
            self.physics.add_static(floor, proxy=Proxy.box((8.0, 1.0, 8.0)))
            self.figure = RagdollFigure(self.physics, model, mode='kinematic')
            self.play(0.25)
            self.figure.knock_down(impulse=BLOW, point=self.figure.ragdoll.bone('chest').position)
            for _ in range(round(SETTLE_SECONDS / STEP)):
                self.play(STEP)
                if self.figure.settled:
                    break
            report['settled'] = int(self.figure.settled)
            self.sg = sceneGraph(children=[
                DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=1.5),
                Group(children=[floor, model.group]),
            ])
            self.animate(self.step)

        def play(self, seconds):
            for _ in range(max(1, round(seconds / STEP))):
                self.step(STEP)
                self.physics.frame(STEP)

        def step(self, dt):
            self.figure.update(dt)
            self.figure.draw()

        def OnDraw(self, *a, **k):
            result = BaseContext.OnDraw(self, *a, **k)
            width, height = self.getViewPort()
            raw = glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE)
            frames.append(np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)[::-1].copy())
            if len(frames) == FRAMES:
                self.finish()
            return result

        def finish(self):
            meshes = [mesh for skin, *_rest in self.figure.mixer._skin_plans  # noqa: SLF001 the mixer's skins as planned
                      for mesh in skin.meshes]
            report['skin_on_gpu'] = int(all(mesh.skin_on_gpu for mesh in meshes))
            report['worst_skin_error'], report['bone_vertices'] = skin_error(self.figure)
            report['hips_height'] = float(self.figure.ragdoll.bone('hips').position[1])
            Image.fromarray(frames[-1], 'RGB').save(out_png)
            for key, value in report.items():
                print('%s=%s' % (key, value), flush=True)

    RagdollDrawContext.ContextMainLoop()


if __name__ == '__main__':
    raise SystemExit(main() or 0)
