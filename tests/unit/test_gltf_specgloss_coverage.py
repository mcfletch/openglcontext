"""Coverage tests for the per-pixel spec/gloss -> metallic/roughness converter.

Exercise the ``as_array`` helper's two uncovered edges: a missing image (filled
with a constant) and a mismatched-size image (resized to the common resolution).
"""
import numpy as np
import pytest

Image = pytest.importorskip("PIL.Image")

from OpenGLContext.loaders.gltf import specular_glossiness as sg  # noqa: E402


class TestSpecGlossTextureConversion:
    def test_missing_diffuse_is_filled_and_sizes_reconciled(self):
        # No diffuse image (defaults to a constant fill) plus a spec/gloss image at
        # a different resolution than the (absent) diffuse forces both the None-fill
        # and the resize path; the outputs match the larger source resolution.
        sg_pil = Image.new('RGBA', (4, 2), (200, 200, 200, 255))
        base_img, mr_img = sg._specgloss_textures_to_metalrough(
            None, sg_pil, diffuse_factor=[1, 1, 1, 1],
            spec_factor=[1, 1, 1, 1], gloss_factor=1.0)
        assert base_img.size == (4, 2)
        assert mr_img.size == (4, 2)

    def test_diffuse_larger_resizes_specgloss(self):
        # Diffuse is bigger than spec/gloss -> the smaller spec/gloss is resized up
        # to the common (4x4) resolution before per-pixel conversion.
        diffuse = Image.new('RGBA', (4, 4), (128, 64, 32, 255))
        sg_pil = Image.new('RGBA', (2, 2), (180, 180, 180, 255))
        base_img, mr_img = sg._specgloss_textures_to_metalrough(
            diffuse, sg_pil, diffuse_factor=[1, 1, 1, 1],
            spec_factor=[1, 1, 1, 1], gloss_factor=0.5)
        assert base_img.size == (4, 4) and mr_img.size == (4, 4)
        # roughness = 1 - gloss(0.5*0.5 authored...) is packed into the green channel;
        # it must be a real value, not all-zero.
        mr = np.asarray(mr_img)
        assert mr[..., 1].any()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
