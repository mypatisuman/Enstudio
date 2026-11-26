import yaml
from pathlib import Path


def read_ympl(path: Path) -> dict:
    """Read a YAML/YMPL/VIDS file and return as dict. Tries UTF-8, falls back to Latin-1."""
    path = Path(path)
    for enc in ('utf-8', 'latin-1'):
        try:
            with open(path, encoding=enc) as f:
                return yaml.safe_load(f) or {}
        except UnicodeDecodeError:
            continue
    raise ValueError(f'Cannot decode {path} as UTF-8 or Latin-1')
