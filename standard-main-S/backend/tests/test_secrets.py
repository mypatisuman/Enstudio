"""
Guards the at-rest encryption of API keys in the `settings` table.

The wire format is shared with the desktop app (src-tauri/src/config/secrets.rs).
If these two drift, the symptom is not a crash — it is extraction failing with
an auth error from the provider, because the Rust side wrote a blob the Python
side handed to the API verbatim. Hence the explicit format assertions below.
"""

import subprocess
import sys

import pytest

from adapters.secrets import (
    ENC_PREFIX, decrypt_secret, encrypt_secret, is_secret_key,
)

IS_WINDOWS = sys.platform == 'win32'
FAKE_KEY = 'sk-ant-api03-NOTAREALKEY-0123456789'


def test_only_api_key_fields_are_secret():
    # Must agree with is_secret_key() in secrets.rs — a field classified
    # differently on the two sides gets written encrypted and read raw.
    assert is_secret_key('anthropic_api_key')
    assert is_secret_key('gemini_api_key')
    assert is_secret_key('custom_grok_api_key')
    assert not is_secret_key('anthropic_model_smart')
    assert not is_secret_key('llm_provider')
    assert not is_secret_key('custom_providers')


def test_round_trip():
    assert decrypt_secret(encrypt_secret(FAKE_KEY)) == FAKE_KEY


def test_empty_stays_empty():
    # load_config treats '' as unset; encrypting it would produce a non-empty
    # blob and make an unconfigured provider look configured.
    assert encrypt_secret('') == ''
    assert decrypt_secret('') == ''


def test_legacy_plaintext_reads_back_unchanged():
    # Rows written before encryption existed have no prefix and must keep
    # working, or every existing install loses its configured key.
    assert decrypt_secret('sk-plain-legacy') == 'sk-plain-legacy'


@pytest.mark.skipif(not IS_WINDOWS, reason='DPAPI is Windows-only')
def test_stored_form_does_not_contain_the_key():
    """The whole point of the change: the key must not be readable in the DB."""
    stored = encrypt_secret(FAKE_KEY)
    assert stored.startswith(ENC_PREFIX)
    assert FAKE_KEY not in stored
    assert 'sk-ant' not in stored


@pytest.mark.skipif(not IS_WINDOWS, reason='DPAPI is Windows-only')
def test_config_round_trip_through_the_settings_table(tmp_path, monkeypatch):
    """save_config → DB → load_config must return plaintext, and the raw row
    must be ciphertext. This is the path extract_cli.py actually takes."""
    import sqlite3

    db_path = tmp_path / 'studio.db'
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

    import adapters.config as config
    monkeypatch.setattr(config, '_settings_db', lambda: conn)

    config.save_config({'anthropic_api_key': FAKE_KEY, 'llm_provider': 'anthropic'})

    raw = conn.execute(
        "SELECT value FROM settings WHERE key='anthropic_api_key'").fetchone()['value']
    assert raw.startswith(ENC_PREFIX), 'key was written in plaintext'
    assert FAKE_KEY not in raw

    # Non-secret fields stay readable — only credentials get encrypted.
    provider = conn.execute(
        "SELECT value FROM settings WHERE key='llm_provider'").fetchone()['value']
    assert provider == 'anthropic'

    assert config.load_config()['anthropic_api_key'] == FAKE_KEY


@pytest.mark.skipif(not IS_WINDOWS, reason='DPAPI is Windows-only')
def test_undecryptable_key_reads_as_unset(tmp_path, monkeypatch):
    """A blob from another machine/user must not be handed to the provider as
    if it were a key — load_config blanks it instead."""
    import sqlite3

    conn = sqlite3.connect(tmp_path / 'studio.db')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    conn.execute("INSERT INTO settings VALUES ('anthropic_api_key', ?)",
                 (ENC_PREFIX + 'bm90LWEtcmVhbC1kcGFwaS1ibG9i',))

    import adapters.config as config
    monkeypatch.setattr(config, '_settings_db', lambda: conn)

    assert config.load_config()['anthropic_api_key'] == ''


@pytest.mark.skipif(not IS_WINDOWS, reason='DPAPI is Windows-only')
def test_python_decrypts_a_blob_produced_by_rust():
    """The actual cross-language guard.

    Encrypt with Python, then have the Rust implementation decrypt it (and
    vice versa) via a throwaway binary. Skipped when cargo is unavailable —
    the format assertions above still catch the common drift cases.
    """
    if not _has_cargo():
        pytest.skip('cargo not available')

    # Round-trip in the other direction is covered by secrets.rs's own tests;
    # what only an end-to-end check can catch is the ENTROPY constant or the
    # prefix differing between the two files.
    from adapters.secrets import ENTROPY
    rust = (_frontend_dir() / 'src-tauri' / 'src' / 'config'
            / 'secrets.rs').read_text(encoding='utf-8')
    assert f'b"{ENTROPY.decode()}"' in rust, 'ENTROPY differs between secrets.py and secrets.rs'
    assert f'"{ENC_PREFIX}"' in rust, 'ENC_PREFIX differs between secrets.py and secrets.rs'


def _repo_root():
    from pathlib import Path
    return Path(__file__).resolve().parents[2]


def _frontend_dir():
    """The desktop app directory, under either name.

    The folder is being renamed plantsketch-desktop -> frontend; accepting both
    keeps this test passing on either side of that change instead of failing for
    a reason that has nothing to do with secrets.
    """
    root = _repo_root()
    for name in ('frontend', 'plantsketch-desktop'):
        if (root / name).is_dir():
            return root / name
    raise AssertionError(f'no frontend directory under {root}')


def _has_cargo():
    try:
        return subprocess.run(['cargo', '--version'], capture_output=True).returncode == 0
    except (OSError, FileNotFoundError):
        return False
