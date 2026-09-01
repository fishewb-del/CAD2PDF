"""
Tests for the deployment dashboard and the optional password gate.

These are the two things that decide whether a Render deploy is usable:
can you tell which commit is live, and can you keep strangers out.
"""

import base64

import pytest

import app as app_module
from app import app as flask_app
from cad2pdf.buildinfo import format_uptime, get_build_info


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def render_env(monkeypatch):
    """Pretend we are running on Render, with the vars Render injects."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RENDER_SERVICE_NAME", "cad2pdf")
    monkeypatch.setenv("RENDER_REGION", "oregon")
    monkeypatch.setenv("RENDER_GIT_REPO_SLUG", "fishewb-del/CAD2PDF")
    monkeypatch.setenv("RENDER_GIT_BRANCH", "main")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)


def test_status_page_renders(client):
    res = client.get("/status")
    assert res.status_code == 200
    assert b"Deployment status" in res.data


def test_api_status_reports_features_and_limits(client):
    body = client.get("/api/status").get_json()
    assert body["status"] == "ok"
    assert body["features"]["dxf"] is True
    assert body["limits"]["max_upload_mb"] == app_module.MAX_UPLOAD_MB
    assert "python" in body["versions"]


def test_build_info_links_back_to_the_github_commit(render_env):
    info = get_build_info()
    assert info.host == "Render"
    assert info.short_commit == "aaaaaaa"
    assert info.repo_url == "https://github.com/fishewb-del/CAD2PDF"
    assert info.commit_url == (
        "https://github.com/fishewb-del/CAD2PDF/commit/" + "a" * 40
    )
    assert info.branch_url == (
        "https://github.com/fishewb-del/CAD2PDF/tree/main"
    )


def test_status_page_shows_the_commit_link(client, render_env):
    res = client.get("/status")
    assert b"/commit/" + b"a" * 40 in res.data


def test_build_info_survives_a_host_with_no_git_metadata(monkeypatch):
    for var in ("RENDER", "RENDER_GIT_REPO_SLUG", "RENDER_GIT_BRANCH",
                "RENDER_GIT_COMMIT", "FLY_APP_NAME",
                "CAD2PDF_GIT_REPO", "CAD2PDF_GIT_BRANCH",
                "CAD2PDF_GIT_COMMIT"):
        monkeypatch.delenv(var, raising=False)
    # A commit may still be found via local git; the point is that the
    # GitHub links are simply absent rather than half-built or crashing.
    info = get_build_info()
    assert info.repo_url is None
    assert info.commit_url is None


@pytest.mark.parametrize("seconds,expected", [
    (12, "12s"),
    (95, "1m 35s"),
    (3700, "1h 1m"),
    (90000, "1d 1h"),
])
def test_uptime_reads_naturally(seconds, expected):
    assert format_uptime(seconds) == expected


# ---- optional password gate -------------------------------------------

@pytest.fixture
def guarded(monkeypatch):
    monkeypatch.setattr(app_module, "AUTH_USERNAME", "edger")
    monkeypatch.setattr(app_module, "AUTH_PASSWORD", "site-secret")


def _basic(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_no_password_configured_means_no_gate(client):
    assert client.get("/").status_code == 200


def test_gate_blocks_anonymous_visitors(client, guarded):
    res = client.get("/")
    assert res.status_code == 401
    assert res.headers["WWW-Authenticate"].startswith("Basic")


def test_gate_lets_the_right_credentials_through(client, guarded):
    res = client.get("/", headers=_basic("edger", "site-secret"))
    assert res.status_code == 200


def test_gate_rejects_a_wrong_password(client, guarded):
    res = client.get("/", headers=_basic("edger", "nope"))
    assert res.status_code == 401


def test_gate_protects_the_conversion_endpoint(client, guarded):
    assert client.post("/api/convert").status_code == 401


def test_health_check_stays_open_so_deploys_pass(client, guarded):
    # Render polls /healthz without credentials. If the gate covered it,
    # every deploy would be marked failed and rolled back.
    assert client.get("/healthz").status_code == 200
