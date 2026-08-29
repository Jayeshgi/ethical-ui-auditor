import asyncio
from datetime import UTC, datetime

import pytest

from app.schemas import ScanRequest, ScanResponse
from app.scans import jobs


@pytest.mark.asyncio
async def test_scan_job_transitions_without_blocking_creation(monkeypatch) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_scan(request: ScanRequest) -> ScanResponse:
        started.set()
        await release.wait()
        return ScanResponse(scan_id="capture-1", status="completed", pages=[], warnings=[])

    monkeypatch.setattr(jobs, "perform_scan", fake_scan)
    manager = jobs.InMemoryScanJobManager()
    request = ScanRequest(url="https://example.com", max_pages=1, scroll_steps=0)

    created = await manager.create(request)
    assert created.status == "queued"
    await asyncio.wait_for(started.wait(), timeout=1)
    assert (await manager.get(created.scan_id)).status == "running"

    release.set()
    for _ in range(20):
        completed = await manager.get(created.scan_id)
        if completed.status == "completed":
            break
        await asyncio.sleep(0)

    assert completed.status == "completed"
    assert completed.result is not None
    assert completed.result.scan_id == "capture-1"


@pytest.mark.asyncio
async def test_scan_job_records_background_failure(monkeypatch) -> None:
    async def failed_scan(request: ScanRequest) -> ScanResponse:
        raise RuntimeError("browser crashed")

    monkeypatch.setattr(jobs, "perform_scan", failed_scan)
    manager = jobs.InMemoryScanJobManager()
    created = await manager.create(ScanRequest(url="https://example.com"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    failed = await manager.get(created.scan_id)
    assert failed.status == "failed"
    assert failed.error == "RuntimeError: browser crashed"
