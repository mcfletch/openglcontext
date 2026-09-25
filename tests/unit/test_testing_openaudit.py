"""The open audit attributes each open to the checked module that made it."""
import os
import subprocess
import sys
import textwrap

import pytest

from OpenGLContext.testing.openaudit import OpenAudit


def _module(name, source):
    """Functions defined as if in the module ``name``."""
    space = {'__name__': name}
    exec(textwrap.dedent(source), space)
    return space


OPENER = '''
def read(path):
    with open(path, 'rb') as handle:
        return handle.read()

def read_through(function, path):
    return function(path)
'''


@pytest.fixture
def audit(tmp_path, monkeypatch):
    """An audit of the package ``auditedpkg``, whose directory is under ``tmp_path``.

    Not the engine's own name: the session's audit checks that.
    """
    package = tmp_path / 'auditedpkg'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'shader.glsl').write_text('void main() {}')
    module = type(sys)('auditedpkg')
    module.__file__ = str(package / '__init__.py')
    monkeypatch.setitem(sys.modules, 'auditedpkg', module)
    found = OpenAudit(['auditedpkg'], ['auditedpkg.loaders.resolver'])
    found.enabled = True
    sys.addaudithook(lambda event, args: found.hook(event, args)
                     if found.enabled else None)
    yield found
    found.enabled = False


@pytest.fixture
def a_file(tmp_path):
    path = tmp_path / 'data.bin'
    path.write_bytes(b'data')
    return str(path)


def test_an_unsanctioned_engine_module_is_found(audit, a_file):
    engine = _module('auditedpkg.scenegraph.example', OPENER)
    engine['read'](a_file)
    found, = audit.take()
    assert found.module == 'auditedpkg.scenegraph.example'
    assert found.path == a_file and found.mode == 'r'
    assert 'auditedpkg.scenegraph.example:' in str(found)
    assert audit.take() == []


def test_a_sanctioned_module_is_not(audit, a_file):
    _module('auditedpkg.loaders.resolver', OPENER)['read'](a_file)
    assert audit.take() == []


def test_the_innermost_checked_module_is_the_one_charged(audit, a_file):
    """An unchecked library between them does not hide the engine module."""
    library = _module('somelibrary.io', OPENER)
    engine = _module('auditedpkg.scenegraph.example', OPENER)
    engine['read_through'](library['read'], a_file)
    assert [found.module for found in audit.take()] == ['auditedpkg.scenegraph.example']
    resolver = _module('auditedpkg.loaders.resolver', OPENER)
    engine['read_through'](lambda path: resolver['read_through'](library['read'], path),
                           a_file)
    assert audit.take() == []


def test_an_open_with_no_checked_module_on_the_stack_is_not(audit, a_file):
    with open(a_file, 'rb'):
        pass
    assert audit.take() == []


def test_an_import_made_by_an_engine_module_is_not(audit, tmp_path):
    (tmp_path / 'audited_import_example.py').write_text('VALUE = 1\n')
    sys.path.insert(0, str(tmp_path))
    try:
        engine = _module('auditedpkg.scenegraph.example', '''
            def load():
                import audited_import_example
                return audited_import_example.VALUE
        ''')
        assert engine['load']() == 1
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop('audited_import_example', None)
    assert audit.take() == []


def test_the_packages_own_data_is_not(audit, tmp_path):
    _module('auditedpkg.scenegraph.example', OPENER)['read'](
        str(tmp_path / 'auditedpkg' / 'shader.glsl'))
    assert audit.take() == []


def test_a_file_descriptor_is_not(audit, a_file):
    descriptor = os.open(a_file, os.O_RDONLY)
    try:
        _module('auditedpkg.scenegraph.example', '''
            def wrap(fd):
                return open(fd, 'rb', closefd=False).read()
        ''')['wrap'](descriptor)
    finally:
        os.close(descriptor)
    assert audit.take() == []


def test_switched_off_it_finds_nothing(audit, a_file):
    audit.enabled = False
    _module('auditedpkg.scenegraph.example', OPENER)['read'](a_file)
    assert audit.take() == []


PROJECT_TEST = textwrap.dedent('''
    import textwrap

    def test_opens_from_an_engine_module(tmp_path):
        path = tmp_path / 'x'
        path.write_text('x')
        space = {'__name__': 'OpenGLContext.scenegraph.example'}
        exec(textwrap.dedent(\'\'\'
            def read(path):
                with open(path) as handle:
                    return handle.read()
        \'\'\'), space)
        assert space['read'](str(path)) == 'x'
''')


def _run(tmp_path, *options):
    (tmp_path / 'test_opens.py').write_text(PROJECT_TEST)
    return subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
         '-p', 'OpenGLContext.testing.plugin', '--rootdir', str(tmp_path),
         '-c', '/dev/null', *options, str(tmp_path)],
        capture_output=True, text=True, timeout=300)


def test_fail_fails_the_test_that_opened(tmp_path):
    done = _run(tmp_path, '-o', 'open_audit=fail')
    assert done.returncode == 1, done.stdout[-2000:]
    assert 'OpenGLContext.scenegraph.example:' in done.stdout
    assert 'sanctioned openers' in done.stdout


def test_report_lists_it_and_passes(tmp_path):
    done = _run(tmp_path, '--open-audit', 'report')
    assert done.returncode == 0, done.stdout[-2000:]
    assert 'OpenAuditWarning' in done.stdout


def test_a_sanctioned_module_passes(tmp_path):
    done = _run(tmp_path, '-o', 'open_audit=fail',
                '-o', 'open_audit_sanctioned=OpenGLContext.scenegraph')
    assert done.returncode == 0, done.stdout[-2000:]
