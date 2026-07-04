"""Cases, tamper-evident audit chain, graph, and report tests."""
import pytest

from app import audit_chain, cases, graph, report, db


@pytest.fixture
def _db(client):
    # `client` fixture wipes + inits the DB and starts the queue.
    return client


async def test_case_lifecycle_and_ref(_db):
    c = cases.create_case(title="Op Test", subject="johndoe", subject_type="username",
                          examiner="Det. Smith", authority="Warrant 123")
    assert c["ref"].startswith("GFM-") and c["ref"].endswith(f"{c['id']:04d}")
    assert c["status"] == "open"
    got = cases.get_case(c["id"])
    assert got["examiner"] == "Det. Smith"
    upd = cases.update_case(c["id"], status="closed")
    assert upd["status"] == "closed"
    assert any(x["id"] == c["id"] for x in cases.list_cases())


async def test_find_or_create_reuses_open_case(_db):
    a = cases.find_or_create_for_subject("acme.com", "domain")
    b = cases.find_or_create_for_subject("acme.com", "domain")
    assert a["id"] == b["id"]  # reused, not duplicated
    cases.update_case(a["id"], status="closed")
    c = cases.find_or_create_for_subject("acme.com", "domain")
    assert c["id"] != a["id"]  # closed → a fresh case opens


async def test_findings_scoped_to_case(_db):
    c = cases.create_case(subject="target1", subject_type="username")
    db.execute("INSERT INTO findings (source_kind, source_name, target, target_type, summary, "
               "case_id, created_at) VALUES ('provider','x','target1','username','{\"found\": true}',?, "
               "datetime('now'))", (c["id"],))
    g = graph.build_for_case(c["id"])
    assert g["stats"]["nodes"] >= 2  # subject + source
    assert any(n["group"] == "subject" for n in g["nodes"])


async def test_audit_chain_appends_and_verifies(_db):
    audit_chain.record("test event a", category="case", foo="bar")
    audit_chain.record("test event b", category="auth")
    v = audit_chain.verify()
    assert v["ok"] is True and v["count"] >= 2 and v["broken_at"] is None


async def test_audit_chain_detects_tampering(_db):
    audit_chain.record("evt1", category="case")
    audit_chain.record("evt2", category="case")
    audit_chain.record("evt3", category="case")
    # Tamper with a historical row's detail without recomputing hashes.
    row = db.query_one("SELECT id FROM audit_chain ORDER BY id ASC LIMIT 1 OFFSET 1")
    db.write("UPDATE audit_chain SET action='EDITED' WHERE id=?", (row["id"],))
    v = audit_chain.verify()
    assert v["ok"] is False and v["broken_at"] == row["id"]


async def test_delete_case_purges_findings(_db):
    from app.util import now_iso, jdumps
    c = cases.create_case(subject="x.com", subject_type="domain")
    cid = c["id"]
    db.execute("INSERT INTO findings (job_id, source_kind, source_name, target, target_type, "
               "summary, raw, case_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
               (None, "tool", "sherlock", "x.com", "domain", jdumps({"found": True}), None,
                cid, now_iso()))
    assert cases.get_case(cid)["counts"]["findings"] == 1
    assert cases.delete_case(cid) == 1
    assert cases.get_case(cid) is None
    # findings for that case are purged, not orphaned
    assert db.query_one("SELECT COUNT(*) c FROM findings WHERE case_id=?", (cid,))["c"] == 0


async def test_delete_all_cases(_db):
    cases.create_case(subject="a.com", subject_type="domain")
    cases.create_case(subject="b.com", subject_type="domain")
    assert cases.delete_all_cases() == 2
    assert cases.list_cases() == []


async def test_case_report_html_renders_and_is_scoped(_db):
    c = cases.create_case(subject="subject-x", subject_type="email", examiner="Analyst A")
    html = report.render_case_html(c["id"])
    assert html is not None
    assert c["ref"] in html and "Integrity" in html
    assert "Analyst A" in html
    # Fingerprint placeholder must be resolved to a real hash.
    assert "%%FINGERPRINT%%" not in html
    assert report.render_case_html(999999) is None
