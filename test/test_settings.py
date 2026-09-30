"""Step-1 acceptance: settings load and an event lands in the JSONL log."""

import json

from setting import get_settings


def test_settings_load():
    s = get_settings()
    assert s.model.base_url.startswith("http")
    assert s.model.name
    assert s.limits.max_records == 30
    assert s.limits.llm_concurrency == 8
    assert s.limits.wall_clock_minutes == 90
    assert s.limits.max_review_iterations == 3
    assert s.paths.skills_dir.name == "skills"
    assert "broad" in {q["id"] for q in s.queries_config["queries"]}
    assert s.sources.pubmed.base_url.endswith("/eutils")
    assert s.sources.ctgov.base_url.endswith("/api/v2/studies")


def test_event_logged(tmp_path):
    from mito_harness.logging_events import EventBus, new_run_id

    run_id = new_run_id()
    bus = EventBus(run_id=run_id, outputs_dir=tmp_path, console_format="{ts} [{event}] {agent} {tool} {detail}")
    bus.emit(
        "tool_called",
        agent="literature_search",
        tool="pubmed_search",
        step_id="s1",
        payload={"query": "elamipretide"},
    )
    lines = (tmp_path / f"run_{run_id}.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "tool_called"
    assert record["agent"] == "literature_search"
    assert record["tool"] == "pubmed_search"
    assert record["run_id"] == run_id
    assert "ts" in record


def test_disk_cache_roundtrip(tmp_path):
    from mito_harness.cache import DiskCache

    cache = DiskCache(tmp_path / "cache")
    assert cache.get("pubmed", {"term": "mitoq"}) is None
    cache.set("pubmed", {"term": "mitoq"}, {"count": 5})
    assert cache.get("pubmed", {"term": "mitoq"}) == {"count": 5}
    cache.clear()
    assert cache.get("pubmed", {"term": "mitoq"}) is None
