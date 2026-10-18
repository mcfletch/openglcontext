"""X3D's layers drawn: order, depth, viewports, cameras, lights, layout and
picks, read back from a real frame"""
import numpy as np
import pytest

SIZE = (64, 64)
RED, GREEN, BLUE, BLACK = (255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 0, 0)


def glowing(colour, geometry='<Box size="4 4 4"/>', extra=''):
    """A shape lit by its own emissive colour alone"""
    red, green, blue = (value / 255.0 for value in colour)
    return ('<Shape %s><Appearance><Material diffuseColor="0 0 0" emissiveColor="%g %g %g"/>'
            '</Appearance>%s</Shape>' % (extra, red, green, blue, geometry))


def document(body):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    return Loader.loads(('<X3D version="4.0"><Scene>%s</Scene></X3D>' % body).encode(),
                        'scene.x3d')


def drawn(body, size=SIZE, frames=2):
    """The frame a document draws, top row first"""
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(document(body), size=size) as context:
        for _ in range(frames):
            context.OnDraw(force=1)
        return drawn_image(context)


def at(image, x, y):
    """The colour at window position (x, y), counted from the bottom left"""
    return tuple(int(value) for value in image[image.shape[0] - 1 - y, x])


#: Layer 0: a red box close to the camera, filling the view.
NEAR_RED = ('<Viewpoint position="0 0 10"/><Transform translation="0 0 5">%s</Transform>'
            % glowing(RED))
#: A green box far behind the red one.
FAR_GREEN = '<Transform translation="0 0 -20">%s</Transform>' % glowing(GREEN)


@pytest.mark.usefixtures('gl_context')
class TestTheStack:
    def test_a_layer_is_drawn_over_the_one_beneath_whatever_its_depth(self):
        image = drawn('<LayerSet order="0 1"><Layer>%s</Layer></LayerSet>%s'
                      % (FAR_GREEN, NEAR_RED))
        assert at(image, 32, 32) == GREEN
        assert at(image, 2, 2) == RED

    def test_the_order_puts_layer_0_on_top(self):
        image = drawn('<LayerSet order="1 0"><Layer>%s</Layer></LayerSet>%s'
                      % (FAR_GREEN, NEAR_RED))
        assert at(image, 32, 32) == RED

    def test_a_layer_left_out_of_the_order_is_not_drawn(self):
        image = drawn('<LayerSet order="0"><Layer>%s</Layer></LayerSet>%s'
                      % (FAR_GREEN, NEAR_RED))
        assert at(image, 32, 32) == RED

    def test_a_hidden_layer_is_not_drawn(self):
        image = drawn('<LayerSet order="0 1"><Layer visible="false">%s</Layer></LayerSet>%s'
                      % (FAR_GREEN, NEAR_RED))
        assert at(image, 32, 32) == RED

    def test_an_empty_order_draws_nothing(self):
        image = drawn('<LayerSet order=""><Layer>%s</Layer></LayerSet>%s'
                      % (FAR_GREEN, NEAR_RED))
        assert at(image, 32, 32) == BLACK


@pytest.mark.usefixtures('gl_context')
class TestViewports:
    def test_a_layer_is_drawn_within_its_viewport(self):
        big = '<Transform translation="0 0 -20">%s</Transform>' % glowing(
            GREEN, '<Box size="100 100 1"/>')
        image = drawn('<LayerSet order="0 1"><Layer><Viewport containerField="viewport" '
                      'clipBoundary="0.5 1 0.5 1"/>%s</Layer></LayerSet>%s' % (big, NEAR_RED))
        assert at(image, 48, 48) == GREEN
        assert at(image, 16, 16) == RED
        assert at(image, 48, 16) == RED

    def test_a_viewport_group_clips_its_children(self):
        big = '<Transform translation="0 0 -20">%s</Transform>' % glowing(
            GREEN, '<Box size="100 100 1"/>')
        image = drawn('<Viewpoint position="0 0 10"/><Viewport clipBoundary="0 0.5 0 1">%s'
                      '</Viewport>' % big)
        assert at(image, 16, 32) == GREEN
        assert at(image, 48, 32) == BLACK

    def test_a_layers_background_fills_its_viewport(self):
        image = drawn('<LayerSet order="0 1"><Layer><Viewport containerField="viewport" '
                      'clipBoundary="0 0.5 0 0.5"/><Background skyColor="0 0 1"/></Layer>'
                      '</LayerSet>%s' % NEAR_RED)
        assert at(image, 16, 16) == BLUE
        assert at(image, 48, 48) == RED


