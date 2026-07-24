"""Unit tests for OpenGLContext.testing.report_generator.

Cover the image encoding/referencing helpers, the diff/stats/metadata sections,
and the generate_report entry point with synthetic result dicts and real PNG
bytes on disk.
"""

import base64
import os

from OpenGLContext.testing.report_generator import (
    _encode_image_base64,
    _image_ref,
    generate_report,
)
from OpenGLContext.testing.report_generator import (
    TestReportGenerator as _TestReportGenerator,
)

# A minimal but valid 1x1 PNG.
_PNG_BYTES = base64.b64decode(
    b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9'
    b'awAAAABJRU5ErkJggg=='
)


def _write_png(path) -> str:
    path.write_bytes(_PNG_BYTES)
    return str(path)


# --------------------------------------------------------------------------
# _encode_image_base64
# --------------------------------------------------------------------------


def test_encode_image_returns_data_uri(tmp_path):
    """A real PNG file is encoded as a base64 data URI of its bytes."""
    path = _write_png(tmp_path / 'img.png')
    uri = _encode_image_base64(path)
    assert uri is not None
    assert uri.startswith('data:image/png;base64,')
    payload = uri.split(',', 1)[1]
    assert base64.b64decode(payload) == _PNG_BYTES


def test_encode_image_missing_file_returns_none():
    """A path that does not exist encodes to None."""
    assert _encode_image_base64('/no/such/file.png') is None
    assert _encode_image_base64('') is None


def test_encode_image_unreadable_returns_none(tmp_path):
    """An unreadable path (a directory) is handled and returns None."""
    assert _encode_image_base64(str(tmp_path)) is None


# --------------------------------------------------------------------------
# _image_ref
# --------------------------------------------------------------------------


def test_image_ref_none_when_no_path():
    """No image path yields no src."""
    assert _image_ref(None, embed_images=True, base_dir=None) is None


def test_image_ref_embeds_when_requested(tmp_path):
    """With embed, the ref is the inlined data URI."""
    path = _write_png(tmp_path / 'img.png')
    ref = _image_ref(path, embed_images=True, base_dir=None)
    assert ref is not None and ref.startswith('data:image/png;base64,')


def test_image_ref_relative_to_base_dir(tmp_path):
    """Without embed and with a base_dir, the ref is made relative to it."""
    img = tmp_path / 'sub' / 'img.png'
    img.parent.mkdir()
    _write_png(img)
    ref = _image_ref(str(img), embed_images=False, base_dir=str(tmp_path))
    assert ref == 'sub/img.png'


def test_image_ref_verbatim_without_base_dir():
    """Without embed and without base_dir, the path is used as given."""
    assert _image_ref('a/b.png', embed_images=False, base_dir=None) == 'a/b.png'


def test_image_ref_falls_back_on_cross_drive(monkeypatch):
    """A ValueError from relpath (cross-drive) falls back to the raw path."""
    def _boom(path, start):
        raise ValueError('paths on different drives')

    monkeypatch.setattr(os.path, 'relpath', _boom)
    ref = _image_ref('X:/img.png', embed_images=False, base_dir='Y:/out')
    assert ref == 'X:/img.png'


# --------------------------------------------------------------------------
# diff / stats / metadata sections
# --------------------------------------------------------------------------


def test_report_includes_stats_stderr_and_diff(tmp_path):
    """A test with stats, streams and a diff image renders the collapsible block."""
    diff = _write_png(tmp_path / 'diff.png')
    gen = _TestReportGenerator('Stats Report')
    gen.add_test({
        'test_name': 'stats_case',
        'status': 'fail',
        'diff_image': diff,
        'stderr': 'boom on stderr',
        'stdout': 'chatter on stdout',
        'comparison_stats': {
            'shapes_match': False,
            'max_diff': 200.0,
            'mean_diff': 12.5,
            'percent_different': 3.14,
            'pixels_different': 1234,
            'total_pixels': 40000,
        },
    })
    html = gen.generate_html(embed_images=True)

    assert 'Show difference heatmap' in html
    assert 'Shapes Match' in html and '>No<' in html
    assert '200.0 / 255' in html
    assert '12.50' in html
    assert '3.14%' in html
    assert '1,234 / 40,000' in html
    assert 'boom on stderr' in html
    assert 'chatter on stdout' in html
    assert 'Difference' in html


def test_report_metadata_section_flattens_values():
    """Metadata dict/list values are flattened into the metadata table."""
    gen = _TestReportGenerator()
    gen.add_test({
        'test_name': 'meta_case',
        'status': 'pass',
        'metadata': {
            'model': 'DamagedHelmet',
            'framing': [640, 480],
            'camera': {'fov': 45, 'near': 0.1},
        },
    })
    html = gen.generate_html()

    assert 'Render metadata' in html
    assert 'DamagedHelmet' in html
    assert '640 x 480' in html
    assert 'fov=45' in html and 'near=0.1' in html


def test_report_omits_empty_sections():
    """A bare pass with no images/stats/metadata emits neither optional block."""
    gen = _TestReportGenerator()
    gen.add_test({'test_name': 'plain', 'status': 'pass'})
    html = gen.generate_html()
    assert 'Show difference heatmap' not in html
    assert 'Render metadata' not in html


# --------------------------------------------------------------------------
# generate_report entry point
# --------------------------------------------------------------------------


def test_generate_report_writes_file(tmp_path):
    """generate_report writes an HTML file and returns its path."""
    out = tmp_path / 'nested' / 'report.html'
    results = [
        {'test_name': 'a', 'status': 'pass', 'duration': 1.5},
        {'test_name': 'b', 'status': 'fail', 'duration': 0.0},
    ]
    returned = generate_report(results, str(out), title='My Report')
    assert returned == str(out)
    assert out.exists()
    content = out.read_text()
    assert 'My Report' in content
    assert '>a<' in content and '>b<' in content


def test_save_non_embedded_links_relative_images(tmp_path):
    """Saving without embed links images relative to the report directory."""
    img = tmp_path / 'result.png'
    _write_png(img)
    out = tmp_path / 'report.html'
    gen = _TestReportGenerator('Linked')
    gen.add_test({'test_name': 'linked', 'status': 'pass',
                  'result_image': str(img)})
    gen.save(str(out), embed_images=False)

    content = out.read_text()
    assert 'src="result.png"' in content
    assert 'data:image/png' not in content
