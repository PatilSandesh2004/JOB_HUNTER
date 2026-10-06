"""Durable agent task queue: retries, the never-retry-after-submit rule, restart recovery, claiming."""

import asyncio

from sqlalchemy import select, update

from ai_service.app.database.session import AsyncSessionLocal
from ai_service.app.integrations.browser.form_filler import FillOutcome, FillResult
from ai_service.app.models.task import TaskModel
from ai_service.app.repositories.task_repository import TaskKind, TaskRepository, TaskStatus
from ai_service.app.services.applications.application_service import INTERRUPTED_SUBMIT
from ai_service.app.services.tasks.runner import TaskRunner
from ai_service.tests.fakes import RESUME


async def _job_id(client) -> str:
    """Profile from the sample resume, plus the stored Acme job (an auto-fillable Lever posting)."""
    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    results = (
        await client.post("/api/v1/search", json={"roles": ["Backend Engineer"], "strict_location": False})
    ).json()["results"]
    return next(r["job"]["id"] for r in results if r["job"]["company"] == "Acme")


async def _app(client, app_id: str) -> dict:
    return (await client.get(f"/api/v1/applications/{app_id}")).json()


async def _tasks(app_id: str) -> list[TaskModel]:
    async with AsyncSessionLocal() as session:
        stmt = select(TaskModel).where(TaskModel.application_id == app_id).order_by(TaskModel.created_at)
        return list((await session.scalars(stmt)).all())


def _failed(message: str, submit_attempted: bool = False) -> FillResult:
    result = FillResult(FillOutcome.FAILED, message=message)
    result.submit_attempted = submit_attempted
    return result


async def test_transient_fill_failure_is_retried_with_backoff(client):
    job_id = await _job_id(client)
    client.filler.script = [_failed("TimeoutError: page did not load")]
    app_id = (await client.post("/api/v1/applications", json={"job_id": job_id})).json()["id"]

    slow_retry = TaskRunner(AsyncSessionLocal, client.service.task_handlers(), backoff_seconds=[3600])
    await slow_retry.run_due_once()
    app = await _app(client, app_id)
    assert app["status"] == "PROCESSING" and "retrying" in app["error"]
    [task] = await _tasks(app_id)
    assert task.status == TaskStatus.QUEUED and task.attempts == 1

    # Not due yet: nothing runs. Once the backoff has passed, the retry succeeds.
    assert await slow_retry.run_due_once() == 0
    async with AsyncSessionLocal() as session:
        await session.execute(update(TaskModel).where(TaskModel.id == task.id).values(run_after=task.created_at))
        await session.commit()
    await slow_retry.run_due_once()
    assert (await _app(client, app_id))["status"] == "PENDING_APPROVAL"
    assert len(client.filler.calls) == 2


async def test_fill_gives_up_after_max_attempts(client):
    job_id = await _job_id(client)
    client.filler.script = [_failed("boom")] * 5
    app_id = (await client.post("/api/v1/applications", json={"job_id": job_id})).json()["id"]
    await client.runner.run_due_once()
    app = await _app(client, app_id)
    assert app["status"] == "FAILED" and app["error"] == "boom"
    assert len(client.filler.calls) == client.service.max_attempts
    [task] = await _tasks(app_id)
    assert task.status == TaskStatus.DONE and task.attempts == client.service.max_attempts


async def test_submit_is_never_retried_after_click(client):
    job_id = await _job_id(client)
    app_id = (await client.post("/api/v1/applications", json={"job_id": job_id})).json()["id"]
    await client.runner.run_due_once()
    client.filler.script = [_failed("TimeoutError after click", submit_attempted=True)]

    await client.post(f"/api/v1/applications/{app_id}/approve")
    calls_before = len(client.filler.calls)
    await client.runner.run_due_once()

    app = await _app(client, app_id)
    assert app["status"] == "FAILED" and "may have gone through" in app["error"]
    assert len(client.filler.calls) == calls_before + 1


async def test_restart_resumes_fills_and_hands_back_interrupted_submits(client):
    job_id = await _job_id(client)
    app_id = (await client.post("/api/v1/applications", json={"job_id": job_id})).json()["id"]
    [task] = await _tasks(app_id)
    async with AsyncSessionLocal() as session:  # simulate a crash mid-fill
        assert await TaskRepository(session).claim(task.id) is not None

    await client.service.recover_interrupted()
    [task] = await _tasks(app_id)
    assert task.status == TaskStatus.QUEUED
    await client.runner.run_due_once()
    assert (await _app(client, app_id))["status"] == "PENDING_APPROVAL"

    await client.post(f"/api/v1/applications/{app_id}/approve")
    submit_task = (await _tasks(app_id))[-1]
    assert submit_task.kind == TaskKind.SUBMIT_APPLICATION
    async with AsyncSessionLocal() as session:  # simulate a crash mid-submit
        await TaskRepository(session).claim(submit_task.id)
    calls_before = len(client.filler.calls)

    await client.service.recover_interrupted()
    app = await _app(client, app_id)
    assert app["status"] == "NEEDS_MANUAL" and app["error"] == INTERRUPTED_SUBMIT
    assert await client.runner.run_due_once() == 0
    assert len(client.filler.calls) == calls_before  # never resubmitted automatically


async def test_two_workers_never_run_the_same_task(client):
    job_id = await _job_id(client)
    await client.post("/api/v1/applications", json={"job_id": job_id})
    other = TaskRunner(AsyncSessionLocal, client.service.task_handlers())
    await asyncio.gather(client.runner.run_due_once(), other.run_due_once())
    assert len(client.filler.calls) == 1


async def test_unknown_task_kind_fails_cleanly(client):
    async with AsyncSessionLocal() as session:
        task = await TaskRepository(session).enqueue(TaskKind.DRAFT_COVER_LETTER)
    runner = TaskRunner(AsyncSessionLocal, handlers={})
    assert await runner.run_due_once() == 1
    async with AsyncSessionLocal() as session:
        stored = await session.get(TaskModel, task.id)
    assert stored.status == TaskStatus.FAILED and "No handler" in stored.last_error


async def test_background_loop_picks_up_new_work(client):
    job_id = await _job_id(client)
    runner = TaskRunner(AsyncSessionLocal, client.service.task_handlers(), poll_seconds=30)
    client.service.on_enqueue = runner.notify
    await runner.start()
    try:
        app_id = (await client.post("/api/v1/applications", json={"job_id": job_id})).json()["id"]
        for _ in range(100):  # notify() wakes the loop long before the 30 s poll
            if (await _app(client, app_id))["status"] != "PROCESSING":
                break
            await asyncio.sleep(0.05)
        assert (await _app(client, app_id))["status"] == "PENDING_APPROVAL"
    finally:
        await runner.stop()
