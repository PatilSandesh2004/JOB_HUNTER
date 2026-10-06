"""Background task runner backed by the `agent_tasks` table.

Tasks are claimed atomically, so a restart (or a second process) never runs one twice. A handler raises
`RetryLater` to be retried with backoff; any other exception fails the task. Periodic jobs (e.g. job
re-checks) run on the same loop.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.app.models.task import TaskModel
from ai_service.app.repositories.task_repository import TaskRepository, TaskStatus

logger = logging.getLogger("jobpilot.tasks")

Handler = Callable[[TaskModel], Awaitable[None]]


class RetryLater(Exception):  # noqa: N818  (control flow, not an error)
    """Raised by a handler that hit a transient failure and has attempts left."""


class TaskFailed(Exception):  # noqa: N818
    """Raised by a handler that already recorded a terminal failure; skips the traceback log."""


@dataclass
class PeriodicJob:
    name: str
    interval_seconds: float
    run: Callable[[], Awaitable[object]]
    initial_delay: float = 60.0
    _next_at: float = field(default=0.0, init=False)


class TaskRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        handlers: dict[str, Handler],
        *,
        concurrency: int = 3,
        poll_seconds: float = 2.0,
        backoff_seconds: Sequence[float] = (30, 120, 600),
        periodic: Sequence[PeriodicJob] = (),
    ) -> None:
        self.session_factory = session_factory
        self.handlers = handlers
        self.concurrency = max(1, concurrency)
        self.poll_seconds = poll_seconds
        self.backoff_seconds = list(backoff_seconds) or [30]
        self.periodic = list(periodic)
        self._wake = asyncio.Event()
        self._inflight: dict[str, asyncio.Task] = {}
        self._loop_task: asyncio.Task | None = None

    # ---- control ----------------------------------------------------------
    def notify(self) -> None:
        """Wake the loop now instead of at the next poll (call after enqueueing)."""
        self._wake.set()

    async def start(self) -> None:
        now = monotonic()
        for job in self.periodic:
            job._next_at = now + job.initial_delay
        self._loop_task = asyncio.create_task(self._loop(), name="jobpilot-task-runner")

    async def stop(self) -> None:
        """Stop polling. In-flight tasks are cancelled and stay 'running'; startup recovery handles them."""
        tasks = [t for t in (self._loop_task, *self._inflight.values()) if t is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._loop_task = None

    async def run_due_once(self) -> int:
        """Run every task that is due now, to completion. Used by tests and one-shot workers."""
        processed = 0
        while True:
            async with self.session_factory() as session:
                ids = await TaskRepository(session).due_ids(self.concurrency)
            if not ids:
                return processed
            processed += sum(await asyncio.gather(*(self._run_one(i) for i in ids)))

    # ---- loop ---------------------------------------------------------------
    async def _loop(self) -> None:
        while True:
            try:
                await self._dispatch()
                await self._run_periodic()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Task loop iteration failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            self._wake.clear()

    async def _dispatch(self) -> None:
        free = self.concurrency - len(self._inflight)
        if free <= 0:
            return
        async with self.session_factory() as session:
            ids = await TaskRepository(session).due_ids(free, exclude=set(self._inflight))
        for task_id in ids:
            task = asyncio.create_task(self._run_one(task_id), name=f"jobpilot-task-{task_id}")
            self._inflight[task_id] = task
            task.add_done_callback(lambda _, tid=task_id: self._finished(tid))

    def _finished(self, task_id: str) -> None:
        self._inflight.pop(task_id, None)
        self.notify()  # a slot is free: look for more work

    async def _run_periodic(self) -> None:
        now = monotonic()
        for job in self.periodic:
            if now < job._next_at:
                continue
            job._next_at = now + job.interval_seconds
            try:
                await job.run()
            except Exception:
                logger.exception("Periodic job %s failed", job.name)

    async def _run_one(self, task_id: str) -> bool:
        async with self.session_factory() as session:
            task = await TaskRepository(session).claim(task_id)
        if task is None:
            return False
        status, error, retry_in = TaskStatus.DONE, None, None
        try:
            handler = self.handlers.get(task.kind)
            if handler is None:
                raise RuntimeError(f"No handler registered for task kind {task.kind!r}")
            await handler(task)
        except RetryLater as exc:
            status, error = TaskStatus.QUEUED, str(exc)
            retry_in = self.backoff_seconds[min(task.attempts, len(self.backoff_seconds)) - 1]
            logger.info(
                "Task %s (%s) attempt %d failed, retrying in %ss: %s", task.id, task.kind, task.attempts, retry_in, exc
            )
        except TaskFailed as exc:
            status, error = TaskStatus.FAILED, str(exc)
        except Exception as exc:
            status, error = TaskStatus.FAILED, f"{type(exc).__name__}: {exc}"
            logger.exception("Task %s (%s) failed", task.id, task.kind)
        async with self.session_factory() as session:
            await TaskRepository(session).finish(task.id, status, error, retry_in)
        return True
