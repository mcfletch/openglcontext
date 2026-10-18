Basis Universal fixtures for tests/unit/test_basisu.py and test_basisu_gl.py.

Written by the basisu encoder of basis_universal v2_50 from flat-colour images.
The first four are copies of opengl_basisu's tests/fixtures, where
tools/make_fixtures.py lists the source images and encoder flags:

  etc1s_srgb_mips.ktx2  ETC1S, sRGB, 16x16 quadrants (red, green / blue, white), 5 levels
  uastc_rgba.ktx2       UASTC, linear, the same quadrants with white at alpha 64
  etc1s_cube.ktx2       ETC1S cube map, 8x8 faces: red, cyan, green, magenta, blue, yellow
  etc1s_rgba.basis      ETC1S .basis file of the uastc_rgba.ktx2 image

  uastc_array.ktx2      UASTC 2D array of three 8x8 layers: red, green, blue
                        basisu -ktx2 -uastc -linear -tex_type 2darray
                               -file layer0.png -file layer1.png -file layer2.png
  uastc_hdr.ktx2        UASTC HDR 4x4, 8x8 red; a codec with no 8-bit target (opengl_basisu's)
