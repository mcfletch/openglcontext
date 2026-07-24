"""HTML test report generator for OpenGLContext visual regression tests.

This module generates HTML reports showing test results, including
reference/result/diff images and comparison statistics.
"""

import base64
import html
import os
from datetime import datetime
from typing import Any, Dict, List, Optional


def _encode_image_base64(image_path: str) -> Optional[str]:
    """Encode an image file as base64 data URI.

    Args:
        image_path: Path to the image file

    Returns:
        Base64 data URI string, or None if file doesn't exist
    """
    if not image_path or not os.path.exists(image_path):
        return None

    try:
        with open(image_path, 'rb') as f:
            data = f.read()
        encoded = base64.b64encode(data).decode('utf-8')
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return None


def _image_ref(image_path: Optional[str], embed_images: bool,
               base_dir: Optional[str]) -> Optional[str]:
    """Resolve an image path to an HTML ``src``.

    An embedded report inlines the bytes as a base64 data URI. Otherwise the
    report links the file: **relative to the report's own directory** when
    ``base_dir`` is known, so the report and its images copy elsewhere together;
    with no ``base_dir`` the path is used verbatim.
    """
    if not image_path:
        return None
    if embed_images:
        return _encode_image_base64(image_path)
    if base_dir:
        try:
            rel = os.path.relpath(os.path.abspath(image_path), base_dir)
        except ValueError:      # different drive on Windows -- no relative form
            return image_path
        return rel.replace(os.sep, '/')
    return image_path


def _status_color(status: str) -> str:
    """Get CSS color for a status."""
    colors = {
        'pass': '#28a745',
        'fail': '#dc3545',
        'skip': '#ffc107',
        'error': '#dc3545',
        'pending': '#6c757d',
        'visual_diff_expected': '#17a2b8',  # Blue - expected difference
    }
    return colors.get(status, '#6c757d')


