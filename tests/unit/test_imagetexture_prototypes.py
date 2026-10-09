"""An ImageTexture in a prototype's body, read again for each instance"""


def test_a_prototype_instances_image_texture_loads_its_image(tmp_path):
    """Each instance's body is a copy of the prototype's, which reads its image too"""
    from PIL import Image  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders import background  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    Image.new('RGB', (4, 4), (0, 128, 0)).save(str(tmp_path / 'green.png'))
    path = tmp_path / 'proto.x3d'
    path.write_text('''<X3D version="4.0"><Scene>
      <ProtoDeclare name="Tile"><ProtoBody><Shape><Appearance>
        <ImageTexture url='"green.png"'/></Appearance><Box/></Shape></ProtoBody></ProtoDeclare>
      <ProtoInstance name="Tile"/><ProtoInstance name="Tile"/>
    </Scene></X3D>''')
    scene = Loader.load(str(path))
    assert background.wait_for_idle(20.0)
    textures = [instance.renderedChildren()[0].appearance.texture for instance in scene.children]
    assert textures[0] is not textures[1]
    for texture in textures:
        assert texture.image is not None
        assert texture.image.size == (4, 4)


def test_every_texture_with_a_url_reads_it_and_a_prototype_copy_reads_its_own(tmp_path):
    """ImageTexture3D and ImageCubeMapTexture read their url as ImageTexture does"""
    import numpy as np  # noqa: PLC0415 kept with its use
    from PIL import Image  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders import background  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.textureimages import nrrd_bytes  # noqa: PLC0415 kept with its use
    (tmp_path / 'block.nrrd').write_bytes(nrrd_bytes(np.full((2, 3, 4), 7, np.uint8)))
    Image.new('RGB', (8, 6), (0, 0, 255)).save(str(tmp_path / 'cross.png'))
    path = tmp_path / 'proto.x3d'
    path.write_text('''<X3D version="4.0"><Scene>
      <ProtoDeclare name="Tile"><ProtoBody><Shape><Appearance>
        <ImageTexture3D url='"block.nrrd"'/></Appearance><Box/></Shape></ProtoBody></ProtoDeclare>
      <ProtoInstance name="Tile"/><ProtoInstance name="Tile"/>
      <Shape><Appearance><ImageCubeMapTexture url='"cross.png"'/></Appearance><Box/></Shape>
    </Scene></X3D>''')
    scene = Loader.load(str(path))
    assert background.wait_for_idle(20.0)
    volumes = [instance.renderedChildren()[0].appearance.texture for instance in scene.children[:2]]
    assert volumes[0] is not volumes[1]
    for volume in volumes:
        assert volume.volumeData().shape == (2, 3, 4, 1)
    cube = scene.children[2].appearance.texture
    assert cube.faces is not None
