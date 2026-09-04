"""
Tests for the Cloud Run deployment config.

These are not tests of Google's behaviour. They pin the handful of
decisions that are easy to break later and expensive to discover in
production: the ordering of the three timeouts, and the concurrency
setting that keeps one instance from taking on more drawings than its
memory can hold.
"""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "deploy" / "cloudrun.env.yaml"
DEPLOY_SCRIPT = ROOT / "deploy" / "cloudrun.sh"


@pytest.fixture(scope="module")
def env():
    return yaml.safe_load(ENV_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def script():
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _default(script: str, name: str) -> str:
    """Pull the fallback out of a NAME="${NAME:-value}" line."""
    match = re.search(rf'^{name}="\$\{{{name}:-([^}}]+)\}}"', script, re.M)
    assert match, f"{name} is not set with a default in cloudrun.sh"
    return match.group(1)


def test_every_value_is_a_string(env):
    """
    gcloud rejects an env-vars file with non-string values, and a bare 240
    in YAML is an int. Catching that here beats catching it fifteen minutes
    into a build.
    """
    non_strings = {k: v for k, v in env.items() if not isinstance(v, str)}
    assert not non_strings, f"quote these in cloudrun.env.yaml: {non_strings}"


def test_the_app_gives_up_before_anything_above_it_does(env, script):
    """
    The whole point of the guarded conversion is that the *app* answers.
    If gunicorn or Cloud Run were to cut in first, the user would get a
    killed connection and an unparseable empty body again, which is the
    bug this deployment exists to avoid.
    """
    app_budget = float(env["CAD2PDF_CONVERT_TIMEOUT"])
    gunicorn_budget = float(env["GUNICORN_TIMEOUT"])
    cloud_run_budget = float(_default(script, "TIMEOUT"))

    assert app_budget < gunicorn_budget, "the app must stop before gunicorn"
    assert gunicorn_budget <= cloud_run_budget, (
        "gunicorn must not outlive the Cloud Run request limit"
    )
    assert float(env["CAD2PDF_PREVIEW_TIMEOUT"]) <= app_budget


def test_one_drawing_at_a_time(script):
    """
    Cloud Run defaults to 80 concurrent requests per instance. A conversion
    can want most of a gigabyte, so the default would run a 2 GB instance
    out of memory as soon as two people converted at once.
    """
    assert _default(script, "CONCURRENCY") == "1"


def test_the_memory_budget_leaves_room_inside_the_instance(env, script):
    """
    The budget is what one drawing may use. It has to be under the
    instance's own memory, or it is not a budget at all.
    """
    budget_mb = float(env["CAD2PDF_MEMORY_BUDGET_MB"])
    memory = _default(script, "MEMORY")

    assert memory.endswith("Gi"), f"unexpected memory unit: {memory}"
    instance_mb = float(memory[:-2]) * 1024

    assert budget_mb < instance_mb
    # Enough left over for the interpreter, gunicorn and the response.
    assert instance_mb - budget_mb >= 256


def test_the_budget_fits_the_drawing_this_was_sized_for(env):
    """
    The reported cross dock drawing peaked at 914 MB. A budget under that
    would reject the very drawing this deployment was set up to convert.
    """
    assert float(env["CAD2PDF_MEMORY_BUDGET_MB"]) > 914


def test_uploads_are_capped_below_what_the_instance_can_hold(env):
    assert 0 < float(env["CAD2PDF_MAX_UPLOAD_MB"]) <= 64


def test_the_script_is_safe_to_re_run(script):
    """Deploying a change is the same command as deploying the first time."""
    assert "set -euo pipefail" in script
    assert "gcloud run deploy" in script
    assert "--env-vars-file deploy/cloudrun.env.yaml" in script


def test_a_runaway_cannot_scale_without_limit(script):
    assert int(_default(script, "MAX_INSTANCES")) <= 10
    # Scaling to zero is what keeps an idle service free.
    assert _default(script, "MIN_INSTANCES") == "0"


def test_the_default_paper_is_one_the_app_knows(env):
    from cad2pdf.converter import PAPER_SIZES_MM

    assert env["CAD2PDF_DEFAULT_PAPER"] in PAPER_SIZES_MM
