# Content packs: shipping data outside the wheel

**Status: the engine facility, the documentation and the publishing side have
landed (work items 1–4 and 8); the twig-bb move is open. glisteel's side is
done — `./release-assets.py` bakes, archives, digests, writes the registry,
installs into this machine's store and pushes to the release tag.**

`OpenGLContext/contentpacks/` is in the tree: `pack.py`, `catalog.py`,
`store.py`, `archive.py`, `fetch.py` and `publish.py`, at 100% statement
coverage over 213 cases, ruff and mypy clean. The fetch cases run against a real HTTP server on
the loopback address rather than a mocked resolver, so what is checked is that
the download, the cap, the digest and the unpacking compose into one pack on
disk.

Five things were found writing it, recorded in place below. Two were holes and
are closed: **an added registry could write over a shipped pack's content**,
since only the *key* was namespaced and `directory` was a name a registry chose
freely; and **nothing bounded what an archive unpacked to** — 1 MB on the wire
expanded to 1 GB on disk with nothing refusing it. Three are facts worth
keeping: an uncompressed tarball has no integrity of its own, the resolver
states an over-cap resource as a `ValueError` where every other failure here is
an `IOError`, and `companions` was renamed `needs` after the name misled its
first reader.

A game built on this engine is code plus data, and the two want different
distribution. The code is small, versioned, and belongs on PyPI. The data is
tens to hundreds of megabytes, changes on its own cadence, and belongs
somewhere that serves large files well. This plan puts a content-pack facility
in the engine so a game declares what it needs, and the engine fetches,
verifies, unpacks and finds it.

## Problem

Two games in this workspace carry their art inside the wheel:

| distribution | art in the package |
|---|---|
| `twig-bb` | 15 MB — characters 6.2 MB, weapons 4 MB, pickups |
| `glisteel` | 1.3 MB — the hero car and five traffic cars |

Neither can grow. A glisteel track is 57 MB baked at the default extent, and a
release wanting three of them is 150 MB of data against 300 KB of Python. That
is not a wheel, and PyPI is not the place to find out.

`twig-bb` already solves this for *third-party* content: `catalog.py`,
`assetpack.py`, `download.py` and `fetcher.py` fetch 18 declared packs — up to
428 MB each — with consent, progress, cancellation, licence text and an
acknowledgements screen generated from the catalogue. `glisteel` has none of
it, and `marble-demo` will want the same thing. Per the workspace rule that
features live in the engine, one copy belongs here rather than three copies in
the games.

## What already exists here

- `OpenGLContext/loaders/resolver.py` — `fetch_to_cache(url, cache_dir,
  max_bytes, progress, cancel)`, an origin-locked redirect handler, a byte cap
  applied while streaming, atomic writes into a per-user cache, and
  `purge_cache`. The network layer is done.
- `OpenGLContext/userpaths.py` — `appdatadirectory()`, which is where every
  per-user file in this stack already goes.
- `OpenGLContext/loaders/cc0.py` — the narrow case: named ambientCG materials,
  fetched once, cached, with a provenance manifest.

What is missing is the layer above: a *declared set* of packs, the consent and
progress a large download needs, and the question "is it already here".

## The shape

A new `OpenGLContext/contentpacks/` package. The split is by what each piece
answers, and each is testable without a window or a network.

| module | what it is |
|---|---|
| `pack.py` | `ContentPack`, one pack as a frozen value |
| `catalog.py` | reading and validating a registry file; `BadCatalog` |
| `store.py` | `ContentStore` — where an application's packs live, and which are installed |
| `archive.py` | `extract()` for zip and tar, refusing any entry that escapes the destination; `write()` and `digest()` for building one; `check_digest()` |
| `fetch.py` | `fetch_pack()`, `fetch_registry()`, `wanted_for()`, `missing_base()`, and `FetchJob` for running one off the frame loop |
| `publish.py` | `install()` a built pack into a store, and `push()` the files to a release |

### What keeps publishers apart

Three rules, each closing a way the others do not. The first was there from the
start; the second and third were found by asking what stops two packs colliding,
and the answer was "nothing".

1. **Keys are namespaced** and a registry declares only its own, so an added one
   cannot be resolved in place of a shipped pack.
2. **Content is partitioned by namespace on disk**,
   `<store>/packs/<namespace>/<directory>`. Only the *key* is namespaced by the
   format; `directory` is a name a registry chooses freely — so an added
   registry could declare `"directory": "ashdown"` under a key it is entitled to
   and write over a shipped track's tiles. Demonstrated before it was fixed.
   Partitioning makes it impossible rather than forbidden, and leaves two packs
   of the *same* publisher free to share a tree on purpose, which is how a world
   and its art arrive as one directory. The searched directories
   (`OPENGLCONTEXT_CONTENT`) are laid out the same way, or they would be the
   same hole.
