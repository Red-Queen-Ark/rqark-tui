import re
from pathlib import Path

from rqark_core.func.image import image_to_data_uri

SUPPORTED_SUFFIXES = frozenset({'.bmp', '.gif', '.heic', '.heif', '.jpeg', '.jpg', '.png', '.tif', '.tiff', '.webp'})

MAX_BYTES = 5 * 1024 * 1024

_TOKEN = re.compile(r'@!(\S+)')


def _resolve(raw: str) -> Path | None:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        path = path.resolve()
    except OSError:
        return None
    if path.suffix.lower() not in SUPPORTED_SUFFIXES or not path.is_file():
        return None
    return path


def parse_attachments(text: str) -> tuple[str, list[Path]]:
    """Strip supported `@!path` tokens from ``text`` and return the resolved image paths.

    Tokens whose path is missing, is not a file, or has an unsupported suffix are
    left untouched in the returned text.
    """
    kept: list[str] = []
    paths: list[Path] = []
    cursor = 0
    for match in _TOKEN.finditer(text):
        start, end = match.span()
        if start > 0 and text[start - 1] not in ' \t\n':
            continue
        path = _resolve(match.group(1))
        if path is None:
            continue
        if start > 0 and text[start - 1] in ' \t':
            start -= 1
        elif text[end : end + 1] in (' ', '\t'):
            end += 1
        kept.append(text[cursor:start])
        cursor = end
        if path not in paths:
            paths.append(path)
    kept.append(text[cursor:])
    return ''.join(kept), paths


def attachment_data_uris(paths: list[Path]) -> tuple[list[str], list[Path]]:
    """Return base64 data URIs for ``paths`` plus the ones that could not be embedded."""
    uris: list[str] = []
    skipped: list[Path] = []
    for path in paths:
        try:
            if path.stat().st_size > MAX_BYTES:
                skipped.append(path)
                continue
            uris.append(image_to_data_uri(path))
        except OSError, ValueError:
            skipped.append(path)
    return uris, skipped
