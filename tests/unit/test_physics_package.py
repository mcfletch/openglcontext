"""What a game author imports from ``OpenGLContext.physics`` without reaching into omi_physics."""
import subprocess
import sys

import pytest

import OpenGLContext.physics as physics


@pytest.mark.parametrize('name, home', [
    ('Physics', 'OpenGLContext.physics.service'),
    ('Body', 'OpenGLContext.physics.body'),
    ('Character', 'OpenGLContext.physics.character'),
    ('Proxy', 'OpenGLContext.physics.proxy'),
    ('Joint', 'OpenGLContext.physics.joints'),
    ('PhysicsDefinition', 'OpenGLContext.physics.settings'),
    ('CharacterCapabilities', 'omi_physics.character'),
    ('Material', 'omi_physics.model'),
    ('CollisionFilter', 'omi_physics.model'),
])
def test_each_name_is_the_class_of_its_home_module(name, home):
    module = __import__(home, fromlist=[name])
    assert getattr(physics, name) is getattr(module, name)
    assert name in physics.__all__


def test_an_unknown_name_raises_attribute_error():
    with pytest.raises(AttributeError):
        physics.NoSuchThing  # noqa: B018 the lookup is what is tested


def test_importing_the_package_imports_none_of_the_service():
    code = ('import sys, OpenGLContext.physics; '
            'print("OpenGLContext.physics.service" in sys.modules)')
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                         check=True)
    assert out.stdout.strip() == 'False'