3. **One namespace comes from one registry.** Nothing proves who owns a
   namespace — there is no registrar. What is enforceable is that everything
   under one came from one file, so `merge()` refuses two registries claiming
   one, and trusting a second becomes a decision rather than something quiet.

Registries themselves are kept by a key derived from the whole URL: two sources
both publishing `registry.zip` would otherwise be one file in the store, the
second fetch replacing the first and every pack it had offered.

**`needs` is symmetric.** It resolves against every pack loaded, in either
direction, and nothing privileges the shipped registry — a third-party track may
name the shipped forest art rather than carry a copy. A key resolves to the
entry in *its own* registry, so the URL fetched and the digest checked are that
publisher's whoever named the key. Where it lands is under the pack that named
it — a world resolves its own paths against its own root, so art it is
incomplete without has to be inside it — and the download is cached, so four
tracks naming one art pack is one transfer and four extractions.

### Two limits, not one

A cap on the download says nothing about the unpacking. A megabyte of zeroes
deflates to almost nothing, so an archive well inside any transfer limit can
write hundreds of gigabytes — measured at 1 MB in, 1 GB out, refused by nothing,
before this was added. `archive.unpacked_limit()` bounds what a pack may write
at `MAX_EXPANSION` (10) times its declared size, floored at 64 MB, and
`MAX_ENTRIES` bounds the count at 100,000 since a million empty files costs
nothing to send. Ten is generous — a baked glisteel track is 57 MB unpacked
against 48 MB compressed, a ratio of 1.2 — and nowhere near the thousandfold an
archive of zeroes reaches. The sizes come from the archive's own headers and are
judged before anything is created, so a refusal costs no disk.

Three things the cases turned up, each recorded where it belongs:

- **An uncompressed tarball has no integrity of its own.** Truncated at a member
  boundary it reads as a shorter archive, and the files that never arrived are
  simply absent — no error anywhere. A compressed one raises (`EOFError` from
  gzip and xz, a `tarfile` error from bzip2). This is the argument for `sha256`
  stated as a fact rather than a preference.
- **One exception family.** The resolver states an over-cap resource as a
  `ValueError`, which is right for a size limit in general and wrong for one of
  several ways a single download can fail; `fetch.TooLarge` is an `IOError` like
  `DigestMismatch`, `UnsafeArchive` and `UnreadableArchive`, so a caller
  reporting "the download did not work" catches one thing. `Cancelled` is
  deliberately outside it: a decision is not a failure.
- **`companions` became `needs`.** The word reads as "things that go alongside"
  and the field means "this pack is incomplete without these" — twig-bb's
  Unvanquished maps carry no art and name the texture packages they draw from.
  Declaring it in the registry rather than reading the map's own `DEPS` after
  download is what lets the whole set be sized, consented to and fetched as one,
  in parallel if a fetcher wants to.

`twig_bb.assetpack`, `twig_bb.catalog`, `twig_bb.fetcher` and the general half
of `twig_bb.download` move here close to unchanged; they are the design this
adopts. What stays in twig-bb is what knows about Quake: `content_roots`,
`find_map`, `list_maps`, `_choose`, `NoMapFound`, `AmbiguousMap`,
`parse_pack_target`, `resolve_target` and the `.pk3`/`.dpk` extension table.

### `ContentPack`

```python
@dataclass(frozen=True)
class ContentPack:
    key: str                 # namespaced; see "Registries that can grow"
    title: str
    url: str
    directory: str           # a name, under <store>/packs/<namespace>/
    archive: str             # 'zip' or 'tar'
    approximate_bytes: int   # shown before consent; sets the fetch cap
    copyright: str           # mandatory; the notices screen is generated from it
    marker: str              # a path proving it is unpacked; '' means non-empty
    sha256: str = ''         # exact digest, where the publisher controls the bytes
    base: bool = False       # the application cannot start without it
    family: str | None = None
    companions: tuple[str, ...] = ()
    requires: str = ''       # a PEP 440 specifier on the consuming application
    notes: str = ''
    url_page: str = ''
    preview: str = ''        # a picture of it, resolved against the registry
```

`copyright` is required and validation is strict — an entry with a mistyped key
is refused rather than skipped, because a pack silently dropped for a typo is
one nobody can download and nobody can see the absence of. Both rules are
twig-bb's and both carry over.

Two fields are new.

