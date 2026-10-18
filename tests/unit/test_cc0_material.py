"""A photographic material from the cached ambientCG maps, or None."""
import numpy as np
import pytest
from PIL import Image

from OpenGLContext.contentpacks import catalog, fetch
from OpenGLContext.contentpacks import store as content_store
from OpenGLContext.loaders import cc0

pytestmark = pytest.mark.usefixtures('no_installed_content')


@pytest.fixture
def maps(tmp_path, monkeypatch):
    monkeypatch.setattr(cc0, 'cache_dir', lambda: str(tmp_path))
    paths = {}
    for kind in ('color', 'normal', 'roughness'):
        path = tmp_path / (kind + '.jpg')
        Image.fromarray(np.full((8, 8, 3), 90, np.uint8), 'RGB').save(path)
        paths[kind] = str(path)
    return paths


def test_the_maps_become_a_material_wearing_them(monkeypatch, maps):
    monkeypatch.setattr(cc0, 'try_material', lambda name, resolution='1K': maps)
    material = cc0.physical_material('rock')
    assert material.baseTexture and material.normalTexture and material.metallicRoughnessTexture
    assert material.metallic == 0.0
    assert tuple(material.baseColor) == (1.0, 1.0, 1.0)


def test_a_tint_multiplies_the_colour(monkeypatch, maps):
    monkeypatch.setattr(cc0, 'try_material', lambda name, resolution='1K': maps)
    assert tuple(cc0.physical_material('bark', tint=(0.5, 0.4, 0.3)).baseColor) == pytest.approx(
        (0.5, 0.4, 0.3))


def test_with_no_roughness_map_the_material_is_rough(monkeypatch, maps):
    del maps['roughness']
    monkeypatch.setattr(cc0, 'try_material', lambda name, resolution='1K': maps)
    material = cc0.physical_material('rock')
    assert not material.metallicRoughnessTexture and material.roughness == pytest.approx(0.9)


@pytest.mark.parametrize('missing', ['color', 'normal'])
def test_a_set_missing_its_colour_or_normal_map_is_not_used(monkeypatch, maps, missing):
    del maps[missing]
    monkeypatch.setattr(cc0, 'try_material', lambda name, resolution='1K': maps)
    assert cc0.physical_material('rock') is None


def test_offline_there_is_no_material(monkeypatch):
    monkeypatch.setattr(cc0, 'try_material', lambda name, resolution='1K': None)
    assert cc0.physical_material('rock') is None


def test_the_image_files_are_closed(monkeypatch, maps):
    opened = []
    real = Image.open

    def spy(path, *args, **kwargs):
        picture = real(path, *args, **kwargs)
        opened.append(picture)
        return picture

    monkeypatch.setattr(Image, 'open', spy)
    monkeypatch.setattr(cc0, 'try_material', lambda name, resolution='1K': maps)
    cc0.physical_material('rock')
    assert opened and all(picture.fp is None for picture in opened)


def test_a_map_outside_the_cache_is_refused(monkeypatch, maps, tmp_path):
    outside = tmp_path.parent / 'elsewhere.jpg'
    Image.fromarray(np.full((8, 8, 3), 90, np.uint8), 'RGB').save(outside)
    maps['color'] = str(outside)
    monkeypatch.setattr(cc0, 'try_material', lambda name, resolution='1K': maps)
    with pytest.raises(IOError, match='leads out of'):
        cc0.physical_material('rock')


# -- the texture pack ---------------------------------------------------------------

@pytest.fixture
def pack(tmp_path, monkeypatch):
    """An installed texture pack holding one material, and no cache."""
    root = tmp_path / 'pack'
    where = root / cc0.PACK_FOLDER / 'Rock030_1K'
    where.mkdir(parents=True)
    for kind in ('color', 'normal', 'roughness'):
        Image.fromarray(np.full((8, 8, 3), 60, np.uint8), 'RGB').save(where / (kind + '.jpg'))
    monkeypatch.setattr(cc0, 'pack_directory', lambda: str(root))
    monkeypatch.setattr(cc0, 'cache_dir', lambda: str(tmp_path / 'cache'))
    monkeypatch.setattr(cc0, '_download', lambda *a, **k: pytest.fail('reached ambientCG'))
    return root


def test_a_material_in_the_pack_is_read_from_it_with_no_download(pack):
    found = cc0.material('rock')
    assert found['color'].startswith(str(pack)) and set(found) == {'color', 'normal', 'roughness'}


def test_a_photographic_material_is_made_from_the_pack(pack):
    material = cc0.physical_material('rock')
    assert material.baseTexture and material.normalTexture


def test_a_material_the_pack_does_not_hold_is_fetched_as_before(pack, monkeypatch):
    monkeypatch.setattr(cc0, '_download', lambda *a, **k: (_ for _ in ()).throw(OSError('offline')))
    assert cc0.try_material('Bark012') is None


def test_every_catalog_material_has_a_name_the_pack_can_hold():
    assert set(cc0.CATALOG.values()) >= {'Rock030', 'Bark012', 'Ground080'}
    assert all(asset.isalnum() for asset in cc0.CATALOG.values())


def test_there_is_no_pack_directory_where_none_is_installed(tmp_path, monkeypatch):
    from OpenGLContext.contentpacks import store as content_store
    monkeypatch.setenv('OPENGLCONTEXT_CONTENT', str(tmp_path))
    monkeypatch.setattr(content_store, '_from_environment', lambda: [])
    assert cc0.pack_directory() is None or isinstance(cc0.pack_directory(), str)


@pytest.fixture
def empty_store(tmp_path, monkeypatch):
    """A content store holding nothing, so no pack is installed."""
    monkeypatch.setenv('OPENGLCONTEXT_CONTENT', str(tmp_path))
    monkeypatch.setattr(content_store, '_from_environment', lambda: [])


def test_the_pack_is_not_fetched_where_the_registry_does_not_offer_it(empty_store, monkeypatch):
    monkeypatch.setattr(catalog, 'load', lambda path: [])
    assert cc0.ensure_pack(consent=lambda packs: pytest.fail('asked')) is False


def test_the_pack_is_not_fetched_when_consent_is_declined(empty_store, monkeypatch):
    fetched = []
    monkeypatch.setattr(fetch, 'fetch_pack', lambda pack, store: fetched.append(pack))
    asked = []

    def decline(packs):
        asked.extend(packs)
        return False

    assert cc0.ensure_pack(consent=decline) is False
    assert [pack.key for pack in asked] == [cc0.PACK] and not fetched


def test_the_pack_is_a_need_until_it_is_installed(empty_store):
    from OpenGLContext.contentpacks.application import Need
    needs = cc0.pack_needs()
    assert [type(need) for need in needs] == [Need]
    assert needs[0].pack.key == cc0.PACK and not needs[0].present()


def test_no_need_where_the_registry_does_not_offer_the_pack(empty_store, monkeypatch):
    monkeypatch.setattr(catalog, 'load', lambda path: [])
    assert cc0.pack_needs() == []
