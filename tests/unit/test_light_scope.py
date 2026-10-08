"""A light's scope: what it lights.

X3D and VRML97: a DirectionalLight whose `global` is false lights only the
descendants of its parent grouping node; a global light lights everything.
The engine's own DirectionalLight made in code is global; one a document
builds is scoped unless the document says otherwise. A draw's `lightsOff`
mask has a bit for each bound light out of its scope.
"""
import pytest

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.passes import lightscope
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.nodepath import NodePath
from OpenGLContext.testing.scenes import drawn_image, scene_context


def path(*nodes):
    return NodePath(list(nodes))


def scoped_light():
    light = basenodes.DirectionalLight()
    setattr(light, 'global', False)
    return light


class TestGlobal:
    def test_a_directional_light_made_in_code_is_global(self):
        assert lightscope.is_global(basenodes.DirectionalLight())

    def test_a_documents_directional_light_is_scoped(self):
        scene = Loader.loads(b'<X3D version="4.0"><Scene><DirectionalLight/></Scene></X3D>',
                             'scene.x3d')
        assert not lightscope.is_global(scene.children[0])

    def test_a_vrml97_worlds_directional_light_is_scoped(self):
        scene = Loader.loads(b'#VRML V2.0 utf8\nDirectionalLight { }\n', 'world.wrl')
        assert not lightscope.is_global(scene.children[0])

    def test_point_and_spot_lights_are_global(self):
        assert lightscope.is_global(basenodes.PointLight())
        assert lightscope.is_global(basenodes.SpotLight())


class TestTheMask:
    def setup_method(self):
        self.root = basenodes.Group()
        self.room = basenodes.Group()
        self.hall = basenodes.Group()
        self.lamp = scoped_light()
        self.sun = basenodes.DirectionalLight()
        self.lights = lightscope.scoped_lights([
            path(self.root, self.sun), path(self.root, self.room, self.lamp)])

    def test_only_scoped_lights_are_kept(self):
        assert [slot for slot, _parents in self.lights] == [1]

    def test_a_shape_under_the_lights_group_is_lit_by_it(self):
        shape = basenodes.Shape()
        assert lightscope.scope_mask(self.lights, path(self.root, self.room, shape)) == 0

    def test_a_shape_elsewhere_is_not(self):
        shape = basenodes.Shape()
        assert lightscope.scope_mask(self.lights, path(self.root, self.hall, shape)) == 0b10

    def test_a_shape_deeper_under_the_group_is_lit(self):
        shape = basenodes.Shape()
        deeper = basenodes.Transform()
        assert lightscope.scope_mask(
            self.lights, path(self.root, self.room, deeper, shape)) == 0

    def test_no_scoped_lights_is_no_mask(self):
        assert lightscope.scoped_lights([path(self.root, self.sun)]) == ()


class TestTheMasksKept:
    """A frame's masks are worked out once a path, and kept while the same
    lights are scoped"""

    def setup_method(self):
        self.root, self.room, self.hall = basenodes.Group(), basenodes.Group(), basenodes.Group()
        self.lamp = scoped_light()
        self.bound = [path(self.root, self.room, self.lamp)]

    def counted(self, monkeypatch):
        worked = []
        real = lightscope.scope_mask

        def counting(scoped, at):
            worked.append(at)
            return real(scoped, at)
        monkeypatch.setattr(lightscope, 'scope_mask', counting)
        return worked

    def test_a_path_is_worked_out_once(self, monkeypatch):
        worked = self.counted(monkeypatch)
        masks = lightscope.ScopeMasks().following(lightscope.scoped_lights(self.bound))
        outside = path(self.root, self.hall, basenodes.Shape())
        assert [masks.mask(outside) for _draw in range(3)] == [1, 1, 1]
        assert len(worked) == 1

    def test_the_same_lights_next_frame_keep_the_masks(self, monkeypatch):
        worked = self.counted(monkeypatch)
        masks = lightscope.ScopeMasks().following(lightscope.scoped_lights(self.bound))
        outside = path(self.root, self.hall, basenodes.Shape())
        masks.mask(outside)
        again = masks.following(lightscope.scoped_lights(self.bound))
        assert again is masks
        assert again.mask(outside) == 1 and len(worked) == 1

    def test_other_lights_work_them_out_again(self):
        masks = lightscope.ScopeMasks().following(lightscope.scoped_lights(self.bound))
        inside = path(self.root, self.room, basenodes.Shape())
        assert masks.mask(inside) == 0
        other = scoped_light()
        moved = masks.following(lightscope.scoped_lights([path(self.root, self.hall, other)]))
        assert moved.mask(inside) == 1

    def test_no_scoped_lights_is_no_mask(self):
        masks = lightscope.ScopeMasks()
        assert not masks
        assert masks.mask(path(self.root, basenodes.Shape())) == 0


def _centre(context):
    image = drawn_image(context)
    h, w = image.shape[:2]
    return image[h // 2, w // 2].astype(int)


@pytest.mark.parametrize('inside, lit', [(True, True), (False, False)])
def test_a_scoped_light_lights_only_its_siblings(gl_context, inside, lit):
    light = scoped_light()
    light.direction = (0, 0, -1)
    box = basenodes.Shape(geometry=basenodes.Box(size=(3, 3, 3)),
                          appearance=basenodes.Appearance(material=basenodes.Material(
                              diffuseColor=(1, 1, 1))))
    other = basenodes.DirectionalLight(direction=(0, 0, -1), intensity=0.0)
    group = basenodes.Group(children=[light, box] if inside else [light])
    children = [basenodes.Viewpoint(position=(0, 0, 8)), basenodes.NavigationInfo(headlight=False),
                other, group] + ([] if inside else [box])
    with scene_context(children, environment={'OPENGLCONTEXT_IBL': 'off'}) as context:
        context.OnDraw(force=1)
        brightness = _centre(context).sum()
    assert bool(brightness > 150) == lit


def test_shapes_batched_under_different_scoped_lights_are_each_lit(gl_context):
    """One Shape USEd under two groups, each with its own scoped light: the
    copies are drawn in separate batches, each lit by its own light"""
    scene = Loader.loads(b'''<X3D version="4.0"><Scene><Viewpoint position="0 0 30"/>
      <NavigationInfo headlight="false"/>
      <Transform translation="-5 0 0"><DirectionalLight direction="0 0 -1"/>
        <Transform DEF="Row"><Shape DEF="Ball"><Appearance><Material/></Appearance><Sphere/>
          </Shape><Transform translation="0 3 0"><Shape USE="Ball"/></Transform>
          <Transform translation="0 -3 0"><Shape USE="Ball"/></Transform></Transform></Transform>
      <Transform translation="5 0 0"><DirectionalLight direction="0 0 -1"/>
        <Transform USE="Row"/></Transform>
    </Scene></X3D>''', 'scene.x3d')
    with scene_context(scene, size=(96, 64)) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
    columns = image[:, :, 0].max(axis=0)
    assert columns[:48].max() > 150 and columns[48:].max() > 150, columns