**`sha256`** is what changes when the publisher owns the bytes. twig-bb's packs
point at other people's servers, where a file can be replaced under the same
URL and only an approximate size is honest. A first-party pack on our own
release is a fixed artefact, so the digest is knowable and checking it makes a
truncated or substituted download a refusal rather than a rendering fault
somewhere later. Required for first-party packs, empty for the rest.

**`requires`** is a specifier on the application version, so a track baked
against a later world format is declined by an older game with a sentence
rather than a traceback.

**`base`** marks what the application cannot start without, which is what the
first run fetches before it shows a menu. A base pack must carry a `sha256` and
may not name a `family`: it is the floor, not a choice among alternatives.

**`preview`** is a picture of what the pack holds. A chooser offering packs
nobody has downloaded has nothing to show them *with*, since a pack's own art is
inside the archive being chosen. It is declared relative to the registry and
comes back resolved to a file on this machine; `.png`, `.jpg` and `.jpeg` only,
never a path outside the registry, and one that is named but absent gives a pack
with no picture rather than a registry that will not load.

### A registry is a document and its pictures

So a registry handed around as one file is a **zip of both** — `packs.json` at
its top and the thumbnails beneath it. `catalog.load_bundle(path, into)`
extracts it through the same reader a content pack goes through and reads the
manifest inside; `catalog.load(path)` takes the loose form, where the pictures
sit beside the JSON. Either way a `preview` resolves against the registry's own
location, so the two are the same registry.

That is what makes an added registry worth pointing at:
`fetch.fetch_registry(url, store)` downloads the bundle — a document and some
thumbnails, capped at `REGISTRY_LIMIT` rather than at anything a content pack
would get — and hands back packs with pictures already on disk. **A chooser can
show third-party content before downloading any of it**, and the store keeps the
bundle so a later run finds it without being pointed at it again.

### `ContentStore`

```python
store = ContentStore('glisteel')          # under appdatadirectory()
store.root_for(pack)                      # path, or None if not fetched
store.directory_for(pack)                 # where it would go
store.installed(packs)                    # those already present
```

Named by application, because two games on one machine share the engine's
download cache but not their content. The store creates nothing until something
is written into it: asking where a file belongs is not a reason to make a
directory.

### `FetchJob`

Carried over whole, including its rule: the worker thread writes under a lock
and `poll()` — called once a frame — is the only place that reads it, so a
caller needs no lock of its own. One progress bar for the whole job rather than
one per pack, weighted by the sizes the user consented to.

## Where the bytes live

**Decided: release assets on the game's own repository**, under a tag that
carries content and nothing else (`content-v1`, `content-v2`), never committed
to git. The alternative considered was a content repository per game.

- Release assets are not in git history, so a clone of `glisteel` stays the size
  of its source either way. The usual reason to split content out — repository
  weight — does not apply.
- One repository means the catalogue and the artefacts are tagged, reviewed and
  moved together. Two repositories means two release processes and a new way for
  a `packs.json` to name a URL that the other repository has retired.
- GitHub allows 2 GB per asset with no count limit and no bandwidth billing.
  Three tracks and a shared art pack is around 150 MB, which is not near
  anything.
- The URL form is stable and needs no new registry field:
  `https://github.com/<owner>/<repo>/releases/download/<tag>/<file>`.

A separate repository earns its keep when the content has a different licence, a
different cadence, or a different set of contributors from the code — which is
the case for community-contributed tracks and not for the ones we bake. The
registry format already supports it, because a pack entry carries a whole URL:
if `glisteel-tracks` is wanted later, nothing here changes.

## Registries that can grow

The catalogue is a data file, not a list in Python, so a pack can be added or a
size corrected without a code change. That stays. Two things get added.

**The shipped registry names the first-party packs**, so a fresh install can
offer them with no bootstrap fetch. A registry that had to be downloaded first
would mean two round trips before anything is shown and one URL that can never
be changed.

**Extra registries merge in**, from `--registry <path-or-url>` and from any
`*.json` in `<store>/registries/`. This is what lets a community track set, a
LAN mirror, or a work-in-progress bake be offered by the same chooser without a
release.

A merged registry is untrusted input — it names URLs the application will fetch
— so:

- it is validated exactly as strictly as the shipped one;
- keys are namespaced (`glisteel/ashdown`, `contrib.someone/hillclimb`), and a
  registry may only declare keys under its own namespace, so nothing outside the
  package can shadow a first-party pack;
- `sha256` on an entry is honoured, and its absence is shown as such on the
  consent screen rather than passed over.

## The first run

**Decided: a game's own art is a pack, fetched on first load.** PyPI carries
code, and that includes the art a game cannot start without — twig-bb's 15 MB of
characters and weapons, glisteel's cars — not only the optional content on top
of it.

