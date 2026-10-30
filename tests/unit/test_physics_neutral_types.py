"""The physics package's own types, their conversion to the engine underneath, and the API contract."""
import dataclasses
import enum
import inspect
import types
import typing

import numpy as np
import pytest

import OpenGLContext.physics as physics_package
from OpenGLContext.physics import (
    Body, Character, CharacterCapabilities, CharacterState, CollisionFilter, Joint, Material,
    Physics, PhysicsDefinition, Proxy,
)
from OpenGLContext.physics import omi_adapter
from OpenGLContext.physics.settings import PhysicsDefinition as SettingsDefinition
from OpenGLContext.physics.zones import Box, Sphere


# -- the types are the package's own --------------------------------------

@pytest.mark.parametrize('cls', [CharacterCapabilities, CharacterState, CollisionFilter, Material])
def test_the_exported_types_are_defined_in_opengl_context(cls):
    assert cls.__module__.startswith('OpenGLContext.physics')


def test_material_has_the_omi_field_names_and_defaults():
    import omi_physics.model as model

    ours = {f.name: f.default for f in dataclasses.fields(Material)}
    theirs = {f.name: f.default for f in dataclasses.fields(model.Material)}
    assert ours == theirs


def test_collision_filter_has_the_omi_field_names_and_defaults():
    import omi_physics.model as model

    ours = {f.name: f.default for f in dataclasses.fields(CollisionFilter)}
    theirs = {f.name: f.default for f in dataclasses.fields(model.CollisionFilter)}
    assert ours == theirs


def test_character_capabilities_have_the_omi_field_names_and_defaults():
    from omi_physics import character

    ours = {f.name: f.default for f in dataclasses.fields(CharacterCapabilities)}
    theirs = {f.name: f.default for f in dataclasses.fields(character.CharacterCapabilities)}
    assert ours == theirs


def test_character_state_has_the_omi_members():
    from omi_physics import character

    assert {(m.name, m.value) for m in CharacterState} == {
        (m.name, m.value) for m in character.CharacterState}


# -- conversions -----------------------------------------------------------

def test_a_material_converts_to_the_engine_and_back():
    given = Material(staticFriction=0.9, dynamicFriction=0.7, restitution=0.3,
                     frictionCombine='minimum')
    made = omi_adapter.omi_material(given)
    assert type(made).__module__ == 'omi_physics.model'
    assert (made.staticFriction, made.dynamicFriction, made.restitution, made.frictionCombine) == (
        0.9, 0.7, 0.3, 'minimum')
    assert omi_adapter.material_from_omi(made) == given


def test_a_collision_filter_converts_and_keeps_its_rule():
    balls = CollisionFilter(collisionSystems=('ball',))
    shards = CollisionFilter(collisionSystems=('shard',), notCollideWithSystems=('ball',))
    assert not balls.collides_with(shards)
    assert balls.collides_with(balls)
    made = omi_adapter.omi_filter(shards)
    assert type(made).__module__ == 'omi_physics.model'
    assert not omi_adapter.omi_filter(balls).collides_with(made)


def test_capabilities_convert_to_the_engine():
    caps = CharacterCapabilities(radius=0.4, standHeight=1.6, jumpHeight=2.0)
    made = omi_adapter.omi_capabilities(caps)
    assert type(made).__module__ == 'omi_physics.character'
    assert (made.radius, made.standHeight, made.jumpHeight) == (0.4, 1.6, 2.0)


def test_the_engine_state_converts_to_the_neutral_state():
    from omi_physics import character

    for member in character.CharacterState:
        assert omi_adapter.character_state(member) is CharacterState[member.name]


def test_coerce_takes_an_object_with_the_same_fields():
    from omi_physics import character

    given = character.CharacterCapabilities(radius=0.25)
    made = CharacterCapabilities.coerce(given)
    assert isinstance(made, CharacterCapabilities) and made.radius == 0.25
    assert CharacterCapabilities.coerce(None) == CharacterCapabilities()
    assert Material.coerce(Material(restitution=0.5)).restitution == 0.5


@pytest.mark.parametrize('proxy, kind, names', [
    (Proxy.box((1, 2, 3)), 'box', {'size'}),
    (Proxy.sphere(0.25), 'sphere', {'radius'}),
    (Proxy.capsule(1.0, 0.3), 'capsule', {'height', 'radius'}),
    (Proxy.cylinder(2.0, 0.5), 'cylinder', {'height', 'radius', 'radius_top'}),
    (Proxy.convex(np.eye(3)), 'convex', {'points'}),
    (Proxy.trimesh(np.eye(3), [[0, 1, 2]]), 'trimesh', {'points', 'indices'}),
])
def test_a_proxy_is_a_kind_and_its_parameters(proxy, kind, names):
    assert proxy.kind == kind
    assert set(proxy.params) == names
    shape = omi_adapter.omi_shape(proxy)
    assert shape.type == kind
    assert omi_adapter.omi_shape(proxy) is shape        # converted once


def test_a_proxy_made_from_an_engine_shape_reads_back_its_parameters():
    from omi_physics import model

    proxy = omi_adapter.proxy_from_shape(model.Shape.box((2.0, 4.0, 6.0)))
    assert proxy.kind == 'box' and tuple(proxy.params['size']) == (2.0, 4.0, 6.0)
    assert proxy.volume() == pytest.approx(48.0)


