"""End-to-end checks of the server-rendered app via Flask's test client (no JS involved)."""
import re

import pytest

import app as appmod


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("roster.state.STATE_DIR", tmp_path)
    appmod.store._SESSIONS.clear()
    return appmod.app.test_client()


def test_pages_render(client):
    for path in ["/roster", "/roster?type=pod", "/roster?type=brand", "/roster?type=process", "/roster?type=employee", "/issues", "/changes", "/rules"] + \
                [f"/setup?entity={e}" for e in appmod.ENTITIES]:
        r = client.get(path, follow_redirects=True)
        assert r.status_code == 200, path
        assert b"Smart Roster" in r.data
    r = client.get("/roster")
    assert b"100.0%" in r.data and b"Pod Alpha" in r.data and "Kaya" not in ""  # company view with sample data


def test_no_javascript_in_pages(client):
    html = client.get("/roster").get_data(as_text=True)
    assert "<script" not in html.lower()


def test_demo_change_and_apply_fix(client):
    client.get("/roster")
    r = client.post("/leave/demo", data={"next": "/changes"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "coverage problem(s) still open" in html and "Leave clash" in html
    fix = re.search(r'name="issue" value="([^"]+)"><input type="hidden" name="fix" value="([^"]+)"', html)
    assert fix
    while fix:
        r = client.post("/fix", data={"next": "/changes", "issue": fix.group(1).replace("&#34;", '"'), "fix": fix.group(2)}, follow_redirects=True)
        html = r.get_data(as_text=True)
        fix = re.search(r'name="issue" value="([^"]+)"><input type="hidden" name="fix" value="([^"]+)"', html)
    assert "resolved" in html


def test_manual_cell_edit_validates_live(client):
    client.get("/roster")
    r = client.post("/cell", data={"next": "/roster", "e": "E06", "d": "2026-11-10", "status": "L"}, follow_redirects=True)
    assert b"blocking issue" in r.data and b"Kaya Naturals" in r.data


def test_master_data_crud(client):
    client.get("/roster")
    r = client.post("/row/save", data={"next": "/setup?entity=brands", "entity": "brands", "id": "", "name": "Test Brand"}, follow_redirects=True)
    assert b"Test Brand" in r.data
    r = client.post("/row/save", data={"next": "/setup?entity=brands", "entity": "brands", "id": "", "name": ""}, follow_redirects=True)
    assert b"required" in r.data
    r = client.post("/row/save", data={"entity": "processes", "id": "", "brand_id": "B01", "name": "X", "calendar": "MON_SAT", "min_staff": "1",
                                       "special_days": "bad line"}, follow_redirects=True)
    assert b"not understood" in r.data


def test_open_redirect_is_blocked(client):
    client.get("/roster")
    r = client.post("/autorepair", data={"next": "https://evil.example/"})
    assert r.headers["Location"] == "/roster"


def test_exports_and_reset(client):
    client.get("/roster")
    assert client.get("/export/roster.csv").data.startswith(b"Employee,Pod,")
    assert b"Severity,Type,Date,Message" in client.get("/export/issues.csv").data
    assert client.post("/reset", data={"next": "/roster"}, follow_redirects=True).status_code == 200


def test_sessions_are_isolated(client):
    client.get("/roster")
    client.post("/row/save", data={"next": "/setup", "entity": "brands", "id": "", "name": "Only Mine"})
    other = appmod.app.test_client()
    assert b"Only Mine" not in other.get("/setup?entity=brands").data
