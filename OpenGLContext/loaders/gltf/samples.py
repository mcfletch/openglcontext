"""Khronos glTF-Sample-Assets catalogue helpers.

Resolves sample-model URLs, parses the upstream ``Models.md`` catalogue, and
caches reference screenshots. Fetching and caching go through the
security-hardened :mod:`resolver`; :func:`load_sample` defers to the package's
``load_gltf_url``. The loader package re-exports these names, so
``gltf.SAMPLE_MODELS`` / ``gltf.load_sample`` etc. resolve.
"""

import urllib.parse
from typing import TYPE_CHECKING, Optional

from OpenGLContext.loaders.resolver import _fetch_url, fetch_to_cache

if TYPE_CHECKING:
    from OpenGLContext.loaders.gltf.scene import GLTFScene

# Khronos glTF-Sample-Assets. The older glTF-Sample-Models repo is deprecated
# (frozen; newer models 404 there), so we resolve against the current assets repo.
# Its models live under Models/<Name>/, and the catalogue is Models/Models.md.
SAMPLE_MODELS_BASE = (
    'https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models'
)
SAMPLE_MODELS = [
    'Box', 'BoxTextured', 'BoxVertexColors', 'Duck', 'BoomBox', 'Avocado',
    'BarramundiFish', 'Corset', 'Lantern', 'WaterBottle', 'DamagedHelmet',
    'MetalRoughSpheres', 'NormalTangentTest', 'OrientationTest', 'Suzanne',
    'ToyCar', 'AntiqueCamera', 'AlphaBlendModeTest',
    # KHR_materials_transmission (glass) showcase assets
    'IridescentDishWithOlives', 'MosquitoInAmber', 'DragonAttenuation',
]


SAMPLE_README_URL = SAMPLE_MODELS_BASE + '/Models.md'


def sample_model_url(name: str) -> str:
    """URL of a Khronos sample model's glTF-Binary file."""
    return '%s/%s/glTF-Binary/%s.glb' % (SAMPLE_MODELS_BASE, name, name)


def fetch_sample_catalog(cache_dir: Optional[str] = None) -> list[dict[str, Optional[str]]]:
    """Parse the Khronos 2.0 README.md into the full model catalogue.

    Returns a list of dicts ``{name, display, screenshot_url}`` -- every model
    listed in the repository, each with the URL of its reference screenshot (for
    side-by-side comparison).

    Each Models.md row opens with a model link and an inline screenshot, in
    either of the two forms the file has used -- Markdown image syntax::

        | [Display](Dir/README.md)<br>[![Display](Dir/screenshot/screenshot.jpg)](Dir/README.md)... | description |

    or an HTML tag, which is what it carries now::

        | [Display](Dir/README.md)<br><a href="Dir/README.md"><img src="Dir/screenshot/screenshot.png" width="250px"></a>... |

    Both are read, because the file is upstream's and has changed under us once
    already: matching only one leaves every ``screenshot_url`` None, which is a
    catalogue that still looks complete.

    ``name`` is the model's directory (url-decoded); the screenshot path is
    relative to the Models/ directory, so it is joined onto ``SAMPLE_MODELS_BASE``.
    """
    import re
    text = _fetch_url(SAMPLE_README_URL, cache_dir).decode('utf-8', 'replace')
    link = re.compile(r'\|\s*\[([^\]]+)\]\(([^)]+?)/README\.md\)')
    shot_res = (
        re.compile(r'!\[[^\]]*\]\(([^)]+?/screenshot/[^)]+)\)'),
        re.compile(r'<img\s[^>]*src="([^"]+?/screenshot/[^"]+)"', re.IGNORECASE),
    )
    rows = []
    for line in text.splitlines():
        if not line.startswith('| ['):
            continue
        m = link.match(line)
        if not m:
            continue
        display = m.group(1).strip()
        name = urllib.parse.unquote(m.group(2).strip('/').split('/')[-1])
        sm = None
        for pattern in shot_res:
            sm = pattern.search(line)
            if sm:
                break
        screenshot_url = None
        if sm:
            shot = urllib.parse.unquote(sm.group(1).strip()).lstrip('./')
            screenshot_url = '%s/%s' % (SAMPLE_MODELS_BASE, shot)
        rows.append({
            'name': name,
            'display': display,
            'screenshot_url': screenshot_url,
        })
    return rows


