"""Local scheduling helpers for recurring NewsWeaver runs."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import find_topic, load_config
from .utils import atomic_write_json, get_data_dir, read_json


SCHEDULE_PATH = get_data_dir() / "schedule.json"


def load_schedule(path: Path | None = None) -> dict:
    schedule_path = path or SCHEDULE_PATH
    data = read_json(schedule_path)
    if not data:
        data = {"jobs": []}
    data.setdefault("jobs", [])
    return data


def save_schedule(schedule: dict, path: Path | None = None) -> None:
    atomic_write_json(path or SCHEDULE_PATH, schedule)


def add_job(topic: str, cadence: str = "daily", hour: int = 9, minute: int = 0, enabled: bool = True) -> dict:
    if cadence not in {"daily", "weekly"}:
        raise ValueError("cadence must be daily or weekly")
    schedule = load_schedule()
    job_id = slugify(f"{topic}-{cadence}-{hour:02d}{minute:02d}")
    job = {
        "id": job_id,
        "topic": topic,
        "cadence": cadence,
        "hour": hour,
        "minute": minute,
        "enabled": enabled,
        "last_run_at": "",
        "next_run_at": compute_next_run(cadence, hour, minute).isoformat(timespec="minutes"),
    }
    schedule["jobs"] = [item for item in schedule["jobs"] if item.get("id") != job_id]
    schedule["jobs"].append(job)
    save_schedule(schedule)
    return job


def remove_job(job_id: str) -> bool:
    schedule = load_schedule()
    before = len(schedule["jobs"])
    schedule["jobs"] = [job for job in schedule["jobs"] if job.get("id") != job_id]
    save_schedule(schedule)
    return len(schedule["jobs"]) < before


def due_jobs(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    schedule = load_schedule()
    jobs = []
    for job in schedule.get("jobs", []):
        if not job.get("enabled", True):
            continue
        next_run = parse_dt(job.get("next_run_at")) or compute_next_run(job.get("cadence", "daily"), int(job.get("hour", 9)), int(job.get("minute", 0)), now=now - timedelta(days=1))
        if next_run <= now:
            jobs.append(job)
    return jobs


def run_due_jobs(config_path: str | None = None, now: datetime | None = None) -> list[dict]:
    from .generator import run_generate

    now = now or datetime.now()
    config = load_config(config_path)
    schedule = load_schedule()
    results = []
    by_id = {job["id"]: job for job in schedule.get("jobs", [])}
    for job in due_jobs(now):
        topic = find_topic(config, job["topic"])
        if not topic:
            results.append({"job_id": job["id"], "topic": job["topic"], "ok": False, "error": "topic not found"})
            continue
        try:
            path = run_generate(
                config,
                topic,
                model=config.get("llm", {}).get("model", "gpt-4o-mini"),
                limit=config.get("search", {}).get("default_limit", 10),
            )
            target = by_id[job["id"]]
            target["last_run_at"] = now.isoformat(timespec="minutes")
            target["next_run_at"] = compute_next_run(
                target.get("cadence", "daily"),
                int(target.get("hour", 9)),
                int(target.get("minute", 0)),
                now=now,
            ).isoformat(timespec="minutes")
            results.append({"job_id": job["id"], "topic": job["topic"], "ok": True, "path": str(path)})
        except Exception as exc:
            results.append({"job_id": job["id"], "topic": job["topic"], "ok": False, "error": str(exc)})
    schedule["jobs"] = list(by_id.values())
    save_schedule(schedule)
    return results


def run_scheduler_loop(config_path: str | None = None, interval_seconds: int = 300) -> None:
    while True:
        run_due_jobs(config_path=config_path)
        time.sleep(interval_seconds)


def compute_next_run(cadence: str, hour: int, minute: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=7 if cadence == "weekly" else 1)
    return candidate


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def slugify(value: str) -> str:
    safe = []
    for char in value.lower():
        if char.isalnum():
            safe.append(char)
        elif char in {"-", "_", " "}:
            safe.append("-")
    result = "".join(safe).strip("-")
    while "--" in result:
        result = result.replace("--", "-")
    return result or "job"
