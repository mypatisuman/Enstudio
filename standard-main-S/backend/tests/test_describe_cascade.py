"""Tests for tag-cascade consistency in agents/describe/services/repository.py
— ported from the Rust desktop app's update_node_by_tag/delete_node_by_tag
cascade behavior (src-tauri/src/commands/graph.rs), since Describe's
Python implementations previously left instruments/equipment/review/
connections stale on rename or delete.
"""
import sys
from pathlib import Path

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from agents.describe.services import repository as R  # noqa: E402

PID = "cascadeproj"


@pytest.fixture()
def db(tmp_path):
    from adapters import db as dbmod
    dbmod.reset_for_path(tmp_path / "studio.db")
    dbmod.init_db()
    dbmod.get_db().execute(
        "INSERT INTO projects (id, title) VALUES (?, ?)", (PID, "Test"))
    yield dbmod
    dbmod.close_db()


def _add_instrument_row(pid, tag, equipment_ref=""):
    # REPLACE, not a bare INSERT: add_nodes() now mirrors a transmitter-kind
    # tag into `instruments` itself (the gap-fix that made Describe-authored
    # graphs visible to export_vids/export_ympl/the Review screen) — these
    # test helpers simulate a project whose instrument row ALREADY carries
    # specific fixture values (e.g. equipment_ref), so they must overwrite
    # whatever add_nodes already inserted rather than collide with it.
    R._db().execute(
        "INSERT OR REPLACE INTO instruments (tag, pid, area, equipment_ref) "
        "VALUES (?,?,?,?)", (tag, pid, "100", equipment_ref))
    R._db().commit()


def _add_equipment_row(pid, tag):
    R._db().execute(
        "INSERT OR REPLACE INTO equipment (tag, pid, area) VALUES (?,?,?)",
        (tag, pid, "100"))
    R._db().commit()


def _set_review(pid, key, state):
    R._db().execute(
        "INSERT OR REPLACE INTO review (pid, key, state) VALUES (?,?,?)",
        (pid, key, state))
    R._db().commit()


def _add_connection_row(pid, from_tag, to_tag):
    # REPLACE for the same reason as _add_instrument_row: add_edges() now
    # mirrors into `connections` itself, so a fixture that wants a specific
    # connection id/shape must overwrite that mirrored row, not collide
    # with it under the (id, pid) primary key.
    R._db().execute(
        "INSERT OR REPLACE INTO connections (pid, id, from_tag, to_tag, type) "
        "VALUES (?,?,?,?,?)",
        (pid, f"{from_tag}\x1e{to_tag}\x1estream", from_tag, to_tag, "stream"))
    R._db().commit()


# ── rename cascade ───────────────────────────────────────────────────────────

def test_rename_cascades_into_instruments(db):
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"}])
    _add_instrument_row(PID, "FT-101")

    R.update_node(PID, "FT-101", new_tag="FT-102")
    row = R._db().execute(
        "SELECT tag FROM instruments WHERE pid=?", (PID,)).fetchone()
    assert row[0] == "FT-102"


def test_rename_cascades_into_equipment(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"}])
    _add_equipment_row(PID, "V-101")

    R.update_node(PID, "V-101", new_tag="V-102")
    row = R._db().execute(
        "SELECT tag FROM equipment WHERE pid=?", (PID,)).fetchone()
    assert row[0] == "V-102"


def test_rename_cascades_into_review(db):
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"}])
    _set_review(PID, "FT-101", "accepted")

    R.update_node(PID, "FT-101", new_tag="FT-102")
    row = R._db().execute(
        "SELECT key, state FROM review WHERE pid=?", (PID,)).fetchone()
    assert tuple(row) == ("FT-102", "accepted")   # key renamed, state kept


def test_rename_cascades_into_equipment_ref(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "FT-101", "kind": "transmitter"}])
    _add_instrument_row(PID, "FT-101", equipment_ref="V-101")

    R.update_node(PID, "V-101", new_tag="V-102")
    row = R._db().execute(
        "SELECT equipment_ref FROM instruments WHERE pid=? AND tag=?",
        (PID, "FT-101")).fetchone()
    assert row[0] == "V-102"


def test_rename_cascades_into_connections_both_sides(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "P-101", "kind": "pump"}])
    _add_connection_row(PID, "V-101", "P-101")

    R.update_node(PID, "V-101", new_tag="V-102")
    row = R._db().execute(
        "SELECT from_tag, to_tag FROM connections WHERE pid=?",
        (PID,)).fetchone()
    assert tuple(row) == ("V-102", "P-101")

    R.update_node(PID, "P-101", new_tag="P-102")
    row = R._db().execute(
        "SELECT from_tag, to_tag FROM connections WHERE pid=?",
        (PID,)).fetchone()
    assert tuple(row) == ("V-102", "P-102")


