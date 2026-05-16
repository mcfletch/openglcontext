# OpenGLContext Project Plan

## Summary

| Plan | Status | Description |
|------|--------|-------------|
| [CODE-REVIEW-2026-01.md](CODE-REVIEW-2026-01.md) | Complete | Comprehensive code review with recommendations |
| [PYTHON-MODERNIZATION.md](PYTHON-MODERNIZATION.md) | Planned | Modernize to require Python 3.10+ and remove Python 2.7 compatibility |
| [GPU-NURBS-TESSELLATION.md](GPU-NURBS-TESSELLATION.md) | Planned | GPU-based NURBS rendering using tessellation shaders |
| [SHADER-BASED-VRML97.md](SHADER-BASED-VRML97.md) | Core Complete | Shader-based rendering pass implementing VRML97 lighting model |
| [CORE-PROFILE-COMPATIBILITY.md](CORE-PROFILE-COMPATIBILITY.md) | Planned | Make flatcore.py actually core-profile compatible |
| [SELECTION-OPTIMIZATION.md](SELECTION-OPTIMIZATION.md) | In Progress | Optimize selection/picking for better performance |
| [ORDER-INDEPENDENT-TRANSPARENCY.md](ORDER-INDEPENDENT-TRANSPARENCY.md) | Planned | Implement order-independent transparency to eliminate sorting artifacts |
| [TESTSUITE-IMPROVEMENTS.md](TESTSUITE-IMPROVEMENTS.md) | **In Progress** | Automated pytest suite with subprocess isolation, visual regression, and HTML reports |

## Recent Progress (January 2026)

### Test Suite Implementation

The automated test suite is now functional with the following capabilities:

- **118 visual test scripts** run with screenshot capture and comparison
- **129 total test scripts** including non-visual functionality tests
- **HTML report generation** at `tests/report.html` with side-by-side image comparisons
- **Coverage collection** from subprocess test runs (currently ~9% coverage)
- **Auto-exit mechanism** via `OPENGLCONTEXT_AUTO_EXIT_FRAMES` environment variable
- **Screenshot capture** via `OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR` and `OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME`
- **FPS display toggle** via `OPENGLCONTEXT_DISABLE_FPS_DISPLAY` for clean screenshots

Script categorization:

- Platform-specific scripts (Windows/WGL, wxPython, pygame) with automatic skip logic
- Non-visual scripts (glget.py, boundingvolume.py, etc.) excluded from visual regression
- Randomized scripts (particles, starfield) marked with `expect_visual_diff`

Test results from last run: 247 passed, 7 failed, 6 skipped

### Known Issues

- `solid_font.py` - Font provider registry issue (`fontNameFromStyle` on None)
- `glutmousewheel.py` - GLUT-specific test failing
- `savepostscript.py` - PostScript save functionality
- `shader_instanced*.py` - Legacy GLSL compatibility issues on some drivers
