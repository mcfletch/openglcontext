"""The regression report shows a 4th 'Upstream (Khronos)' column when an
upstream_image is present, plus an expand-all control and a click-to-zoom
lightbox -- without breaking the classic 3-column reports."""
from OpenGLContext.testing.report_generator import (
    TestReportGenerator as _ReportGenerator,
)


def _html(test):
    g = _ReportGenerator(title='t')
    g.add_test(test)
    return g.generate_html(embed_images=False)


class TestUpstreamColumn:
    def test_four_columns_when_upstream_present(self):
        h = _html({'test_name': 'x', 'status': 'pass',
                   'reference_image': 'r.png', 'result_image': 's.png',
                   'diff_image': 'd.png', 'upstream_image': 'u.png'})
        assert 'Our Reference' in h        # primary relabelled
        assert 'Upstream (Khronos)' in h   # the 4th column
        assert 'href="u.png"' in h         # the upstream image is rendered

    def test_three_column_report_unchanged(self):
        h = _html({'test_name': 'x', 'status': 'fail',
                   'reference_image': 'r.png', 'result_image': 's.png',
                   'diff_image': 'd.png'})
        assert '>Reference<' in h           # plain label, not "Our Reference"
        assert 'Our Reference' not in h
        assert 'Upstream (Khronos)' not in h


class TestReportControls:
    def test_expand_all_control_present(self):
        h = _html({'test_name': 'x', 'status': 'pass'})
        assert 'id="expand-all"' in h
        assert 'Expand all' in h

    def test_lightbox_present_and_images_are_zoomable(self):
        h = _html({'test_name': 'x', 'status': 'pass', 'result_image': 's.png'})
        assert 'id="lightbox"' in h
        assert 'class="zoomable"' in h