def test_rename_by_node_id_still_cascades_correctly(db):
    """Callers may pass a node id (Holistic-resolved target) as the
    `tag` arg — the cascade must key off the node's actual LABEL, not
    whatever string the caller passed in, since instruments/equipment/
    review/connections are label-keyed, never id-keyed."""
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"}])
    _add_instrument_row(PID, "FT-101")
    node_id = R.get_node(PID, "FT-101")["id"]   # == "FT-101" (tag-as-id here)

    # Force a distinct id vs label to prove the cascade uses label, not id:
    R._db().execute("UPDATE nodes SET id='n99' WHERE pid=? AND label=?",
                    (PID, "FT-101"))
    R._db().execute("UPDATE instruments SET tag='FT-101' WHERE pid=?", (PID,))
    R._db().commit()

    R.update_node(PID, "n99", new_tag="FT-102")   # target by id
    row = R._db().execute(
        "SELECT tag FROM instruments WHERE pid=?", (PID,)).fetchone()
    assert row[0] == "FT-102"


def test_kind_only_update_does_not_touch_cascade_tables(db):
    """A non-rename update (kind/area/description only) must NOT run
    the rename cascade — nothing to rename, and running it anyway could
    wrongly no-op-overwrite unrelated rows."""
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"}])
    _add_instrument_row(PID, "FT-101")

    R.update_node(PID, "FT-101", area="200")
    row = R._db().execute(
        "SELECT tag FROM instruments WHERE pid=?", (PID,)).fetchone()
    assert row[0] == "FT-101"   # unchanged, not renamed to itself repeatedly


# ── delete cascade ───────────────────────────────────────────────────────────

def test_delete_cascades_into_instruments(db):
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"}])
    _add_instrument_row(PID, "FT-101")

    R.delete_nodes(PID, ["FT-101"])
    assert R._db().execute(
        "SELECT COUNT(*) FROM instruments WHERE pid=?",
        (PID,)).fetchone()[0] == 0


def test_delete_cascades_into_equipment(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"}])
    _add_equipment_row(PID, "V-101")

    R.delete_nodes(PID, ["V-101"])
    assert R._db().execute(
        "SELECT COUNT(*) FROM equipment WHERE pid=?",
        (PID,)).fetchone()[0] == 0


def test_delete_cascades_into_review(db):
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"}])
    _set_review(PID, "FT-101", "accepted")

    R.delete_nodes(PID, ["FT-101"])
    assert R._db().execute(
        "SELECT COUNT(*) FROM review WHERE pid=?",
        (PID,)).fetchone()[0] == 0


def test_delete_cascades_into_connections(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "P-101", "kind": "pump"}])
    _add_connection_row(PID, "V-101", "P-101")

    R.delete_nodes(PID, ["V-101"])
    assert R._db().execute(
        "SELECT COUNT(*) FROM connections WHERE pid=?",
        (PID,)).fetchone()[0] == 0


def test_delete_clears_dangling_equipment_ref(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "FT-101", "kind": "transmitter"}])
    _add_instrument_row(PID, "FT-101", equipment_ref="V-101")

    R.delete_nodes(PID, ["V-101"])
    row = R._db().execute(
        "SELECT equipment_ref FROM instruments WHERE pid=? AND tag=?",
        (PID, "FT-101")).fetchone()
    assert row[0] == ""


def test_delete_multiple_tags_cascades_each(db):
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"},
                      {"tag": "V-101", "kind": "vessel"}])
    _add_instrument_row(PID, "FT-101")
    _add_equipment_row(PID, "V-101")

    R.delete_nodes(PID, ["FT-101", "V-101"])
    assert R._db().execute(
        "SELECT COUNT(*) FROM instruments WHERE pid=?", (PID,)
    ).fetchone()[0] == 0
    assert R._db().execute(
        "SELECT COUNT(*) FROM equipment WHERE pid=?", (PID,)
    ).fetchone()[0] == 0


# ── insert_between must NOT trigger a cascade (no rename/delete of a tag) ──

def test_insert_between_does_not_touch_cascade_tables(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    _add_instrument_row(PID, "E-101")   # unrelated row that must survive untouched
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])

    R.insert_between(PID, {"tag": "VALVE-1", "kind": "valve"},
                     "V-101", "E-101")
    row = R._db().execute(
        "SELECT tag FROM instruments WHERE pid=?", (PID,)).fetchone()
    assert row[0] == "E-101"   # unchanged
