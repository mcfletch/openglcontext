"""Strip bookkeeping in `OpenGLContext.atlas`."""
import gc

from OpenGLContext.arrays import zeros
from OpenGLContext.atlas import AtlasManager
from OpenGLContext.texture import NumpyAdapter


def _image(width: int = 16, height: int = 16) -> NumpyAdapter:
    return NumpyAdapter(zeros((height, width, 4), 'B'))


def test_released_maps_leave_the_strip_empty():
    """Every released map is dropped, including several released together.

    The collector clears a cycle's weak references before it runs any of their
    callbacks, so a callback can see more than one of them dead at once.
    """
    manager = AtlasManager(max_size=256)
    maps = [manager.add(_image()) for _ in range(4)]
    strip = manager.components[4][0].strips[0]
    assert len(strip.maps) == 4

    holder = {'maps': maps}
    holder['self'] = holder          # a cycle, so they die as one group
    del maps, holder
    gc.collect()

    assert strip.maps == []


def test_space_is_reused_after_a_release():
    manager = AtlasManager(max_size=256)
    first = manager.add(_image())
    assert first.offset == (0, 0)
    del first
    gc.collect()
    second = manager.add(_image())
    assert second.offset == (0, 0)


def test_an_image_larger_than_the_child_limit_is_refused():
    import pytest

    from OpenGLContext.atlas import AtlasError

    manager = AtlasManager(max_size=256, max_child_size=32)
    with pytest.raises(AtlasError):
        manager.add(_image(64, 8))
    with pytest.raises(AtlasError):
        manager.add(_image(8, 64))


def test_the_driver_limit_caps_the_atlas_size(gl_context):
    """With no size asked for, the atlas is as big as the driver allows."""
    manager = AtlasManager(max_size=None)
    size = manager.calculate_max_size()
    assert isinstance(size, int)
    assert 0 < size <= AtlasManager._MAX_MAX_SIZE