So a first run reaches the network before it can draw. The game asks, with the
size and the terms, and fetches a **base pack** its registry marks as such: one
download, before the menu, rather than a stall at the first frame that needs a
model. A base pack is the application's own, always digested, and never
optional — a game with none of it has nothing to show.

That makes the escape hatch below part of the feature rather than a convenience:

## Offline, tests and CI

A machine that cannot reach the network, or should not, still has to run:

- `OPENGLCONTEXT_CONTENT` names a directory searched before the store, so a
  packaged build, a test suite, an air-gapped machine or a CI job points at a
  local copy and fetches nothing.
- A suite that needs content declares which packs, and skips with a reason
  naming them when neither the store nor `OPENGLCONTEXT_CONTENT` has them —
  rather than failing in a way that reads as a defect in the code under test.
- The engine's own suite covers the facility with a local HTTP server and
  fixture archives, so nothing in CI reaches the internet.

## Work

1. ✅ `OpenGLContext/contentpacks/` — the five modules, with tests: validation
   refusals, safe extraction (absolute paths, `..`, symlinks, tar device
   entries), digest mismatch, cap exceeded, cancel,
   resume-as-already-installed, registry bundles and previews, and a `FetchJob`
   driven from a frame loop.
2. ✅ `OPENGLCONTEXT_CONTENT` and the store's search order.
3. ✅ `missing_base(packs, store)` — every base pack not here, and whatever
   those are incomplete without, since half a floor is not a floor. The screen
   an application shows before its menu is the application's; the engine owns
   the decision and the fetch.
4. ✅ Documentation: [docs/contentpacks.html](../docs/contentpacks.html) for
   application authors — the registry schema, every field, the units of
   `approximate_bytes`, where packs land on each platform, the base-pack rule,
   the environment variable and the publishing side.
5. Move twig-bb onto it — `twig_bb.assetpack`/`catalog`/`fetcher` become
   re-exports or go, `download.py` keeps only the Quake-specific half, and the
   18 existing entries gain namespaced keys.
6. Move `twig_bb/assets/` (15 MB) to a base pack on twig-bb's own releases.
   Declared, built and installable — `twig-bb/art` is in the registry and
   twig-bb's `./release-assets.py` builds it, digests it and can push it. What
   is left is the release itself, and then one line of `pyproject.toml` taking
   the copy out of the wheel.
7. ✅ Glisteel's side is its own plan,
   [TRACK-PACKS.md](https://github.com/mcfletch/glisteel/blob/main/plans/TRACK-PACKS.md).
8. ✅ The publishing side: `archive.write` and `contentpacks/publish.py`, so
   building a release is one command per project rather than a script per
   project (see below).

Order matters only in that 1–4 precede 5–7; 5 and 7 are independent.

## Publishing, and testing a release before there is one

A pack is built, installed and attached by the engine, because three
applications here publish content and each had written the same fifteen lines.

- **`archive.write(directory, path)`** makes the `.tar.gz` a release carries.
  Both copies of the hand-written version fixed their tar entries' timestamps
  and left the gzip container's own, so the digest moved between builds of
  identical content — the same size, a different hash — and a digest that
  nothing can reproduce is a digest nothing can check a rebuild against. Sorted
  entries, `EPOCH` on every entry and on the container, no owner, one mode.
- **`publish.install(pack, store, archives)`** puts what was just built where a
  download would have left it: digest checked, unpacking bounded, content under
  the store. An application then runs against content no release carries, which
  is how the two defects above were found.
- **`publish.push(repository, tag, paths)`** attaches them through the GitHub
  CLI, creating the release at that tag the first time and replacing its assets
  afterwards. The repository is read off the registry's own URL rather than
  named a second time.

**What a pack `needs` unpacks into it, not beside it.** A baked world resolves
every path inside it against its own root, so the art four glisteel tracks share
belongs under each of them; the registry gives that art a `directory` of its
own, and a fetched track drove through a treeless world until this was fixed.
`store.directory_for(pack, within=...)`, `store.root_for(pack, within=...)` and
`fetch.wanted_for(chosen, packs, store)` are that relationship — the archive is
downloaded once and cached, and what repeats is the extraction. It costs a copy
of the art per track, which is what keeps a world one directory that can be
moved, copied or deleted whole. `catalog.offered(packs)` is the other half: a
pack that exists only to be needed is not one to put in a download screen, since
it would never read as arrived.

## What this does not do

- It does not deduplicate across packs. Two packs carrying the same file store
  it twice; the alternative is a content-addressed store, which is a larger
  design and buys little at this scale.
- It does not patch. A changed pack is a new pack at a new URL, and the old one
  is deleted or left alone.
- It does not mirror or fall back between hosts. One URL per pack, and a failure
  is reported to the user.