def reference_screenshot_url(name: str, cache_dir: Optional[str] = None) -> Optional[str]:
    """URL of a model's Khronos reference screenshot, or None if not catalogued."""
    for entry in fetch_sample_catalog(cache_dir):
        if entry['name'] == name:
            return entry.get('screenshot_url')
    return None


def cache_reference_screenshot(name: str, cache_dir: Optional[str] = None) -> Optional[str]:
    """Download (once) a model's Khronos reference screenshot to the disk cache.

    Returns the local file path, or None if the model has no catalogued
    screenshot. The image goes through the resolver's sha1-keyed cache, so a
    second call for the same model makes no network request -- the regression
    report can embed the upstream reference offline after the first run.
    """
    url = reference_screenshot_url(name, cache_dir)
    if not url:
        return None
    return fetch_to_cache(url, cache_dir)


#: The variants a Khronos sample may publish, in the order to prefer them.  The
#: self-contained binary first; then ``glTF``, whose buffers and textures are
#: resolved over the network; then the embedded form.  **Not every sample ships
#: all three** -- Sponza publishes no ``.glb`` at all -- which is why a caller
#: holding one URL still has to be able to try the others.
SAMPLE_VARIANTS = (
    ('glTF-Binary', '.glb'),
    ('glTF', '.gltf'),
    ('glTF-Embedded', '.gltf'),
)


def sample_variant_urls(name: str) -> list:
    """Every URL a Khronos sample of this name might be published at."""
    return ['%s/%s/%s/%s%s' % (SAMPLE_MODELS_BASE, name, directory, name, suffix)
            for directory, suffix in SAMPLE_VARIANTS]


def sample_name_from_url(url: str) -> Optional[str]:
    """The sample this URL names, or None if it is not a Khronos sample URL.

    Answering None for anything else is the point: guessing at sibling paths on
    somebody else's server would be inventing URLs they never published.
    """
    if not url.startswith(SAMPLE_MODELS_BASE + '/'):
        return None
    rest = url[len(SAMPLE_MODELS_BASE) + 1:].split('/')
    return rest[0] if len(rest) >= 2 else None


def load_sample_url(url: str, cache_dir: Optional[str] = None) -> "GLTFScene":
    """Load a URL, trying the other variants if it names a Khronos sample.

    A library entry carries a URL rather than a name, and
    :func:`sample_model_url` names the ``.glb`` because that is the one to
    prefer -- so a sample that publishes no ``.glb`` answered 404 and could not
    be opened at all.  Anything that is not a sample URL is loaded exactly as
    given and its failure is its own.
    """
    from OpenGLContext.loaders.gltf import load_gltf_url
    name = sample_name_from_url(url)
    candidates = [url] if name is None else (
        [url] + [other for other in sample_variant_urls(name) if other != url])
    last_error: Optional[BaseException] = None
    for candidate in candidates:
        try:
            return load_gltf_url(candidate, cache_dir)
        except Exception as err:
            last_error = err
    raise last_error if last_error else IOError("could not load %r" % url)


def load_sample(name: str, cache_dir: Optional[str] = None) -> "GLTFScene":
    """Load a Khronos sample model by directory name, trying each glTF variant.

    Prefers the self-contained ``glTF-Binary`` (.glb); falls back to ``glTF``
    (external buffers/textures resolved over the network) and ``glTF-Embedded``.
    """
    return load_sample_url(sample_model_url(name), cache_dir)