def _status_icon(status: str) -> str:
    """Get emoji icon for a status."""
    icons = {
        'pass': '✓',
        'fail': '✗',
        'skip': '⊘',
        'error': '⚠',
        'pending': '○',
        'visual_diff_expected': '~',  # Tilde - expected difference
    }
    return icons.get(status, '?')


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{
            color: #333;
            border-bottom: 2px solid #ddd;
            padding-bottom: 10px;
        }}
        .summary {{
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .summary-card {{
            background: white;
            padding: 15px 25px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .summary-card h2 {{ margin: 0 0 5px 0; font-size: 2em; }}
        .summary-card p {{ margin: 0; color: #666; }}
        .pass {{ color: #28a745; }}
        .fail {{ color: #dc3545; }}
        .skip {{ color: #ffc107; }}
        .test-list {{ list-style: none; padding: 0; }}
        .test-item {{
            background: white;
            margin-bottom: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .test-header {{
            display: flex;
            align-items: center;
            padding: 15px 20px;
            cursor: pointer;
            border-bottom: 1px solid #eee;
        }}
        .test-header:hover {{ background: #f9f9f9; }}
        .status-badge {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            color: white;
            font-weight: bold;
            margin-right: 15px;
            font-size: 14px;
        }}
        .test-name {{
            font-weight: 600;
            flex-grow: 1;
        }}
        .test-duration {{
            color: #888;
            font-size: 0.9em;
        }}
        .test-details {{
            display: none;
            padding: 20px;
            background: #fafafa;
        }}
        .test-item.expanded .test-details {{ display: block; }}
        .image-comparison {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .image-box {{
            background: white;
            padding: 10px;
            border-radius: 4px;
            border: 1px solid #ddd;
        }}
        .image-box h4 {{
            margin: 0 0 10px 0;
            font-size: 0.9em;
            color: #666;
        }}
        .image-box img {{
            max-width: 100%;
            height: auto;
            display: block;
            border: 1px solid #eee;
        }}
        .stats {{
            background: white;
            padding: 15px;
            border-radius: 4px;
            border: 1px solid #ddd;
            margin-bottom: 20px;
        }}
        .stats table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .stats td, .stats th {{
            padding: 8px 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        .stats th {{ color: #666; font-weight: 500; }}
        .diff-details, .metadata-details {{ margin-bottom: 20px; }}
        .diff-details > summary, .metadata-details > summary {{
            cursor: pointer;
            color: #0969da;
            font-size: 0.9em;
            padding: 4px 0;
            user-select: none;
            list-style: none;
        }}
        .diff-details > summary:hover, .metadata-details > summary:hover {{
            text-decoration: underline;
        }}
        .diff-details > summary::before {{ content: '▸ '; }}
        .diff-details[open] > summary::before {{ content: '▾ '; }}
        .metadata-details > summary::before {{ content: '▸ '; }}
        .metadata-details[open] > summary::before {{ content: '▾ '; }}
        .output {{
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 15px;
            border-radius: 4px;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 13px;
            white-space: pre-wrap;
            overflow-x: auto;
            max-height: 300px;
            overflow-y: auto;
        }}
        .output-section {{ margin-bottom: 15px; }}
        .output-section h4 {{ margin: 0 0 10px 0; color: #333; }}
        .no-image {{
            display: flex;
            align-items: center;
            justify-content: center;
            height: 150px;
            background: #f0f0f0;
            color: #999;
            border: 1px dashed #ccc;
            border-radius: 4px;
        }}
        .timestamp {{
            color: #888;
            font-size: 0.9em;
            margin-bottom: 20px;
        }}
        .expand-icon {{
            color: #888;
            margin-left: 10px;
            transition: transform 0.2s;
        }}
        .test-item.expanded .expand-icon {{ transform: rotate(90deg); }}
        .toolbar {{ margin-bottom: 15px; }}
        .toolbar button {{
            font-size: 0.9em;
            padding: 8px 16px;
            border: 1px solid #ccc;
            border-radius: 4px;
            background: #fff;
            cursor: pointer;
        }}
        .toolbar button:hover {{ background: #f0f0f0; }}
        .image-box a.zoomable {{ display: block; cursor: zoom-in; }}
        .lightbox {{
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.9);
            z-index: 1000;
            cursor: zoom-out;
            padding: 20px;
        }}
        .lightbox.open {{ display: flex; align-items: center; justify-content: center; }}
        .lightbox img {{
            max-width: 100%;
            max-height: 100%;
            box-shadow: 0 0 40px rgba(0, 0, 0, 0.6);
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <p class="timestamp">Generated: {timestamp}</p>

        <div class="summary">
            <div class="summary-card">
                <h2>{total}</h2>
                <p>Total Tests</p>
            </div>
            <div class="summary-card">
                <h2 class="pass">{passed}</h2>
                <p>Passed</p>
            </div>
            <div class="summary-card">
                <h2 class="fail">{failed}</h2>
                <p>Failed</p>
            </div>
            <div class="summary-card">
                <h2 class="skip">{skipped}</h2>
                <p>Skipped</p>
            </div>
        </div>

        <div class="toolbar">
            <button id="expand-all" type="button">Expand all</button>
        </div>

        <ul class="test-list">
            {test_items}
        </ul>
    </div>

    <div class="lightbox" id="lightbox"><img alt="zoomed image"></div>

    <script>
        document.querySelectorAll('.test-header').forEach(header => {{
            header.addEventListener('click', () => {{
                header.parentElement.classList.toggle('expanded');
            }});
        }});

        // Expand/collapse every card at once so the page can be scanned in one pass.
        (function () {{
            const btn = document.getElementById('expand-all');
            if (!btn) return;
            btn.addEventListener('click', () => {{
                const items = document.querySelectorAll('.test-item');
                const anyCollapsed = Array.from(items).some(
                    i => !i.classList.contains('expanded'));
                items.forEach(i => i.classList.toggle('expanded', anyCollapsed));
                btn.textContent = anyCollapsed ? 'Collapse all' : 'Expand all';
            }});
        }})();

        // Click any image to view it full size; click the backdrop or press Esc.
        (function () {{
            const box = document.getElementById('lightbox');
            if (!box) return;
            const img = box.querySelector('img');
            document.querySelectorAll('a.zoomable').forEach(a => {{
                a.addEventListener('click', ev => {{
                    ev.preventDefault();
                    img.src = a.getAttribute('href');
                    box.classList.add('open');
                }});
            }});
            box.addEventListener('click', () => box.classList.remove('open'));
            document.addEventListener('keydown', ev => {{
                if (ev.key === 'Escape') box.classList.remove('open');
            }});
        }})();
    </script>
</body>
</html>
"""

TEST_ITEM_TEMPLATE = """
<li class="test-item">
    <div class="test-header">
        <span class="status-badge" style="background-color: {status_color};">{status_icon}</span>
        <span class="test-name">{test_name}</span>
        <span class="test-duration">{duration}</span>
        <span class="expand-icon">▶</span>
    </div>
    <div class="test-details">
        {images_section}
        {diff_details}
        {metadata_section}
    </div>
</li>
"""


class TestReportGenerator:
    """Generates HTML test reports."""

    def __init__(self, title: str = "OpenGLContext Test Report"):
        """Initialize the report generator.

        Args:
            title: Title for the HTML report
        """
        self.title = title
        self.tests: List[Dict[str, Any]] = []

    def add_test(self, test_data: Dict[str, Any]) -> None:
        """Add a test result to the report.

        Args:
            test_data: Test result data from VisualRegressionTest.generate_report_data()
        """
        self.tests.append(test_data)

    def generate_html(self, embed_images: bool = True,
                      base_dir: Optional[str] = None) -> str:
        """Generate the HTML report.

        Args:
            embed_images: If True, embed images as base64. If False, link files.
            base_dir: When not embedding, the directory the report is written to;
                image links are made relative to it so the report and its images
                copy elsewhere together. None links images by the path as given.

        Returns:
            HTML string
        """
        self._base_dir = base_dir
        # Count results
        passed = sum(1 for t in self.tests if t.get('status') == 'pass')
        failed = sum(1 for t in self.tests if t.get('status') == 'fail')
        skipped = sum(1 for t in self.tests if t.get('status') in ('skip', 'pending'))
        total = len(self.tests)

        # Generate test items
        test_items = []
        for test in self.tests:
            test_items.append(self._generate_test_item(test, embed_images))

        return HTML_TEMPLATE.format(
            title=html.escape(self.title),
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            total=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            test_items='\n'.join(test_items),
        )

    def _generate_test_item(self, test: Dict[str, Any], embed_images: bool) -> str:
        """Generate HTML for a single test item.

        Args:
            test: Test data dictionary
            embed_images: Whether to embed images as base64

        Returns:
            HTML string for the test item
        """
        status = test.get('status', 'pending')
        test_name = html.escape(test.get('test_name', 'Unknown'))
        duration = test.get('duration', 0.0)
        duration_str = f"{duration:.2f}s" if duration else ""

        # Real images stay visible; the diff heatmap + stats + stdout/stderr collapse
        # behind one toggle; render metadata is a second collapsible after that.
        images_section = self._generate_images_section(test, embed_images)
        diff_details = self._generate_diff_details(test, embed_images)
        metadata_section = self._generate_metadata_section(test)

        return TEST_ITEM_TEMPLATE.format(
            status_color=_status_color(status),
            status_icon=_status_icon(status),
            test_name=test_name,
            duration=duration_str,
            images_section=images_section,
            diff_details=diff_details,
            metadata_section=metadata_section,
        )

    def _generate_images_section(self, test: Dict[str, Any], embed_images: bool) -> str:
        """Generate the images comparison section.

        Renders up to four columns. When an ``upstream_image`` (the tertiary
        Khronos reference) is present the primary ``reference_image`` is labelled
        "Our Reference" and the Khronos shot is shown as a fourth column;
        otherwise the classic three-column Reference/Result/Difference layout is
        produced unchanged. Every image is wrapped in a ``.zoomable`` link so the
        report's lightbox can open it full size.
        """
        has_upstream = bool(test.get('upstream_image'))
        # The real images (our reference, the new result, and the Khronos upstream)
        # stay visible; the amplified difference heatmap is the least-interesting of
        # the four for a passing scene, so it collapses behind a click to give the
        # real images more room.
        columns = [
            ('Our Reference' if has_upstream else 'Reference', 'reference_image'),
            ('Result', 'result_image'),
        ]
        if has_upstream:
            columns.append(('Upstream (Khronos)', 'upstream_image'))

        def _image_box(label: str, path: str | None) -> str:
            src = _image_ref(path, embed_images, getattr(self, '_base_dir', None))
            if src:
                img_html = (f'<a class="zoomable" href="{src}">'
                            f'<img src="{src}" alt="{label}"></a>')
            else:
                img_html = '<div class="no-image">No image</div>'
            return f'<div class="image-box"><h4>{label}</h4>{img_html}</div>'

        self._image_box = _image_box   # reused by the diff-details section
        images = [_image_box(label, test.get(key)) for label, key in columns]
        return f'<div class="image-comparison">{"".join(images)}</div>'

    def _generate_diff_details(self, test: Dict[str, Any], embed_images: bool) -> str:
        """One collapsible 'Show difference heatmap' toggle holding the amplified
        diff image, the comparison statistics, and stderr/stdout -- the detail a
        reviewer only wants on demand, kept out of the way of the real images."""
        image_box = getattr(self, '_image_box', None)
        diff_path = test.get('diff_image')
        stats_rows = self._stats_rows(test)
        stderr = (test.get('stderr') or '').strip()
        stdout = (test.get('stdout') or '').strip()
        if not (diff_path or stats_rows or stderr or stdout):
            return ''
        parts = []
        if diff_path and image_box is not None:
            parts.append('<div class="image-comparison">%s</div>'
                         % image_box('Difference', diff_path))
        if stats_rows:
            parts.append('<div class="stats"><table>%s</table></div>' % stats_rows)
        for label, text in (('Standard Error', stderr), ('Standard Output', stdout)):
            if text:
                parts.append('<div class="output-section"><h4>%s</h4>'
                             '<div class="output">%s</div></div>'
                             % (label, html.escape(text)))
        return ('<details class="diff-details"><summary>Show difference heatmap, '
                'stats &amp; output</summary>%s</details>' % ''.join(parts))

    def _generate_metadata_section(self, test: Dict[str, Any]) -> str:
        """Render per-view render metadata (model, background, framing, provenance)
        as a collapsible table, from the ``metadata`` dict on the test data."""
        meta = test.get('metadata')
        if not meta:
            return ''
        rows = []
        for key, value in meta.items():
            if isinstance(value, dict):
                value = ', '.join('%s=%s' % (k, v) for k, v in value.items())
            elif isinstance(value, (list, tuple)):
                value = ' x '.join(str(v) for v in value)
            rows.append('<tr><th>%s</th><td>%s</td></tr>'
                        % (html.escape(str(key)), html.escape(str(value))))
        return (
            '<details class="metadata-details"><summary>Render metadata</summary>'
            '<div class="stats"><table>%s</table></div></details>' % ''.join(rows))

    def _stats_rows(self, test: Dict[str, Any]) -> str:
        """The comparison-statistics table rows (``<tr>...``), or '' if no stats."""
        stats = test.get('comparison_stats')
        if not stats:
            return ''
        rows = []
        if 'shapes_match' in stats:
            match_str = "Yes" if stats['shapes_match'] else "No"
            rows.append(f'<tr><th>Shapes Match</th><td>{match_str}</td></tr>')
        if 'max_diff' in stats:
            rows.append(f'<tr><th>Max Difference</th><td>{stats["max_diff"]:.1f} / 255</td></tr>')
        if 'mean_diff' in stats:
            rows.append(f'<tr><th>Mean Difference</th><td>{stats["mean_diff"]:.2f}</td></tr>')
        if 'percent_different' in stats:
            rows.append(f'<tr><th>Pixels Different</th><td>{stats["percent_different"]:.2f}%</td></tr>')
        if 'pixels_different' in stats and 'total_pixels' in stats:
            rows.append(f'<tr><th>Pixel Count</th><td>{stats["pixels_different"]:,} / {stats["total_pixels"]:,}</td></tr>')
        return ''.join(rows)

    def save(self, output_path: str, embed_images: bool = True) -> None:
        """Save the report to a file.

        Args:
            output_path: Path to save the HTML file
            embed_images: Whether to embed images as base64
        """
        base_dir = None if embed_images else os.path.dirname(os.path.abspath(output_path))
        html_content = self.generate_html(embed_images, base_dir=base_dir)
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)


def generate_report(
    test_results: List[Dict[str, Any]],
    output_path: str,
    title: str = "OpenGLContext Test Report",
    embed_images: bool = True,
) -> str:
    """Generate an HTML test report.

    Args:
        test_results: List of test result dictionaries
        output_path: Path to save the HTML file
        title: Report title
        embed_images: Whether to embed images as base64

    Returns:
        Path to the generated report
    """
    generator = TestReportGenerator(title)
    for result in test_results:
        generator.add_test(result)
    generator.save(output_path, embed_images)
    return output_path
