#!/usr/bin/env python
"""Generate font texture atlases for shader-based text rendering.

This script generates pre-rendered texture atlases from DejaVu Sans Mono
at multiple sizes for embedding in OpenGLContext.

DejaVu fonts are based on Bitstream Vera fonts, which are in the public domain.
DejaVu additions are under a permissive license allowing embedding.
See: https://dejavu-fonts.github.io/License.html

Usage:
    python scripts/generate_font_atlas.py [--output-dir DIR] [--sizes SIZE,SIZE,...]

Requirements:
    - PIL/Pillow for image generation
"""

import argparse
import base64
import io
import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow")
    sys.exit(1)


# Font sizes to generate (height in pixels)
DEFAULT_SIZES = [10, 12, 14, 16, 18, 20, 24, 28, 32]

# Characters to include in the atlas (ASCII printable + some extras)
FIRST_CHAR = 32   # Space
LAST_CHAR = 126   # Tilde
CHARS_PER_ROW = 16

# License notice for DejaVu Sans Mono
LICENSE_NOTICE = """
Font: DejaVu Sans Mono
License: DejaVu Fonts License (permissive, allows embedding)
Homepage: https://dejavu-fonts.github.io/

DejaVu fonts are based on Bitstream Vera fonts. Bitstream Vera fonts
are released to the public domain. DejaVu changes are in public domain.
Glyphs imported from other sources are under compatible permissive licenses.

The full license text is available at:
https://dejavu-fonts.github.io/License.html

This license explicitly permits:
- Embedding in documents and software
- Redistribution with or without modification
- Commercial and non-commercial use
"""


def find_dejavu_font():
    """Try to find DejaVu Sans Mono on the system."""
    search_paths = [
        # Linux system fonts
        '/usr/share/fonts/truetype/dejavu/',
        '/usr/share/fonts/dejavu/',
        '/usr/share/fonts/TTF/',
        '~/.local/share/fonts/',
        # Debian/Ubuntu
        '/usr/share/fonts/truetype/dejavu/',
        # Fedora/RHEL
        '/usr/share/fonts/dejavu-sans-mono-fonts/',
        '/usr/share/fonts/dejavu/',
        # Arch Linux
        '/usr/share/fonts/TTF/',
        # macOS
        '~/Library/Fonts/',
        '/Library/Fonts/',
        '/System/Library/Fonts/',
        # Windows
        'C:/Windows/Fonts/',
    ]

    font_names = [
        'DejaVuSansMono.ttf',
        'DejaVu Sans Mono.ttf',
        'dejavu-sans-mono.ttf',
    ]

    for path in search_paths:
        path = os.path.expanduser(path)
        if os.path.isdir(path):
            for name in font_names:
                full_path = os.path.join(path, name)
                if os.path.isfile(full_path):
                    return full_path

    return None


def find_monospace_font():
    """Find any available monospace font as fallback."""
    monospace_fonts = [
        # Linux - try several common monospace fonts
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf',
        '/usr/share/fonts/truetype/freefont/FreeMono.ttf',
        '/usr/share/fonts/TTF/DejaVuSansMono.ttf',
        '/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf',
        # macOS
        '/System/Library/Fonts/Menlo.ttc',
        '/System/Library/Fonts/Monaco.dfont',
        # Windows
        'C:/Windows/Fonts/consola.ttf',
        'C:/Windows/Fonts/cour.ttf',
    ]

    for path in monospace_fonts:
        path = os.path.expanduser(path)
        if os.path.isfile(path):
            return path

    return None


