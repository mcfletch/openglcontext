# What is in these pictures, and on what terms

Every picture under `docs/images/` is a render this project produced. The
*render* is ours; what is **in** the render carries its own terms, and this file
records them.

Most of these are the Khronos glTF sample models, which is what the engine is
held to for conformance (`tests/unit/test_gltf_conformance.py`). The gallery
sets are drawn from renders already blessed as regression baselines, so what a
reader sees on a page is the same picture the test suite compares against.

`manifest.toml` carries a `licence` field on every entry, and
`tools/doc_images.py --check` fails an entry without one.

## The rule

A licence attaches to the picture, not to the site it appears on, so a page may
show a picture under different terms from the page. That is not a reason to be
careless about which ones we host:

- **Anything permissive — CC0, public domain, CC-BY** — is rendered into
  `docs/images/` and credited below. CC-BY asks for attribution and nothing
  else; this file is the attribution.
- **Anything restricted — non-commercial, share-alike, or a bespoke licence** —
  is not rendered into this repository. Where such a picture is wanted, it
  belongs in the
  [reference-images](https://github.com/mcfletch/openglcontext-reference-images)
  repository, which already holds the conformance renders and can carry a
  copyleft subdirectory without that reaching anything else, and is referenced
  from here rather than copied.

## Our own work

| Picture | Terms |
|---|---|
| `gallery/showcase/glisteel-*.jpg` | [GLinting Steel](https://github.com/mcfletch/glisteel), BSD-3-Clause, on CC0 generated assets |
| `gallery/showcase/forest-walk.jpg` | the forest demo, BSD-3-Clause; assets per its own `ASSET-LICENSES.md` |
| `gallery/showcase/marble-board.jpg` | the marble demo, MIT, on CC0 generated assets |
| `gallery/showcase/parthenon.jpg`, `parthenon/*.jpg` | the Parthenon model, CC0 |
| `demos/*.jpg`, `extrusions/*.png`, `shadow_demo.jpg`, `text_simple.png` | BSD-3-Clause; scenes built by the demo scripts in `tests/` |
| `toronto-3dtiles.jpg` | City of Toronto 3D massing data, Open Government Licence &mdash; Toronto |

## Khronos glTF sample models

Rendered by this project; each model is its authors' work under the licence
named. The source of each is the
[glTF-Sample-Assets](https://github.com/KhronosGroup/glTF-Sample-Assets)
repository, where the full legal notice for a model lives in its own `README.md`.

| Model | Terms |
|---|---|
| AntiqueCamera | &copy; 2018 UX3D &mdash; CC0 1.0 |
| BarramundiFish | public domain &mdash; CC0 1.0 |
| BoomBox | public domain &mdash; CC0 1.0 |
| ClearCoatCarPaint | public domain &mdash; CC0 1.0 |
| Corset | &copy; 2017 UX3D &mdash; CC0 1.0 |
| FlightHelmet | public domain &mdash; CC0 1.0 |
| GlassVaseFlowers | public domain &mdash; CC0 1.0 |
| Lantern | &copy; 2017 Microsoft, &copy; 2018 Frank Galligan &mdash; CC0 1.0 |
| SciFiHelmet | public domain &mdash; CC0 1.0 |
| ToyCar | public domain &mdash; CC0 1.0 |
| WaterBottle | public domain &mdash; CC0 1.0 |
| ABeautifulGame | &copy; 2020 ASWF, &copy; 2022 Ed Mackey &mdash; CC-BY 4.0 |
| CarConcept | &copy; 2024 Darmstadt Graphics Group &mdash; CC-BY 4.0 |
| ChronographWatch | &copy; 2025 Darmstadt Graphics Group &mdash; CC-BY 4.0 |
| CommercialRefrigerator | &copy; 2025 Darmstadt Graphics Group, Sean Thomas &mdash; CC-BY 4.0 |
| GlamVelvetSofa | &copy; 2021 Wayfair &mdash; CC-BY 4.0 |
| GlassHurricaneCandleHolder | &copy; 2021 Wayfair &mdash; CC-BY 4.0 |
| IridescentDishWithOlives | &copy; 2020 Wayfair &mdash; CC-BY 4.0 |
| MaterialsVariantsShoe | &copy; 2021 Shopify &mdash; CC-BY 4.0 |
| MetalRoughSpheres | &copy; 2017 Analytical Graphics &mdash; CC-BY 4.0 |
| MosquitoInAmber | &copy; 2018, 2019 Sketchfab &mdash; CC-BY 4.0 |
| SheenWoodLeatherSofa | &copy; 2024 Darmstadt Graphics Group &mdash; CC-BY 4.0 |
| StainedGlassLamp | &copy; 2021 Wayfair &mdash; CC-BY 4.0 |
| SunglassesKhronos | &copy; 2024 Darmstadt Graphics Group &mdash; CC-BY 4.0 |
| Fox (`crowd_demo`) | &copy; PixelMannen, tomkranis &mdash; CC-BY 4.0 |

The Khronos and vendor logos that appear on several of these models are
trademarks of their owners, used as they arrive in the sample model.

## Deliberately not here

These sample models render correctly and are covered by the conformance suite;
none is used as a documentation picture, because the licence on the model is
narrower than the pages showing it should carry.

| Model | Why |
|---|---|
| Sponza | Cryengine Limited License Agreement |
| Duck | SCEA Shared Source License 1.0 |
| DragonAttenuation, DragonDispersion | Stanford Graphics Library terms on the dragon mesh |
| VirtualCity | 3DRT licence, permitting glTF testing only |

**DamagedHelmet** belongs in this table and is not yet out of the pages: its
mesh is CC-BY 4.0, but its textures are &copy; 2016 theblueturtle\_ under
**CC-BY-NC 4.0**, a non-commercial licence. It is the lead image of
`pbr.html` and appears twice in `gltf.html`, from before this file existed. The
substitutions are ready to hand &mdash; `SciFiHelmet` and `FlightHelmet` are both
CC0 and show the same features &mdash; and making them is a decision to take
rather than a change to slip in.

**twig-bb** has no picture here. Its levels are built from downloaded OpenArena
and ioquake3 content under GPL and CC-BY-SA terms, so a screenshot of one is a
derivative of that art. A twig-bb picture wants either a frame on the game's own
BSD-licensed furniture, or a home in the reference-images repository under those
terms.
