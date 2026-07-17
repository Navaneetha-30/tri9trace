"""Version matcher unit tests (FR2 edge cases, TRD section 5)."""
from __future__ import annotations

from app.ingest import ingest_text
from app.db.models import Node, NodeRevision


def _revisions_by_key(db):
    rows = db.query(Node, NodeRevision).join(NodeRevision, NodeRevision.node_id == Node.id).all()
    return {n.logical_key: (n, r) for n, r in rows}


def test_same_key_unchanged(db):
    md = "# Doc\n## A\nbody-a\n## B\nbody-b\n"
    ingest_text(db, "d", "D", "f.md", md)
    ingest_text(db, "d", "D", "f2.md", md)
    by_key = _revisions_by_key(db)
    a_node, a_rev = by_key["doc/a"]
    # Second revision for A must report unchanged.
    a_revs = db.query(NodeRevision).filter(NodeRevision.node_id == a_node.id).all()
    assert len(a_revs) == 2
    assert a_revs[1].is_changed_from_previous is False


def test_same_key_changed(db):
    md1 = "# Doc\n## A\nbody-a\n"
    md2 = "# Doc\n## A\nbody-a-CHANGED\n"
    ingest_text(db, "d", "D", "f1.md", md1)
    ingest_text(db, "d", "D", "f2.md", md2)
    a = db.query(Node).filter(Node.logical_key == "doc/a").one()
    revs = db.query(NodeRevision).filter(NodeRevision.node_id == a.id).order_by(NodeRevision.document_version_id).all()
    assert len(revs) == 2
    assert revs[0].is_changed_from_previous is False  # first ingest
    assert revs[1].is_changed_from_previous is True
    assert revs[0].content_hash != revs[1].content_hash


def test_key_disappeared_is_not_deleted(db):
    """A section present in v1 but absent in v2 is not removed from history;
    it simply gets no v2 revision."""
    md1 = "# Doc\n## A\nbody-a\n## B\nbody-b\n"
    md2 = "# Doc\n## A\nbody-a\n"  # B disappeared
    ingest_text(db, "d", "D", "f1.md", md1)
    ingest_text(db, "d", "D", "f2.md", md2)
    b = db.query(Node).filter(Node.logical_key == "doc/b").one()
    revs = db.query(NodeRevision).filter(NodeRevision.node_id == b.id).all()
    assert len(revs) == 1, "B must retain exactly its v1 revision, not be deleted"


def test_key_appeared_is_new(db):
    md1 = "# Doc\n## A\nbody-a\n"
    md2 = "# Doc\n## A\nbody-a\n## B\nbody-b\n"
    ingest_text(db, "d", "D", "f1.md", md1)
    ingest_text(db, "d", "D", "f2.md", md2)
    b = db.query(Node).filter(Node.logical_key == "doc/b").one()
    revs = db.query(NodeRevision).filter(NodeRevision.node_id == b.id).all()
    assert len(revs) == 1
    assert revs[0].is_changed_from_previous is False  # new node: nothing to compare


def test_duplicate_heading_disambiguation_persists(db):
    """Two `### Alarms` under the same parent get distinct logical keys that
    survive a re-ingest (the second re-ingest matches them back, not tripled)."""
    md = "# Doc\n## Parent\n### Alarms\nfirst\n### Alarms\nsecond\n"
    ingest_text(db, "d", "D", "f1.md", md)
    ingest_text(db, "d", "D", "f2.md", md)
    keys = {n.logical_key for n in db.query(Node).all()}
    assert "doc/parent/alarms" in keys
    assert "doc/parent/alarms (2)" in keys
    # Re-ingest must NOT create a third duplicate node.
    alarms_nodes = db.query(Node).filter(Node.heading_text == "Alarms").all()
    assert len(alarms_nodes) == 2