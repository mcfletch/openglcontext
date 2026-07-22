"""The PBR pass skips re-configuring an unchanged material within a frame.

CAD assemblies (Buggy/Gearbox) submit hundreds of shapes; re-boxing and
re-uploading ~19 material uniforms for every shape dominates the frame. When
consecutive shapes share a material the whole appearance setup is skipped, while
a per-frame reset keeps material edits live. These run GL-free: with the program
handle left None the uniform setters short-circuit before any GL call.
"""
import pytest

from OpenGLContext.passes.pbrpass import PBRShaderProgram
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial


class _App:
    def __init__(self, material):
        self.material = material


def _spy(prog):
    # bind_material_block runs once per non-skipped configure_appearance; with the
    # program handle None it returns before any GL call, so this stays GL-free.
    calls = {'material': 0}
    ob = prog.bind_material_block
    prog.bind_material_block = lambda *a, **k: (calls.__setitem__('material', calls['material'] + 1), ob(*a, **k))[1]
    return calls


def _prog():
    p = PBRShaderProgram()      # not compiled -> program is None -> GL-free
    p.transmission_mode = 'off'
    return p


def test_same_material_configured_once_per_run():
    p = _prog()
    calls = _spy(p)
    m = PBRMaterial()
    ap = _App(m)
    p.reset_appearance_cache()
    for _ in range(50):
        p.configure_appearance(ap, None)
    assert calls['material'] == 1


def test_distinct_materials_each_configured():
    p = _prog()
    calls = _spy(p)
    p.reset_appearance_cache()
    for _ in range(5):
        p.configure_appearance(_App(PBRMaterial()), None)
    assert calls['material'] == 5


def test_reset_forces_reconfigure_next_frame():
    p = _prog()
    calls = _spy(p)
    m = PBRMaterial()
    ap = _App(m)
    p.reset_appearance_cache()
    p.configure_appearance(ap, None)
    p.configure_appearance(ap, None)      # skipped
    assert calls['material'] == 1
    p.reset_appearance_cache()            # new frame
    p.configure_appearance(ap, None)      # must reconfigure (edits may have landed)
    assert calls['material'] == 2


def test_transmission_mode_change_forces_reconfigure():
    p = _prog()
    calls = _spy(p)
    m = PBRMaterial()
    ap = _App(m)
    p.reset_appearance_cache()
    p.configure_appearance(ap, None)
    p.transmission_mode = 'full'          # same material, different pass mode
    p.configure_appearance(ap, None)
    assert calls['material'] == 2


def test_none_material_first_shape_still_configures():
    # The sentinel is distinct from None, so a first shape with no material
    # (VRML97 default) is not mistaken for "already configured".
    p = _prog()
    calls = _spy(p)
    p.reset_appearance_cache()
    p.configure_appearance(_App(None), None)
    assert calls['material'] == 1


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