@pytest.mark.usefixtures('gl_context')
class TestCameras:
    def test_a_layer_is_seen_from_its_own_viewpoint(self):
        aside = '<Transform translation="100 0 0">%s</Transform>' % glowing(GREEN)
        image = drawn('<LayerSet order="0 1"><Layer><Viewpoint position="100 0 10"/>%s'
                      '</Layer></LayerSet><Viewpoint position="0 0 10"/>' % aside)
        assert at(image, 32, 32) == GREEN

    def test_a_layer_binding_no_viewpoint_is_seen_from_the_default_one(self):
        image = drawn('<LayerSet order="0 1"><Layer>%s</Layer></LayerSet>'
                      '<Viewpoint position="100 100 100"/>' % glowing(GREEN))
        assert at(image, 32, 32) == GREEN

    def test_navigation_moves_the_active_layers_camera_alone(self):
        from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
        small = '<Box size="2 2 2"/>'
        scene = document(
            '<LayerSet order="0 1" activeLayer="1"><Layer><Viewpoint position="0 0 10"/>'
            '<Transform translation="0 2 0">%s</Transform></Layer></LayerSet>'
            '<Viewpoint position="0 0 10"/><Transform translation="0 -2 0">%s</Transform>'
            % (glowing(GREEN, small), glowing(RED, small)))
        with scene_context(scene, size=SIZE) as context:
            context.OnDraw(force=1)
            before = drawn_image(context)
            context.platform.setPosition((50, 0, 10))
            after = drawn_image(context)
        assert (at(before, 32, 44), at(before, 32, 20)) == (GREEN, RED)
        assert (at(after, 32, 44), at(after, 32, 20)) == (BLACK, RED)


@pytest.mark.usefixtures('gl_context')
class TestLights:
    def test_a_light_lights_only_its_own_layer(self):
        lit = ('<Shape><Appearance><Material diffuseColor="1 1 1"/></Appearance>'
               '<Box size="4 4 4"/></Shape>')
        # A PointLight lights everything in its scope; X3D's global is true
        image = drawn('<NavigationInfo headlight="false"/><Viewpoint position="0 0 10"/>'
                      '<Transform translation="-3 0 0">%s</Transform>'
                      '<LayerSet order="0 1"><Layer><NavigationInfo headlight="false"/>'
                      '<PointLight location="0 0 10" radius="1000" global="true"/>'
                      '<Transform translation="3 0 0">%s</Transform></Layer></LayerSet>'
                      % (lit, lit))
        assert at(image, 20, 32) == BLACK
        assert min(at(image, 44, 32)) > 200


#: A blue HUD, 20 pixels by 10 in the bottom left corner of its view, over a
#: red box that fills the view; a TouchSensor ``HUD`` is beside it.
HUD_OVER_RED = (
    '<LayerSet order="0 1"><LayoutLayer><Layout containerField="layout" size="20 10" '
    'sizeUnits=\'"PIXEL"\' align=\'"LEFT" "BOTTOM"\' scaleMode=\'"PIXEL"\'/>'
    '<Group>%s<TouchSensor DEF="HUD"/></Group></LayoutLayer></LayerSet>%s'
    % (glowing(BLUE, '<Rectangle2D size="20 10"/>'), NEAR_RED))


