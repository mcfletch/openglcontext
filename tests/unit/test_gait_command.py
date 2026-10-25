"""`oglc-gait`: the stride of a model's locomotion clips, printed."""
import pytest

pygltflib = pytest.importorskip("pygltflib")

from OpenGLContext.bin.gait import main

from ._locomotion_assets import striding, walker_glb, waving


@pytest.fixture
def model_file(tmp_path):
    path = tmp_path / 'walker.glb'
    path.write_bytes(walker_glb({
        'idle': waving(2.0), 'walk': striding(1.0), 'run': striding(0.5),
        'dance': waving(1.0)}))
    return str(path)


def test_each_locomotion_clip_is_reported_with_its_speed_and_cycle(model_file, capsys):
    assert main([model_file]) == 0
    out = capsys.readouterr().out
    walk = next(line for line in out.splitlines() if line.startswith('walk'))
    run = next(line for line in out.splitlines() if line.startswith('run'))
    assert '1.67' in walk and '1.000' in walk
    assert '3.33' in run and '0.500' in run


def test_clips_that_are_not_locomotion_are_left_out(model_file, capsys):
    main([model_file])
    names = [line.split()[0] for line in capsys.readouterr().out.splitlines()
             if line.strip()]
    assert 'idle' not in names
    assert 'dance' not in names


def test_all_asks_for_every_clip(model_file, capsys):
    main([model_file, '--all'])
    out = capsys.readouterr().out
    assert 'idle' in out and 'dance' in out


def test_clips_can_be_named(model_file, capsys):
    main([model_file, '--clips', 'dance,run'])
    out = capsys.readouterr().out
    assert 'dance' in out and 'run' in out
    assert not any(line.startswith('walk') for line in out.splitlines())


def test_the_contact_times_are_listed(model_file, capsys):
    main([model_file])
    walk = next(line for line in capsys.readouterr().out.splitlines()
                if line.startswith('walk'))
    assert 'left 0.00' in walk
    assert 'right 0.50' in walk


def test_a_map_to_paste_comes_with_the_numbers(model_file, capsys):
    main([model_file])
    out = capsys.readouterr().out
    assert "walk=ClipSpec('walk', speed=1.67" in out
    assert "idle='idle'" in out


def test_roles_with_no_clip_and_clips_with_no_role_are_listed(model_file, capsys):
    main([model_file])
    out = capsys.readouterr().out
    assert 'no clip for: sprint' in out
    assert 'no role for: dance' in out


def test_a_clip_the_model_lacks_is_an_error(model_file, capsys):
    assert main([model_file, '--clips', 'gallop']) == 2
    assert 'gallop' in capsys.readouterr().err


def test_a_model_with_no_skeleton_is_an_error(tmp_path, capsys):
    from ._character_assets import skeleton_glb
    path = tmp_path / 'bare.glb'
    path.write_bytes(skeleton_glb(names=['bone%d' % i for i in range(19)]))
    assert main([str(path), '--all']) == 2
    assert 'skeleton' in capsys.readouterr().err


def test_a_file_that_is_not_there_is_an_error(tmp_path, capsys):
    assert main([str(tmp_path / 'missing.glb')]) == 2
    assert 'missing.glb' in capsys.readouterr().err