def test_a_compound_proxy_lists_its_parts_as_proxies():
    cooked = Proxy.from_mesh(*_l_shape(), strategy='auto', dynamic=True)
    if cooked.kind == 'compound':
        parts = cooked.params['parts']
        assert all(isinstance(part[0], Proxy) for part in parts)


def _l_shape():
    points = np.array([[0, 0, 0], [2, 0, 0], [2, 1, 0], [1, 1, 0], [1, 2, 0], [0, 2, 0],
                       [0, 0, 1], [2, 0, 1], [2, 1, 1], [1, 1, 1], [1, 2, 1], [0, 2, 1]], 'd')
    indices = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 5],
                        [6, 8, 7], [6, 9, 8], [6, 10, 9], [6, 11, 10]])
    return points, indices


def test_zone_regions_are_the_packages_own():
    box, sphere = Box(center=(0, 1, 0), size=(2, 2, 2)), Sphere(center=(0, 0, 0), radius=1.0)
    assert box.contains((0.5, 1.5, 0.5)) and not box.contains((2.0, 1.0, 0.0))
    assert sphere.contains((0.5, 0.0, 0.0)) and not sphere.contains((1.5, 0.0, 0.0))
    for region in (box, sphere):
        assert not any(base.__module__.startswith('omi_physics') for base in type(region).__mro__)


# -- the contract: no engine type in the public API ------------------------

def _is_omi(value):
    if isinstance(value, types.ModuleType):
        return value.__name__.startswith('omi_physics')
    module = getattr(type(value), '__module__', '') or ''
    if module.startswith('omi_physics'):
        return True
    if isinstance(value, type):
        return (value.__module__ or '').startswith('omi_physics')
    return False


def _mentions_omi(annotation):
    if annotation is inspect.Parameter.empty:
        return False
    if isinstance(annotation, str):
        return 'omi' in annotation
    if _is_omi(annotation):
        return True
    return any(_mentions_omi(arg) for arg in typing.get_args(annotation))


def _public_members(cls):
    for name, value in inspect.getmembers(cls):
        if name.startswith('_'):
            continue
        yield name, value


@pytest.mark.parametrize('cls', [Physics, Body, Character, Joint, Proxy, PhysicsDefinition])
def test_no_public_signature_names_an_engine_type(cls):
    for name, member in _public_members(cls):
        function = member.fget if isinstance(member, property) else member
        if not callable(function):
            assert not _is_omi(member), '%s.%s is %r' % (cls.__name__, name, member)
            continue
        try:
            signature = inspect.signature(function)
        except (TypeError, ValueError):
            continue
        assert not _mentions_omi(signature.return_annotation), '%s.%s returns omi' % (cls.__name__, name)
        for parameter in signature.parameters.values():
            assert not _mentions_omi(parameter.annotation), '%s.%s(%s)' % (
                cls.__name__, name, parameter.name)
            assert not _is_omi(parameter.default), '%s.%s(%s=)' % (cls.__name__, name, parameter.name)


def test_no_name_the_package_exports_is_an_engine_object():
    for name in physics_package.__all__:
        value = getattr(physics_package, name)
        assert not _is_omi(value), name


def test_the_definition_is_the_settings_node():
    assert PhysicsDefinition is SettingsDefinition


def _service_attributes(service):
    character = service.add_character(position=(0, 0, 0))
    body = service.add_dynamic(None, proxy=Proxy.sphere(0.5), translation=(0, 2, 0))
    joint = service.add_ball(body, anchor=(0, 3, 0))
    service.frame(0.01)
    for owner in (service, character, body, joint, body.proxy):
        for name in dir(type(owner)):
            if name.startswith('_') or name in DEPRECATED.get(type(owner).__name__, ()):
                continue
            yield owner, name


#: The deprecated aliases kept for one step, by the class that has them.
DEPRECATED = {'Physics': ('world', 'backend', 'slot_of', 'body_at', 'index_of', 'run', 'BACKENDS'),
              'Character': ('controller',), 'Proxy': ('shape',)}


@pytest.mark.parametrize('mode', ['inline', 'thread'])
def test_no_public_attribute_value_is_an_engine_object(mode):
    service = Physics(PhysicsDefinition(mode=mode))
    try:
        for owner, name in _service_attributes(service):
            try:
                value = getattr(owner, name)
            except AttributeError:      # a reading this kind of joint does not have
                continue
            if callable(value) and not isinstance(value, (enum.Enum,)):
                continue
            assert not _is_omi(value), '%s.%s is %r' % (type(owner).__name__, name, value)
            if isinstance(value, (tuple, list)):
                assert not any(_is_omi(item) for item in value), '%s.%s' % (type(owner).__name__, name)
        assert not _is_omi(service.materials.get('wood').material)
    finally:
        service.close()


def test_the_test_inspection_helper_is_not_public():
    assert 'inspect' not in physics_package.__all__
    with pytest.raises(AttributeError):
        physics_package.inspect  # noqa: B018 the attribute access is the test
