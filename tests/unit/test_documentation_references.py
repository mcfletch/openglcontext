"""Every pointer the documentation offers leads somewhere.

A docstring that names a module, a page that names a console command, a
sentence that sends the reader to a demo script -- each is a promise, and a
reader who follows one and lands nowhere has been told the rest of the page is
not to be trusted either.  Reorganising a package moves the targets silently,
so the pointers are checked mechanically rather than by remembering.
"""
import ast
import re
import tomllib

import pytest

from OpenGLContext.testing.paths import tests_root

ROOT = tests_root(__file__).parent
PACKAGE = ROOT / 'OpenGLContext'
DOCS = ROOT / 'docs'


def _modules():
    """Every importable dotted name inside the package."""
    names = set()
    for path in PACKAGE.rglob('*.py'):
        relative = path.relative_to(ROOT).with_suffix('')
        parts = relative.parts
        if parts[-1] == '__init__':
            parts = parts[:-1]
        names.add('.'.join(parts))
    return names


def _docstrings():
    """(path, lineno, text) for every docstring in the package."""
    for path in sorted(PACKAGE.rglob('*.py')):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
        except SyntaxError:                     # pragma: no cover - none today
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            text = ast.get_docstring(node)
            if text:
                yield path.relative_to(ROOT), getattr(node, 'lineno', 1), text


class TestDocstringsNameModulesThatExist:
    """A dotted ``OpenGLContext.…`` in prose has to resolve to a module.

    The reference may name a class or a function inside the module, so the
    check is that *some* prefix of the dotted name is a module -- which is
    exactly what fails when a module moves to a sub-package.
    """

    def test_every_reference_resolves(self):
        modules = _modules()
        broken = []
        for path, lineno, text in _docstrings():
            for match in re.findall(r'OpenGLContext(?:\.[A-Za-z_]\w*)+', text):
                parts = match.split('.')
                if not any('.'.join(parts[:n]) in modules
                           for n in range(len(parts), 1, -1)):
                    broken.append(f'{path}:{lineno} -> {match}')
        assert not broken, (
            'docstrings naming a module that does not exist: %s' % broken)


#: Commands the documentation names that belong to a sibling distribution
#: rather than to this one.  They are real, and installing the named package
#: is what puts them on the path.
SIBLING_COMMANDS = {
    'oglc-bake': 'OpenGLContext-editor',
    'oglc-forest': 'openglcontext-forest-demo',
}

#: Paths the documentation names inside a sibling package's own checkout, in a
#: sentence that says which package.  ``docs/audio.html`` describes the tests
#: that live in ``omi_audio``.
SIBLING_PATHS = {
    'tests/test_device.py',
    'tests/test_clip.py',
}


class TestDocsNameCommandsThatExist:
    def _scripts(self):
        with open(ROOT / 'pyproject.toml', 'rb') as f:
            return set(tomllib.load(f)['project']['scripts'])

    @pytest.mark.skipif(not DOCS.is_dir(), reason='docs/ not in this checkout')
    def test_every_oglc_command_in_the_docs_is_registered(self):
        scripts = self._scripts()
        broken = {}
        for page in sorted(DOCS.glob('*.html')):
            text = page.read_text(encoding='utf-8', errors='replace')
            for name in set(re.findall(r'\boglc-[a-z-]+', text)):
                if name not in scripts and name not in SIBLING_COMMANDS:
                    broken.setdefault(page.name, set()).add(name)
        assert not broken, (
            'named in docs/ but not in pyproject [project.scripts]: %s'
            % {k: sorted(v) for k, v in broken.items()})


class TestDocsNameFilesThatExist:
    """Only paths with a directory in them, which are unambiguous.

    A bare ``flatcore.py`` in prose is the module's name rather than a path
    from the checkout root, and resolving those would be guessing.
    """

    @pytest.mark.skipif(not DOCS.is_dir(), reason='docs/ not in this checkout')
    def test_every_repository_path_named_in_the_docs_exists(self):
        pattern = re.compile(
            r'\b((?:tests|OpenGLContext|plans|docs)/[\w./-]+\.(?:py|glsl|vert|frag|md|html))')
        broken = {}
        for page in sorted(DOCS.glob('*.html')):
            text = re.sub(r'<[^>]+>', ' ',
                          page.read_text(encoding='utf-8', errors='replace'))
            for path in set(pattern.findall(text)):
                if path in SIBLING_PATHS:
                    continue
                if not (ROOT / path).exists():
                    broken.setdefault(page.name, set()).add(path)
        assert not broken, (
            'named in docs/ but not in the checkout: %s'
            % {k: sorted(v) for k, v in broken.items()})


class TestTheDirectoryMapIsComplete:
    """``CLAUDE.md``'s map is how a change finds the package it belongs in.

    A package missing from it is a package whose code ends up somewhere else,
    and the one most likely to be missing is the one added last -- so the map
    is checked rather than remembered.
    """

    MAP = ROOT / 'CLAUDE.md'

    @pytest.mark.skipif(not (ROOT / 'CLAUDE.md').is_file(),
                        reason='CLAUDE.md is not shipped in the distribution')
    def test_every_sub_package_is_listed(self):
        text = self.MAP.read_text(encoding='utf-8')
        block = text.split('## Directory Structure')[1].split('```')[1]
        listed = set(re.findall(r'[│├└─ ]+([a-z_0-9]+)/', block))
        packages = {
            path.name
            for path in PACKAGE.iterdir()
            if path.is_dir() and path.name != '__pycache__'
        }
        assert not (packages - listed), (
            'sub-packages of OpenGLContext/ missing from the directory map in '
            'CLAUDE.md: %s' % sorted(packages - listed))