@pytest.mark.usefixtures('gl_context')
class TestLayout:
    def test_a_layout_layer_places_a_hud_in_pixels(self):
        hud = glowing(BLUE, '<Rectangle2D size="20 10"/>')
        image = drawn('<LayerSet order="0 1"><LayoutLayer><Layout containerField="layout" '
                      'size="20 10" sizeUnits=\'"PIXEL"\' align=\'"LEFT" "BOTTOM"\' '
                      'scaleMode=\'"PIXEL"\'/>'
                      '%s</LayoutLayer></LayerSet>%s' % (hud, NEAR_RED))
        assert at(image, 1, 1) == BLUE
        assert at(image, 18, 8) == BLUE
        assert at(image, 22, 5) == RED
        assert at(image, 5, 12) == RED

    def test_a_screen_group_is_measured_in_pixels_at_any_distance(self):
        square = glowing(BLUE, '<Rectangle2D size="10 10"/>')
        image = drawn('<Viewpoint position="0 0 10"/><Transform translation="0 0 -50">'
                      '<ScreenGroup>%s</ScreenGroup></Transform>' % square)
        column = [at(image, 32, y) == BLUE for y in range(64)]
        assert sum(column) == 10

    def test_a_screen_group_is_placed_for_each_view(self):
        """Four views, three orthographic along the axes and one perspective:
        the square faces each camera, six pixels a side in every view"""
        from OpenGLContext.context import MultiViewContext  # noqa: PLC0415 GL
        from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL

        class Quad(MultiViewContext):
            def setupViews(self):
                self.startViews(arrangement='quad', chrome=False)

        scene = document('<Viewpoint position="0 0 10"/><ScreenGroup>%s</ScreenGroup>'
                         % glowing(BLUE, '<Rectangle2D size="6 6"/>'))
        with scene_context(scene, base=Quad, size=(128, 128)) as context:
            for _ in range(2):
                context.OnDraw(force=1)
            image = drawn_image(context)
        blue = (image[:, :, 2] > 128) & (image[:, :, 0] < 64)
        quarters = [blue[:64, :64], blue[:64, 64:], blue[64:, :64], blue[64:, 64:]]
        assert [int(quarter.sum()) for quarter in quarters] == [36] * 4

    def test_a_view_styled_without_layers_draws_the_navigated_layer_alone(self):
        """Four views; the three orthographic ones are styled without layers,
        so the HUD is in the window's own view and nowhere else"""
        import dataclasses  # noqa: PLC0415 kept with its use

        from OpenGLContext.context import MultiViewContext  # noqa: PLC0415 GL
        from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL

        class Quad(MultiViewContext):
            def setupViews(self):
                for view in self.startViews(arrangement='quad', chrome=False).views:
                    if not view.windowView:
                        view.style = dataclasses.replace(view.style, layers=False)

        scene = document(HUD_OVER_RED)
        with scene_context(scene, base=Quad, size=(128, 128)) as context:
            for _ in range(2):
                context.OnDraw(force=1)
            image = drawn_image(context)
        blue = (image[:, :, 2] > 128) & (image[:, :, 0] < 64)
        quarters = [blue[:64, :64], blue[:64, 64:], blue[64:, :64], blue[64:, 64:]]
        assert [int(quarter.sum()) for quarter in quarters] == [0, 0, 0, 200]

    def test_a_click_in_a_view_without_layers_passes_their_sensors_by(self):
        import dataclasses  # noqa: PLC0415 kept with its use

        from OpenGLContext.context import MultiViewContext  # noqa: PLC0415 GL
        from OpenGLContext.events import synthetic  # noqa: PLC0415 kept with its use
        from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL

        class Quad(MultiViewContext):
            def setupViews(self):
                views = self.startViews(arrangement='quad', chrome=False).views
                views[2].style = dataclasses.replace(views[2].style, layers=False)

        scene = document(HUD_OVER_RED)
        touch = scene.getDEF('HUD')
        # The HUD's place in the bottom left view, which has no layers, then
        # in the bottom right one, which has
        for x, expected in ((5, False), (69, True)):
            with scene_context(scene, base=Quad, size=(128, 128)) as context:
                context.OnDraw(force=1)
                for record in (
                    {'type': 'mousemove', 'buttons': [], 'x': x, 'y': 5, 'pick': True},
                    {'type': 'mousemove', 'buttons': [], 'x': x, 'y': 5, 'pick': True},
                    {'type': 'mousebutton', 'button': 0, 'state': 1, 'x': x, 'y': 5, 'pick': True},
                    {'type': 'mousebutton', 'button': 0, 'state': 0, 'x': x, 'y': 5, 'pick': True},
                ):
                    synthetic.dispatch(context, record)
                    context.OnDraw(force=1)
                for _ in range(120 if expected else 20):
                    if 'touchTime' in touch.__dict__:
                        break
                    context.OnDraw(force=1)
            assert ('touchTime' in touch.__dict__) is expected

    def test_screen_text_is_its_point_size_in_pixels(self):
        text = ('<Shape><Appearance><Material diffuseColor="0 0 0" emissiveColor="1 1 1"/>'
                '</Appearance><Text string="H"><ScreenFontStyle pointSize="30" '
                'justify="MIDDLE MIDDLE"/></Text></Shape>')
        near = drawn('<Viewpoint position="0 0 10"/><Transform translation="0 0 0">%s'
                     '</Transform>' % text)
        far = drawn('<Viewpoint position="0 0 10"/><Transform translation="0 0 -80">%s'
                    '</Transform>' % text)
        rows = [np.flatnonzero(image.max(axis=(1, 2)) > 128) for image in (near, far)]
        assert len(rows[0]) and len(rows[1])
        heights = [row[-1] - row[0] for row in rows]
        assert heights[0] == heights[1]
        assert 15 <= heights[0] <= 40


