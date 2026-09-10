"""The `oglc-test` command in `OpenGLContext.bin.gltest`."""
import os

from OpenGLContext.bin import gltest


def _write(path, text: str) -> str:
    path.write_text(text)
    return str(path)


def test_layers_every_configuration_file(tmp_path):
    """`-c` may be given more than once and each file is read."""
    first = _write(tmp_path / 'first.ini', '[context]\ntype = vrml\n')
    second = _write(tmp_path / 'second.ini', '[context]\ngui = glfw\n')
    cfg = gltest.readConfigs([first, second])
    assert cfg.get('context', 'type') == 'vrml'
    assert cfg.get('context', 'gui') == 'glfw'


def test_a_later_file_wins(tmp_path):
    first = _write(tmp_path / 'first.ini', '[context]\ngui = pygame\n')
    second = _write(tmp_path / 'second.ini', '[context]\ngui = glfw\n')
    assert gltest.readConfigs([first, second]).get('context', 'gui') == 'glfw'


def test_no_script_is_an_error_exit():
    assert gltest.main([]) == 1


def test_a_missing_script_is_an_error_exit(tmp_path):
    missing = str(tmp_path / 'nothing-here.py')
    assert gltest.main(['-s', missing]) == 1


def test_the_generated_class_counts_the_frames_asked_for():
    class Base:
        pass

    cls = gltest.saveAndExitClass(Base, 7, 'template-%(script)s.png', 'demo')
    assert issubclass(cls, Base)
    assert cls.target_frame_count == 7
    assert cls.frame_count == 0


def test_the_output_directory_is_made_absolute(tmp_path, monkeypatch):
    """A relative -o is anchored to the working directory, not the picture folder.

    The reference image is looked for and written at the same path, so a second
    run compares against what the first one wrote.
    """
    script = _write(tmp_path / 'demo.py', 'raise SystemExit(0)\n')
    monkeypatch.chdir(tmp_path)
    recorded = {}

    def record(base, frames, template, script_name):
        recorded.update(template=template, script_name=script_name)
        raise SystemExit(0)

    monkeypatch.setattr(gltest, 'saveAndExitClass', record)
    monkeypatch.setattr(gltest, 'contextClass', lambda configs: object)
    try:
        gltest.main(['-s', script, '-o', 'shots'])
    except SystemExit:
        pass
    assert os.path.isabs(recorded['template'])
    assert recorded['template'] == str(tmp_path / 'shots' / 'demo-ref.png')
    assert recorded['script_name'] == 'demo'
