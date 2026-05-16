"""HTML test report generator for OpenGLContext visual regression tests.

This module generates HTML reports showing test results, including
reference/result/diff images and comparison statistics.
"""

import base64
import html
import json
import os
from datetime import datetime
from pathlib import Path
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

        <ul class="test-list">
            {test_items}
        </ul>
    </div>

    <script>
        document.querySelectorAll('.test-header').forEach(header => {{
            header.addEventListener('click', () => {{
                header.parentElement.classList.toggle('expanded');
            }});
        }});
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
        {stats_section}
        {output_section}
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

    def generate_html(self, embed_images: bool = True) -> str:
        """Generate the HTML report.

        Args:
            embed_images: If True, embed images as base64. If False, use file paths.

        Returns:
            HTML string
        """
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

        # Images section
        images_section = self._generate_images_section(test, embed_images)

        # Stats section
        stats_section = self._generate_stats_section(test)

        # Output section
        output_section = self._generate_output_section(test)

        return TEST_ITEM_TEMPLATE.format(
            status_color=_status_color(status),
            status_icon=_status_icon(status),
            test_name=test_name,
            duration=duration_str,
            images_section=images_section,
            stats_section=stats_section,
            output_section=output_section,
        )

    def _generate_images_section(self, test: Dict[str, Any], embed_images: bool) -> str:
        """Generate the images comparison section."""
        images = []

        for label, key in [
            ('Reference', 'reference_image'),
            ('Result', 'result_image'),
            ('Difference', 'diff_image'),
        ]:
            path = test.get(key)
            if embed_images and path:
                src = _encode_image_base64(path)
            else:
                src = path

            if src:
                img_html = f'<img src="{src}" alt="{label}">'
            else:
                img_html = '<div class="no-image">No image</div>'

            images.append(f'''
                <div class="image-box">
                    <h4>{label}</h4>
                    {img_html}
                </div>
            ''')

        return f'<div class="image-comparison">{"".join(images)}</div>'

    def _generate_stats_section(self, test: Dict[str, Any]) -> str:
        """Generate the comparison statistics section."""
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

        if not rows:
            return ''

        return f'''
            <div class="stats">
                <h4>Comparison Statistics</h4>
                <table>{"".join(rows)}</table>
            </div>
        '''

    def _generate_output_section(self, test: Dict[str, Any]) -> str:
        """Generate the output (stdout/stderr) section."""
        sections = []

        stdout = test.get('stdout', '').strip()
        stderr = test.get('stderr', '').strip()

        if stdout:
            sections.append(f'''
                <div class="output-section">
                    <h4>Standard Output</h4>
                    <div class="output">{html.escape(stdout)}</div>
                </div>
            ''')

        if stderr:
            sections.append(f'''
                <div class="output-section">
                    <h4>Standard Error</h4>
                    <div class="output">{html.escape(stderr)}</div>
                </div>
            ''')

        return ''.join(sections)

    def save(self, output_path: str, embed_images: bool = True) -> None:
        """Save the report to a file.

        Args:
            output_path: Path to save the HTML file
            embed_images: Whether to embed images as base64
        """
        html_content = self.generate_html(embed_images)
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


# pytest-html integration hook
def pytest_html_results_summary(prefix, summary, postfix):
    """pytest-html hook for custom summary content."""
    pass


def pytest_html_report_title(report):
    """pytest-html hook to set report title."""
    report.title = "OpenGLContext Test Report"
