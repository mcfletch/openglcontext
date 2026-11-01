"""A knocked-down ragdoll figure is drawn where its bones lie, in a window and offscreen."""
import os
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

from OpenGLContext.testing.gl_env import gl_subprocess_env
from OpenGLContext.testing.paths import tests_root
from tests.unit._character_assets import ragdoll_figure_glb

HARNESS = os.path.join(str(tests_root(__file__)), 'helpers', '_ragdoll_draw_harness.py')


def _draw(model, out, backend, gpu):
    """Run the harness; its report and the frame it read back."""
    overrides = {'OPENGLCONTEXT_BACKEND': backend, 'OPENGLCONTEXT_GPU_SKINNING': '1' if gpu else '0'}
    if os.environ.get('PYTHONPATH'):
        overrides['PYTHONPATH'] = os.environ['PYTHONPATH']
    result = subprocess.run([sys.executable, HARNESS, str(model), str(out)], capture_output=True,
                            text=True, timeout=300, env=gl_subprocess_env(**overrides))
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    report = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    assert out.exists(), result.stdout[-4000:] + result.stderr[-4000:]
    return report, np.asarray(Image.open(out).convert('RGB')).astype(np.int16)


@pytest.mark.parametrize('backend', ['glfw', 'offscreen'])
def test_a_settled_figure_is_drawn_where_its_bones_lie(tmp_path, backend):
    """Settled on the floor, every skin vertex sits on its bone's body, and the
    shader draws the same picture as the CPU deform."""
    model = tmp_path / 'figure.glb'
    model.write_bytes(ragdoll_figure_glb())
    shader, on_gpu = _draw(model, tmp_path / 'gpu.png', backend, gpu=True)
    cpu, on_cpu = _draw(model, tmp_path / 'cpu.png', backend, gpu=False)
    for report in (shader, cpu):
        assert report['settled'] == '1'
        assert float(report['hips_height']) < 0.2, 'the figure is not lying down'
        assert int(report['bone_vertices']) > 300
        assert float(report['worst_skin_error']) < 1e-3, report
    assert shader['skin_on_gpu'] == '1' and cpu['skin_on_gpu'] == '0'
    lit = on_cpu.max(axis=2) > 150
    assert lit.mean() > 0.002, 'the figure is not in the frame'
    differing = (np.abs(on_gpu - on_cpu).max(axis=2) > 8).mean()
    assert differing < 0.005
