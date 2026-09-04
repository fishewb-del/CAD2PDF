"""
Tests for the memory and time budgets that keep one big drawing from
taking the whole server down with it.

The failure these guard against is specific: a drawing needs more memory
than the instance has, the kernel kills the gunicorn worker, and the
browser is handed an empty response it cannot parse - or a request that
never settles at all. What has to be true is that the *server* notices
first and answers.
"""

import io
import os
import time

import pytest

from cad2pdf import hostlimits
from cad2pdf.sandbox import ChildFailed, WorkloadStopped, run_guarded


# Targets live at module level so this file reads the same whether or not
# the platform's start method pickles them.
def _return_value(value):
    return value


def _eat_memory(target_mb):
    """Allocate until well past target_mb, in chunks the guard can catch."""
    held = []
    for _ in range(int(target_mb) * 2):
        held.append(bytearray(1024 * 1024))
        time.sleep(0.002)
    return len(held)


def _sleep_forever():
    time.sleep(600)


def _finish_quickly():
    """Work that is over well inside one poll interval."""
    time.sleep(0.05)
    return "done"


def _raise_value_error():
    raise ValueError("a scale of zero is not a scale")


# --- host limits ----------------------------------------------------------

def test_container_limit_is_preferred_over_the_machines_memory(tmp_path, monkeypatch):
    """
    A 512 MB container on a 64 GB host still only gets 512 MB, and
    /proc/meminfo reports the host. Reading the wrong one is how a budget
    ends up permissive enough to be useless.
    """
    limit = tmp_path / "memory.max"
    limit.write_text(str(512 * 1024 * 1024), encoding="ascii")
    monkeypatch.setattr(hostlimits, "_CGROUP_V2", str(limit))

    assert hostlimits.container_memory_mb() == pytest.approx(512)


def test_an_unlimited_cgroup_reads_as_no_limit(tmp_path, monkeypatch):
    """cgroup reports a number near 2**63 rather than saying 'unlimited'."""
    limit = tmp_path / "memory.max"
    limit.write_text("9223372036854771712", encoding="ascii")
    monkeypatch.setattr(hostlimits, "_CGROUP_V2", str(limit))
    monkeypatch.setattr(hostlimits, "_CGROUP_V1", str(tmp_path / "absent"))

    assert hostlimits.container_memory_mb() is None


def test_the_budget_can_be_set_and_turned_off(monkeypatch):
    monkeypatch.setenv("CAD2PDF_MEMORY_BUDGET_MB", "250")
    assert hostlimits.memory_budget_mb() == 250

    monkeypatch.setenv("CAD2PDF_MEMORY_BUDGET_MB", "0")
    assert hostlimits.memory_budget_mb() is None


# --- the guarded runner ---------------------------------------------------

def test_work_that_fits_returns_its_result():
    assert run_guarded(_return_value, args=({"scale": 50},)) == {"scale": 50}


def test_work_that_eats_memory_is_stopped_and_the_parent_survives():
    """
    The whole point. The child is stopped at the budget and the caller is
    still alive to say so, rather than being killed alongside it.
    """
    before = hostlimits.current_rss_mb()

    with pytest.raises(WorkloadStopped) as caught:
        run_guarded(_eat_memory, args=(4096,), memory_mb=before + 150)

    assert caught.value.kind == "memory"
    assert caught.value.detail["budget_mb"] > 0
    # Nothing leaked into this process: the allocation happened elsewhere.
    assert hostlimits.current_rss_mb() < before + 100


def test_short_work_is_still_measured_before_its_result_is_accepted():
    """
    Regression. The budget used to be checked only after waiting on the
    child's pipe, so a child that finished inside one poll interval handed
    back its result having never been measured. Whether an oversized
    drawing was caught then came down to how fast the machine was: this
    passed locally at 0.17s of work against a 0.2s wait, and failed on CI
    where the same work finished sooner.
    """
    with pytest.raises(WorkloadStopped) as caught:
        run_guarded(_finish_quickly, memory_mb=1)

    assert caught.value.kind == "memory"


def test_work_that_runs_too_long_is_stopped():
    with pytest.raises(WorkloadStopped) as caught:
        run_guarded(_sleep_forever, timeout=1.0)

    assert caught.value.kind == "time"


def test_an_error_inside_the_child_keeps_its_type_and_message():
    """
    The routes tell a bad scale from a missing font by exception type, so
    the type has to survive being carried back from another process.
    """
    with pytest.raises(ChildFailed) as caught:
        run_guarded(_raise_value_error)

    assert caught.value.exc_type == "ValueError"
    assert "not a scale" in str(caught.value)


# --- the routes -----------------------------------------------------------

@pytest.fixture()
def client():
    import app as appmod

    appmod.app.config.update(TESTING=True)
    return appmod.app.test_client()


def _upload(client, route, path, **form):
    with open(path, "rb") as fh:
        data = {"file": (io.BytesIO(fh.read()), os.path.basename(path))}
    data.update(form)
    return client.post(route, data=data, content_type="multipart/form-data")


def test_a_drawing_too_big_for_the_server_gets_an_explanation(client, monkeypatch):
    """
    Not a 502 with an empty body. The reply says what ran out, that the
    drawing is not at fault, and what would make it work.
    """
    monkeypatch.setenv("CAD2PDF_MEMORY_BUDGET_MB", "10")

    res = _upload(client, "/api/convert", "examples/sample-floor-plan.dxf")
    payload = res.get_json()

    assert res.status_code == 507
    assert payload["ok"] is False
    assert "memory" in payload["error"]
    assert "Nothing is wrong with the drawing" in payload["error"]


def test_a_normal_drawing_still_converts_through_the_guard(client):
    res = _upload(client, "/api/convert", "examples/sample-floor-plan.dxf",
                  paper="ARCH D", units="auto")
    payload = res.get_json()

    assert res.status_code == 200
    assert payload["ok"] is True
    assert payload["pdf_b64"]


def test_a_bad_scale_still_reads_as_a_bad_scale_not_a_server_failure(client):
    """The error taxonomy has to survive the process boundary."""
    res = _upload(client, "/api/convert", "examples/sample-floor-plan.dxf",
                  scale="banana")

    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_status_reports_what_this_server_can_take(client):
    limits = client.get("/api/status").get_json()["limits"]

    assert limits["convert_timeout_seconds"] > 0
    assert limits["preview_timeout_seconds"] > 0
    assert "memory_budget_mb" in limits
    assert "memory_total_mb" in limits
