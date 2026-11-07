"""Validated directory-local defaults, separate from torrent runtime state."""
import json
from pathlib import Path

DEFAULTS = {
    'seed_completed': False,
    'auto_start': True,
    'download_directory': 'downloads',
    'download_rate_limit': 0,
    'upload_rate_limit': 0,
    'enable_dht': True,
}


def validate(values, root):
    if not isinstance(values, dict):
        raise ValueError('terrence.json must contain a JSON object')
    unknown = values.keys() - DEFAULTS.keys()
    if unknown:
        raise ValueError('Unknown settings: ' + ', '.join(sorted(unknown)))
    settings = {**DEFAULTS, **values}
    for key in ('seed_completed', 'auto_start', 'enable_dht'):
        if type(settings[key]) is not bool:
            raise ValueError(f'{key} must be true or false')
    for key in ('download_rate_limit', 'upload_rate_limit'):
        if type(settings[key]) is not int or not 0 <= settings[key] <= 2**31 - 1:
            raise ValueError(f'{key} must be an integer between 0 and 2147483647 (bytes/second; 0 = unlimited)')
    folder = settings['download_directory']
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError('download_directory must be a nonempty relative path')
    root = Path(root).resolve()
    target = (root / folder).resolve()
    if Path(folder).is_absolute() or target == root or not target.is_relative_to(root) or target.is_relative_to(root / '.terrence') or target.is_relative_to(root / '.git'):
        raise ValueError('download_directory must be a subdirectory of the working directory outside .terrence and .git')
    return settings


def read_settings(root):
    path = Path(root) / 'terrence.json'
    try:
        values = json.loads(path.read_text(encoding='utf-8-sig'))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError(f'Invalid {path}: {error}') from error
    return validate(values, root)