#: The ways a pick is resolved: the object-id buffer read a frame later or
#: at once, the selection render drawn for each pick point, and the
#: compatibility profile's colour-buffer selection render.
PICKING = ['deferred', 'immediate', 'drawn', 'compatibility']


@pytest.mark.usefixtures('gl_context')
@pytest.mark.parametrize('picking', PICKING)
class TestPicking:
    def click(self, scene, x, y, sensor, picking):
        from OpenGLContext.events import synthetic  # noqa: PLC0415 kept with its use
        from OpenGLContext.passes import renderpass  # noqa: PLC0415 GL
        from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
        environment = ({'OPENGLCONTEXT_PROFILE': 'compatibility'} if picking == 'compatibility'
                       else None)
        with scene_context(scene, size=SIZE, pickAsync=picking == 'deferred',
                           environment=environment) as context:
            context.OnDraw(force=1)
            renderpass.FLAT.use_mrt_selection = picking != 'drawn'
            # The immediate read is of the frame before, so the first move
            # only warms the id buffer
            for record in (
                {'type': 'mousemove', 'buttons': [], 'x': x, 'y': y, 'pick': True},
                {'type': 'mousemove', 'buttons': [], 'x': x, 'y': y, 'pick': True},
                {'type': 'mousebutton', 'button': 0, 'state': 1, 'x': x, 'y': y, 'pick': True},
                {'type': 'mousebutton', 'button': 0, 'state': 0, 'x': x, 'y': y, 'pick': True},
            ):
                synthetic.dispatch(context, record)
                context.OnDraw(force=1)
            touch = scene.getDEF(sensor)
            for _ in range(120):
                if 'touchTime' in touch.__dict__:
                    break
                context.OnDraw(force=1)
        return touch

    def scene(self, pickable='true'):
        return document(
            '<LayerSet order="0 1"><Layer pickable="%s"><Group>%s'
            '<TouchSensor DEF="HUD"/></Group></Layer></LayerSet>'
            '<Viewpoint position="0 0 10"/><Group><Transform translation="0 0 5">%s'
            '</Transform><TouchSensor DEF="WORLD"/></Group>'
            % (pickable, glowing(GREEN, '<Box size="2 2 2"/>'), glowing(RED)))

    def test_a_click_on_a_layer_reaches_its_sensor(self, picking):
        scene = self.scene()
        touch = self.click(scene, 32, 32, 'HUD', picking)
        assert 'touchTime' in touch.__dict__
        assert 'touchTime' not in scene.getDEF('WORLD').__dict__
        # The green box's face, a unit in front of its centre, seen through
        # the layer's own camera
        assert tuple(touch.hitPoint_changed)[2] == pytest.approx(1.0, abs=0.05)

    def test_a_click_beside_a_layers_geometry_reaches_the_layer_beneath(self, picking):
        scene = self.scene()
        touch = self.click(scene, 4, 4, 'WORLD', picking)
        assert 'touchTime' in touch.__dict__
        assert 'touchTime' not in scene.getDEF('HUD').__dict__
        # The red box's face, measured through layer 0's camera although the
        # layer above cleared the depth buffer there
        assert tuple(touch.hitPoint_changed)[2] == pytest.approx(7.0, abs=0.05)

    def test_a_layer_that_is_not_pickable_is_clicked_through(self, picking):
        scene = self.scene('false')
        touch = self.click(scene, 32, 32, 'WORLD', picking)
        assert 'touchTime' in touch.__dict__
        assert 'touchTime' not in scene.getDEF('HUD').__dict__
