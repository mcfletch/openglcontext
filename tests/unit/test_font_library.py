"""X3D's FontLibrary: a font file a document's FontStyles may name (scenegraph.text.fontlibrary)"""
import numpy as np
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from vrml.x3d import loadsensor

from OpenGLContext.loaders import background
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph.text import fontlibrary, pillowtext
from OpenGLContext.scenegraph.text.fontprovider import TTFFontProvider

PATIENCE = 30.0


def block_font(family='Blockish Test', weight=400, italic=False):
    """A TrueType font whose every letter is a full square of ink"""
    builder = FontBuilder(1000, isTTF=True)
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    order = ['.notdef', 'space', *letters]
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({32: 'space', **{ord(letter): letter for letter in letters}})
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((50, 700))
    pen.lineTo((650, 700))
    pen.lineTo((650, 0))
    pen.closePath()
    square = pen.glyph()
    empty = TTGlyphPen(None).glyph()
    builder.setupGlyf({'.notdef': empty, 'space': empty,
                       **{letter: square for letter in letters}})
    builder.setupHorizontalMetrics({name: (700, 50) for name in order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    style = 'Italic' if italic else 'Regular'
    builder.setupNameTable({'familyName': family, 'styleName': style})
    builder.setupOS2(usWeightClass=weight, fsSelection=0x01 if italic else 0x40,
                     sTypoAscender=800, sTypoDescender=-200, usWinAscent=800,
                     usWinDescent=200)
    builder.setupPost()
    return builder


def write_font(path, **named):
    block_font(**named).save(str(path))
    return path


def delivered():
    """Wait for the loader pool, and make the calls it queued for any open context"""
    from OpenGLContext.context import Context  # noqa: PLC0415 kept with its use
    assert background.wait_for_idle(PATIENCE)
    for reference in Context.allContexts:
        found = reference()
        if found is not None:
            found.renderQueue.run()


def document(tmp_path, library, style='"Fancy" "SANS"', string='"Hi"'):
    text = ('<Shape><Text string=\'%s\'><FontStyle DEF="STYLE" family=\'%s\'/></Text>'
            '</Shape>' % (string, style))
    (tmp_path / 'world.x3d').write_text(
        '<X3D version="4.1"><Scene>%s%s</Scene></X3D>' % (library, text))
    scene = Loader.load(str(tmp_path / 'world.x3d'))
    delivered()
    return scene


def test_a_font_file_describes_its_family_weight_and_slant(tmp_path):
    found = fontlibrary.read_face(str(write_font(tmp_path / 'b.ttf', weight=700, italic=True)))
    assert (found.family, found.weight, found.italic) == ('Blockish Test', 700, True)


def test_a_file_that_is_no_font_is_reported(tmp_path):
    (tmp_path / 'nothing.ttf').write_bytes(b'not a font at all')
    with pytest.raises(ValueError):
        fontlibrary.read_face(str(tmp_path / 'nothing.ttf'))


def test_a_library_family_names_its_font_for_the_documents_styles(tmp_path):
    write_font(tmp_path / 'block.ttf')
    scene = document(tmp_path, '<FontLibrary DEF="LIB" family="Fancy" url=\'"block.ttf"\'/>')
    assert loadsensor.load_state(scene.getDEF('LIB')) == loadsensor.LOADED
    found = pillowtext.face(scene.getDEF('STYLE'))
    assert found.path == str(tmp_path / 'block.ttf')
    assert TTFFontProvider.matchFile(scene.getDEF('STYLE'))[0] == str(tmp_path / 'block.ttf')


def test_without_a_family_the_fonts_own_name_is_used(tmp_path):
    write_font(tmp_path / 'block.ttf')
    scene = document(tmp_path, '<FontLibrary url=\'"block.ttf"\'/>', style='"Blockish Test"')
    assert pillowtext.face(scene.getDEF('STYLE')).path == str(tmp_path / 'block.ttf')


def test_the_style_nearest_is_chosen_among_a_familys_files(tmp_path):
    write_font(tmp_path / 'plain.ttf')
    write_font(tmp_path / 'bold.ttf', weight=700)
    write_font(tmp_path / 'italic.ttf', italic=True)
    scene = document(tmp_path, '<FontLibrary family="Fancy" url=\'"plain.ttf"\'/>'
                     '<FontLibrary family="Fancy" url=\'"bold.ttf"\'/>'
                     '<FontLibrary family="Fancy" url=\'"italic.ttf"\'/>')
    style = scene.getDEF('STYLE')
    style.style = 'BOLD'
    assert pillowtext.face(style).path == str(tmp_path / 'bold.ttf')
    style.style = 'ITALIC'
    assert pillowtext.face(style).path == str(tmp_path / 'italic.ttf')
    style.style = 'BOLDITALIC'
    found = pillowtext.face(style)
    assert found.path == str(tmp_path / 'italic.ttf') and found.embolden


def test_an_earlier_family_name_the_system_has_is_preferred(tmp_path):
    write_font(tmp_path / 'block.ttf')
    scene = document(tmp_path, '<FontLibrary family="Fancy" url=\'"block.ttf"\'/>',
                     style='"SANS" "Fancy"')
    assert pillowtext.face(scene.getDEF('STYLE')).path != str(tmp_path / 'block.ttf')


def test_a_url_outside_the_documents_folder_is_not_read(tmp_path):
    inner = tmp_path / 'inner'
    inner.mkdir()
    write_font(tmp_path / 'block.ttf')
    scene = document(inner, '<FontLibrary DEF="LIB" family="Fancy" url=\'"../block.ttf"\'/>')
    assert loadsensor.load_state(scene.getDEF('LIB')) == loadsensor.FAILED
    assert pillowtext.face(scene.getDEF('STYLE')).path != str(tmp_path / 'block.ttf')


def test_the_first_url_that_reads_is_used(tmp_path):
    write_font(tmp_path / 'block.ttf')
    scene = document(tmp_path, '<FontLibrary family="Fancy" url=\'"missing.ttf" "block.ttf"\'/>')
    assert pillowtext.face(scene.getDEF('STYLE')).path == str(tmp_path / 'block.ttf')


def test_load_false_reads_nothing_until_it_is_set(tmp_path):
    write_font(tmp_path / 'block.ttf')
    scene = document(tmp_path, '<FontLibrary DEF="LIB" load="false" family="Fancy" '
                     'url=\'"block.ttf"\'/>')
    assert pillowtext.face(scene.getDEF('STYLE')).path != str(tmp_path / 'block.ttf')
    scene.getDEF('LIB').load = True
    delivered()
    assert pillowtext.face(scene.getDEF('STYLE')).path == str(tmp_path / 'block.ttf')


def test_another_documents_styles_do_not_see_the_library(tmp_path):
    write_font(tmp_path / 'block.ttf')
    document(tmp_path, '<FontLibrary family="Fancy" url=\'"block.ttf"\'/>')
    other = tmp_path / 'other'
    other.mkdir()
    scene = document(other, '')
    assert pillowtext.face(scene.getDEF('STYLE')).path != str(tmp_path / 'block.ttf')


def test_the_library_changes_when_a_font_arrives(tmp_path):
    write_font(tmp_path / 'block.ttf')
    scene = document(tmp_path, '<FontLibrary DEF="LIB" family="Fancy" url=\'"block.ttf"\'/>')
    fonts = fontlibrary.document_fonts(scene.getDEF('STYLE'))
    before = fonts.generation
    scene.getDEF('LIB').family = 'Other'
    delivered()
    assert fonts.generation != before
    assert pillowtext.face(scene.getDEF('STYLE')).path != str(tmp_path / 'block.ttf')


def ink(image):
    """The fraction of the frame's text box that is inked"""
    lit = image.max(axis=2) > 128
    rows, columns = np.nonzero(lit)
    if not len(rows):
        return 0.0
    box = lit[rows.min():rows.max() + 1, columns.min():columns.max() + 1]
    return float(box.mean())


def test_the_text_is_drawn_in_the_librarys_font(tmp_path):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    write_font(tmp_path / 'block.ttf')
    scene = document(tmp_path, '<FontLibrary family="Fancy" url=\'"block.ttf"\'/>'
                     '<Viewpoint position="0.35 0.35 3"/>', string='"W"')
    with scene_context(scene, renderer='pbr') as context:
        drawn_image(context)
        assert ink(drawn_image(context)) > 0.9


def test_text_drawn_before_its_font_arrives_is_drawn_again_in_it(tmp_path):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    write_font(tmp_path / 'block.ttf')
    scene = document(tmp_path, '<FontLibrary DEF="LIB" load="false" family="Fancy" '
                     'url=\'"block.ttf"\'/><Viewpoint position="0.35 0.35 3"/>',
                     string='"W"')
    with scene_context(scene, renderer='pbr') as context:
        drawn_image(context)
        assert ink(drawn_image(context)) < 0.8
        scene.getDEF('LIB').load = True
        delivered()
        drawn_image(context)
        assert ink(drawn_image(context)) > 0.9


def test_a_style_in_no_document_has_no_library():
    from OpenGLContext.scenegraph.basenodes import FontStyle  # noqa: PLC0415 kept with its use
    style = FontStyle(family=['Fancy'])
    assert fontlibrary.document_fonts(style) is None
    assert fontlibrary.key(style) == ()
    assert fontlibrary.faces_for(style, 'Fancy') == []


def test_a_library_built_in_code_reads_a_path_the_application_names(tmp_path):
    from OpenGLContext.scenegraph.basenodes import (  # noqa: PLC0415 kept with its use
        FontStyle, Shape, Text, sceneGraph,
    )
    write_font(tmp_path / 'block.ttf')
    library = fontlibrary.FontLibrary(family='Fancy')
    style = FontStyle(family=['Fancy'])
    scene = sceneGraph(children=[library, Shape(geometry=Text(string=['W'], fontStyle=style))])
    library.url = [str(tmp_path / 'block.ttf')]
    delivered()
    assert pillowtext.face(style).path == str(tmp_path / 'block.ttf')
    assert scene.children[0] is library


@pytest.fixture
def served(tmp_path):
    """``tmp_path/site`` served over http on localhost; yields (directory, url)."""
    import functools  # noqa: PLC0415 kept with its use
    import http.server  # noqa: PLC0415 kept with its use
    import threading  # noqa: PLC0415 kept with its use
    site = tmp_path / 'site'
    site.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    handler.log_message = lambda *_args: None
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield site, 'http://%s:%d/' % (host, port)
    finally:
        server.shutdown()
        server.server_close()


def test_a_served_documents_font_is_fetched_from_its_origin(served, tmp_path, monkeypatch):
    from OpenGLContext.loaders import resolver  # noqa: PLC0415 kept with its use
    monkeypatch.setattr(resolver, 'default_cache_dir', lambda: str(tmp_path / 'cache'))
    site, url = served
    write_font(site / 'block.ttf')
    (site / 'world.x3d').write_text(
        '<X3D version="4.1"><Scene><FontLibrary family="Fancy" url=\'"block.ttf"\'/>'
        '<Shape><Text string=\'"W"\'><FontStyle DEF="STYLE" family=\'"Fancy"\'/></Text>'
        '</Shape></Scene></X3D>')
    scene = Loader.load(url + 'world.x3d')
    delivered()
    found = pillowtext.face(scene.getDEF('STYLE')).path
    assert found.startswith(str(tmp_path / 'cache'))


def test_a_font_without_a_style_table_is_of_normal_weight(tmp_path):
    font = block_font().font
    del font['OS/2']
    font.save(str(tmp_path / 'bare.ttf'))
    found = fontlibrary.read_face(str(tmp_path / 'bare.ttf'))
    assert (found.weight, found.italic) == (fontlibrary.NORMAL_WEIGHT, False)


def test_a_read_superseded_by_a_later_one_is_not_placed(tmp_path):
    write_font(tmp_path / 'block.ttf')
    scene = document(tmp_path, '<FontLibrary DEF="LIB" family="Fancy" url=\'"block.ttf"\'/>')
    library = scene.getDEF('LIB')
    stale = fontlibrary.FontFace(str(tmp_path / 'stale.ttf'), 'Fancy', 400, False)
    library._place(stale, library.__dict__['_generation'] - 1)
    assert pillowtext.face(scene.getDEF('STYLE')).path == str(tmp_path / 'block.ttf')
