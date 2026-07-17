"""Integration test (FR2): ingest v1 then v2 of the REAL CT-200 manuals and
assert the exact set of is_changed_from_previous flags matches manual
inspection of the two files.

Manual diff v1 -> v2 (by section):
- Warnings: 'near open flame' -> 'near an open flame' ........ CHANGED
- Recording: export sentence moved out to new 'Export' sec ... CHANGED
- Safety Limits: 160 bpm/5 kg -> 140 bpm/7 kg ................. CHANGED
Everything else that shares a logical key is byte-identical (unchanged);
sections renamed/added/removed are new/deleted, NOT 'changed'.
"""
from __future__ import annotations

from pathlib import Path

from app.ingest import ingest_file
from app.db.models import Node, NodeRevision

DATA = Path(__file__).resolve().parents[1] / "data"


def test_v1_to_v2_changed_flags_match_manual_inspection(db):
    ingest_file(db, "ct200-manual", "CT-200 Manual", str(DATA / "ct200_manual.md"))
    ingest_file(db, "ct200-manual", "CT-200 Manual", str(DATA / "ct200_manual_v2.md"))

    # For every node, take its v2 revision (if any) and read is_changed.
    v2_changed_keys = [
        n.logical_key
        for n in db.query(Node).all()
        if any(
            r.is_changed_from_previous and r.document_version_id == 2
            for r in db.query(NodeRevision).filter(NodeRevision.node_id == n.id).all()
        )
    ]
    # Exactly three sections changed substance while keeping their path.
    assert len(v2_changed_keys) == 3, v2_changed_keys
    suffixes = {k.rsplit("/", 1)[-1] for k in v2_changed_keys}
    assert suffixes == {"warnings", "recording", "safety-limits"}, suffixes

    # Safety Limits is the dangerous case: heading intact, threshold rewritten.
    sl = db.query(Node).filter(Node.logical_key.like("%safety-limits")).one()
    revs = db.query(NodeRevision).filter(NodeRevision.node_id == sl.id).order_by(NodeRevision.document_version_id).all()
    assert revs[0].body_text != revs[1].body_text
    assert "160 bpm" in revs[0].body_text
    assert "140 bpm" in revs[1].body_text
    assert revs[1].is_changed_from_previous is True