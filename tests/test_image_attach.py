from pathlib import Path

import pytest

from rqark_tui.tui import image_attach
from rqark_tui.tui.image_attach import attachment_data_uris, parse_attachments

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 16


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write_image(directory: Path, name: str = 'photo.png', data: bytes = PNG) -> Path:
    path = directory / name
    path.write_bytes(data)
    return path


def test_supported_token_is_stripped_and_resolved(workspace):
    write_image(workspace)
    text, paths = parse_attachments('look @!photo.png please')
    assert text == 'look please'
    assert paths == [(workspace / 'photo.png').resolve()]


def test_image_only_message_leaves_no_text(workspace):
    write_image(workspace)
    text, paths = parse_attachments('@!photo.png')
    assert text == ''
    assert len(paths) == 1


def test_unsupported_suffix_is_left_alone(workspace):
    (workspace / 'notes.txt').write_text('hi')
    text, paths = parse_attachments('see @!notes.txt')
    assert text == 'see @!notes.txt'
    assert paths == []


def test_missing_file_is_left_alone(workspace):
    text, paths = parse_attachments('see @!nope.png')
    assert text == 'see @!nope.png'
    assert paths == []


def test_directory_with_an_image_suffix_is_left_alone(workspace):
    (workspace / 'weird.png').mkdir()
    text, paths = parse_attachments('see @!weird.png')
    assert text == 'see @!weird.png'
    assert paths == []


def test_token_inside_a_word_is_left_alone(workspace):
    write_image(workspace)
    text, paths = parse_attachments('mail@!photo.png')
    assert text == 'mail@!photo.png'
    assert paths == []


def test_token_after_a_newline_is_recognised(workspace):
    write_image(workspace)
    text, paths = parse_attachments('first\n@!photo.png')
    assert text == 'first\n'
    assert len(paths) == 1


def test_duplicate_tokens_are_stripped_but_attached_once(workspace):
    write_image(workspace)
    text, paths = parse_attachments('@!photo.png and @!photo.png')
    assert text == 'and'
    assert paths == [(workspace / 'photo.png').resolve()]


def test_multiple_images_keep_the_surrounding_text(workspace):
    write_image(workspace, 'a.png')
    write_image(workspace, 'b.png')
    text, paths = parse_attachments('compare @!a.png with @!b.png now')
    assert text == 'compare with now'
    assert [path.name for path in paths] == ['a.png', 'b.png']


def test_nested_and_absolute_paths_are_supported(workspace):
    nested = workspace / 'assets'
    nested.mkdir()
    write_image(nested, 'shot.jpeg')
    relative = parse_attachments('@!assets/shot.jpeg')[1]
    absolute = parse_attachments(f'@!{nested / "shot.jpeg"}')[1]
    assert relative == [(nested / 'shot.jpeg').resolve()]
    assert absolute == relative


def test_uppercase_suffix_is_supported(workspace):
    write_image(workspace, 'PHOTO.PNG')
    text, paths = parse_attachments('@!PHOTO.PNG')
    assert text == ''
    assert len(paths) == 1


def test_data_uri_uses_the_detected_mime(workspace):
    write_image(workspace)
    _text, paths = parse_attachments('@!photo.png')
    uris, skipped = attachment_data_uris(paths)
    assert skipped == []
    assert len(uris) == 1
    assert uris[0].startswith('data:image/png;base64,')


def test_oversized_images_are_skipped(workspace, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(image_attach, 'MAX_BYTES', 4)
    write_image(workspace)
    _text, paths = parse_attachments('@!photo.png')
    uris, skipped = attachment_data_uris(paths)
    assert uris == []
    assert skipped == paths


def test_unreadable_images_are_skipped(workspace):
    path = write_image(workspace)
    _text, paths = parse_attachments('@!photo.png')
    path.unlink()
    uris, skipped = attachment_data_uris(paths)
    assert uris == []
    assert skipped == paths