def generate_atlas(font_path, size):
    """Generate a font texture atlas at the specified size.

    Args:
        font_path: Path to TTF font file
        size: Font size in points

    Returns:
        Dict with atlas data including:
        - image: PIL Image object
        - char_width: Width of each character cell
        - char_height: Height of each character cell
        - atlas_width: Total atlas width
        - atlas_height: Total atlas height
        - baseline: Y offset from top of cell to baseline
    """
    try:
        font = ImageFont.truetype(font_path, size)
    except Exception as e:
        print(f"Warning: Could not load font at size {size}: {e}")
        font = ImageFont.load_default()

    # Get font metrics - ascent is distance from baseline to top of tallest char,
    # descent is distance from baseline to bottom of lowest char (e.g., 'g')
    font_ascent, font_descent = font.getmetrics()

    # Measure max character width
    max_width = 0
    for char_code in range(FIRST_CHAR, LAST_CHAR + 1):
        char = chr(char_code)
        bbox = font.getbbox(char)
        if bbox:
            width = bbox[2] - bbox[0]
            max_width = max(max_width, width)

    # Add padding for better rendering
    char_width = max_width + 2
    # Cell height needs to accommodate full ascent + descent + padding
    char_height = font_ascent + font_descent + 2
    # Baseline position from top of cell (1 pixel padding + ascent)
    baseline = 1 + font_ascent

    # Calculate atlas dimensions
    num_chars = LAST_CHAR - FIRST_CHAR + 1
    num_rows = (num_chars + CHARS_PER_ROW - 1) // CHARS_PER_ROW
    atlas_width = CHARS_PER_ROW * char_width
    atlas_height = num_rows * char_height

    # Create RGBA image with transparent background
    image = Image.new('RGBA', (atlas_width, atlas_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Render each character aligned to baseline
    for char_code in range(FIRST_CHAR, LAST_CHAR + 1):
        char_idx = char_code - FIRST_CHAR
        col = char_idx % CHARS_PER_ROW
        row = char_idx // CHARS_PER_ROW

        # Cell top-left corner
        cell_x = col * char_width
        cell_y = row * char_height

        char = chr(char_code)

        # Get the character's bounding box
        bbox = font.getbbox(char)
        if bbox:
            char_w = bbox[2] - bbox[0]
            # Center horizontally in cell
            offset_x = (char_width - char_w) // 2
            # For vertical positioning:
            # - bbox[1] is the top of the glyph relative to the draw position
            # - We want to draw at position such that the baseline is at cell_y + baseline
            # - Pillow's draw.text places text so that the baseline is at y + ascent
            # - So we draw at cell_y + 1 (padding) to position correctly
            draw_x = cell_x + offset_x - bbox[0]
            draw_y = cell_y + 1  # 1 pixel padding from top
            # Draw white text
            draw.text((draw_x, draw_y), char, font=font, fill=(255, 255, 255, 255))

    return {
        'image': image,
        'char_width': char_width,
        'char_height': char_height,
        'atlas_width': atlas_width,
        'atlas_height': atlas_height,
        'font_size': size,
        'baseline': baseline,
        'ascent': font_ascent,
        'descent': font_descent,
    }


def atlas_to_python_module(atlas_data, font_name, output_path):
    """Write atlas data as a Python module with embedded PNG.

    Args:
        atlas_data: Dict from generate_atlas()
        font_name: Name to use in the module
        output_path: Path to write the .py file
    """
    # Save image to PNG bytes
    img_bytes = io.BytesIO()
    atlas_data['image'].save(img_bytes, format='PNG', optimize=True)
    png_data = img_bytes.getvalue()

    # Encode as base64 for embedding
    b64_data = base64.b64encode(png_data).decode('ascii')

    # Generate Python module
    module_content = f'''# -*- coding: utf-8 -*-
"""Font atlas resource: {font_name} size {atlas_data['font_size']}
{LICENSE_NOTICE}
"""
# Generated by scripts/generate_font_atlas.py

import base64

font_name = {repr(font_name)}
font_size = {atlas_data['font_size']}
char_width = {atlas_data['char_width']}
char_height = {atlas_data['char_height']}
atlas_width = {atlas_data['atlas_width']}
atlas_height = {atlas_data['atlas_height']}
first_char = {FIRST_CHAR}
last_char = {LAST_CHAR}
chars_per_row = {CHARS_PER_ROW}
baseline = {atlas_data['baseline']}
ascent = {atlas_data['ascent']}
descent = {atlas_data['descent']}

# PNG image data (base64 encoded)
_png_base64 = (
'''

    # Split base64 into lines for readability
    line_length = 76
    for i in range(0, len(b64_data), line_length):
        chunk = b64_data[i:i+line_length]
        module_content += f'    {repr(chunk)}\n'

    module_content += ''')

def get_png_data():
    """Return the raw PNG data bytes."""
    return base64.b64decode(_png_base64)

def get_image():
    """Return a PIL Image object (requires Pillow)."""
    import io
    from PIL import Image
    return Image.open(io.BytesIO(get_png_data()))
'''

    with open(output_path, 'w') as f:
        f.write(module_content)

    return len(png_data)


def generate_atlas_index(sizes, font_name, output_path):
    """Generate an index module for loading font atlases.

    Args:
        sizes: List of generated font sizes
        font_name: Name of the font used
        output_path: Path to write the index module
    """
    module_content = f'''# -*- coding: utf-8 -*-
"""Font atlas index for shader-based text rendering.
{LICENSE_NOTICE}
"""
# Generated by scripts/generate_font_atlas.py

import importlib

# Font information
FONT_NAME = {repr(font_name)}

# Available font sizes
SIZES = {sorted(sizes)}

# Character mapping info
FIRST_CHAR = {FIRST_CHAR}
LAST_CHAR = {LAST_CHAR}
CHARS_PER_ROW = {CHARS_PER_ROW}


def get_atlas(size):
    """Get the atlas module for the specified size.

    Args:
        size: Font size in pixels

    Returns:
        Module with atlas data, or None if size not available
    """
    if size not in SIZES:
        return None

    module_name = f".font_atlas_{{size}}"
    try:
        return importlib.import_module(module_name, package=__name__)
    except ImportError:
        return None


def get_closest_atlas(size):
    """Get the atlas module closest to the specified size.

    Args:
        size: Desired font size in pixels

    Returns:
        Tuple of (actual_size, module)
    """
    if not SIZES:
        return None, None

    # Find closest size
    closest = min(SIZES, key=lambda s: abs(s - size))
    return closest, get_atlas(closest)


def get_available_sizes():
    """Return list of available font sizes."""
    return list(SIZES)
'''

    with open(output_path, 'w') as f:
        f.write(module_content)


def main():
    parser = argparse.ArgumentParser(
        description='Generate font texture atlases for OpenGLContext'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default='OpenGLContext/scenegraph/text/fonts',
        help='Output directory for atlas files'
    )
    parser.add_argument(
        '--sizes', '-s',
        default=','.join(str(s) for s in DEFAULT_SIZES),
        help=f'Comma-separated list of sizes (default: {",".join(str(s) for s in DEFAULT_SIZES)})'
    )
    parser.add_argument(
        '--font', '-f',
        default=None,
        help='Path to TTF font file (auto-detects DejaVu Sans Mono if not specified)'
    )
    parser.add_argument(
        '--preview', '-p',
        action='store_true',
        help='Save preview PNG files alongside Python modules'
    )

    args = parser.parse_args()

    # Parse sizes
    sizes = [int(s.strip()) for s in args.sizes.split(',')]

    # Find font
    font_path = args.font
    font_name = "DejaVu Sans Mono"

    if font_path is None:
        font_path = find_dejavu_font()
        if font_path:
            print(f"Found DejaVu Sans Mono: {font_path}")
        else:
            font_path = find_monospace_font()
            if font_path:
                font_name = os.path.splitext(os.path.basename(font_path))[0]
                print(f"DejaVu Sans Mono not found, using fallback: {font_path}")
            else:
                print("Error: No suitable monospace font found.")
                print("Please install DejaVu fonts or specify a font with --font")
                sys.exit(1)
    else:
        if not os.path.isfile(font_path):
            print(f"Error: Font file not found: {font_path}")
            sys.exit(1)
        font_name = os.path.splitext(os.path.basename(font_path))[0]

    # Create output directory
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    # Generate atlases for each size
    generated_sizes = []
    total_bytes = 0

    for size in sizes:
        print(f"Generating {size}px atlas...", end=' ')

        try:
            atlas_data = generate_atlas(font_path, size)

            # Write Python module
            module_name = f"font_atlas_{size}.py"
            module_path = os.path.join(output_dir, module_name)
            png_size = atlas_to_python_module(atlas_data, font_name, module_path)

            # Optionally save preview PNG
            if args.preview:
                preview_path = os.path.join(output_dir, f"font_atlas_{size}.png")
                atlas_data['image'].save(preview_path)

            generated_sizes.append(size)
            total_bytes += png_size

            print(f"OK ({atlas_data['atlas_width']}x{atlas_data['atlas_height']}, "
                  f"{atlas_data['char_width']}x{atlas_data['char_height']} per char, "
                  f"{png_size} bytes)")

        except Exception as e:
            print(f"FAILED: {e}")
            import traceback
            traceback.print_exc()

    # Generate index module
    if generated_sizes:
        index_path = os.path.join(output_dir, "__init__.py")
        generate_atlas_index(generated_sizes, font_name, index_path)
        print(f"\nGenerated index: {index_path}")

    print(f"\nGenerated {len(generated_sizes)} atlases, total {total_bytes} bytes")
    print(f"Output directory: {output_dir}")


if __name__ == '__main__':
    main()