class TestTheEnvironmentReferenceIsComplete:
    """``docs/environment.html`` is the only page that lists the switches.

    They are otherwise described across a dozen feature pages, which is fine
    for someone who already knows which feature they want and no use to anyone
    else.  The page is hand-written prose, so what is checked is that it names
    every variable and invents none.
    """

    PAGE = DOCS / 'environment.html'

    def _documented(self):
        text = self.PAGE.read_text(encoding='utf-8')
        return set(re.findall(r'OPENGLCONTEXT_[A-Z_0-9]+', text))

    @pytest.mark.skipif(not DOCS.is_dir(), reason='docs/ not in this checkout')
    def test_every_rendering_variable_is_documented(self):
        from OpenGLContext import renderoptions
        missing = set(renderoptions.ENVIRONMENT) - self._documented()
        assert not missing, (
            'in renderoptions.ENVIRONMENT but absent from '
            'docs/environment.html: %s' % sorted(missing))

    @pytest.mark.skipif(not DOCS.is_dir(), reason='docs/ not in this checkout')
    def test_it_documents_the_inherited_ones_too(self):
        """The exemptions need documenting most: nothing else mentions them."""
        documented = self._documented()
        for name in ('OPENGLCONTEXT_AUDIO', 'OPENGLCONTEXT_AUDIO_VOLUME',
                     'OPENGLCONTEXT_STALL_MS', 'OPENGLCONTEXT_TRACE_STALLS',
                     'OPENGLCONTEXT_STALL_TRACE', 'OPENGLCONTEXT_DEBUG_WHEEL'):
            assert name in documented, name

    @pytest.mark.skipif(not DOCS.is_dir(), reason='docs/ not in this checkout')
    def test_it_invents_nothing(self):
        package = set()
        for path in PACKAGE.rglob('*.py'):
            package.update(re.findall(
                r'OPENGLCONTEXT_[A-Z_0-9]+',
                path.read_text(encoding='utf-8', errors='replace')))
        invented = self._documented() - package
        assert not invented, (
            'documented in docs/environment.html but named nowhere in the '
            'package: %s' % sorted(invented))


class TestNoOrphanPages:
    """A page nothing links to is a page nobody finds."""

    @pytest.mark.skipif(not DOCS.is_dir(), reason='docs/ not in this checkout')
    def test_every_page_is_reachable_from_the_index(self):
        index = DOCS / 'documentation.html'
        linked = set(re.findall(r'href="([a-z0-9_]+\.html)"',
                                index.read_text(encoding='utf-8')))
        pages = {p.name for p in DOCS.glob('*.html')}
        assert not (pages - linked), (
            'not linked from docs/documentation.html: %s'
            % sorted(pages - linked))


class TestTheConsoleCommandsAreDocumented:
    """``docs/documentation.html`` is where a reader finds what to type.

    A command declared in ``[project.scripts]`` and described nowhere is a
    command nobody runs: it appears on the path at install time and there is no
    page that says it exists.  The list is hand-written prose, so what is
    checked is that it names every command and invents none.
    """

    PAGE = DOCS / 'documentation.html'

    def _declared(self):
        data = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        return set(data['project']['scripts'])

    def _listed(self, text):
        """The commands with an entry of their own in the list"""
        return set(re.findall(r'<dt><code>([a-z0-9-]+)</code></dt>', text))

    def _excused(self, text):
        """Every command named in a paragraph about deprecation

        A deprecated alias is named there rather than given an entry of its
        own, which is the right shape for it: a reader is being told to use
        something else, not what it is for. Read from the page rather than
        listed here, so that removing an alias after its release cycle brings
        its exemption down with it.

        This excuses the command the aliases point *at* as well, since it is
        named in the same paragraph -- so the one thing this does not check is
        whether `oglc-view` still has an entry. Telling the two apart means
        reading the prose, which would fail the next time somebody rewords it.
        A command newly added is in no such paragraph and is always caught,
        which is the case that matters.
        """
        excused = set()
        for paragraph in re.findall(r'<p class="technical">(.*?)</p>', text, re.S):
            if 'deprecated' in paragraph:
                excused.update(re.findall(r'<code>([a-z0-9-]+)</code>', paragraph))
        return excused

    @pytest.mark.skipif(not DOCS.is_dir(), reason='docs/ not in this checkout')
    def test_every_command_has_an_entry(self):
        """An entry in the list, not a mention somewhere on the page.

        A command named in passing while describing something else is not how
        a reader finds out that it exists, which is the job this list does.
        """
        text = self.PAGE.read_text(encoding='utf-8')
        missing = sorted(
            self._declared() - self._listed(text) - self._excused(text))
        assert not missing, (
            'declared in [project.scripts] with no entry in the console-command '
            'list in docs/documentation.html: %s' % (missing,))

    @pytest.mark.skipif(not DOCS.is_dir(), reason='docs/ not in this checkout')
    def test_the_list_invents_nothing(self):
        text = self.PAGE.read_text(encoding='utf-8')
        invented = sorted(self._listed(text) - self._declared())
        assert not invented, (
            'listed as a console command in docs/documentation.html but not '
            'declared in [project.scripts]: %s' % (invented,))
