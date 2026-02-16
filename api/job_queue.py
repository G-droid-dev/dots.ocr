"""
In-memory async job queue for long-running parse operations.
Used by ``POST /parse/async`` to queue multi-page PDF parsing
and by ``GET /result/{job_id}`` to poll progress.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    job_id: str
    file_name: str = ""
    total_pages: int = 0
    pages_done: int = 0
    status: JobStatus = JobStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None

    @property
    def processing_time(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at or time.time()
        return round(end - self.started_at, 2)

    @property
    def progress(self) -> str:
        return f"{self.pages_done}/{self.total_pages}"

    @property
    def estimated_remaining(self) -> Optional[float]:
        if self.pages_done == 0 or self.started_at is None:
            return None
        elapsed = time.time() - self.started_at
        per_page = elapsed / self.pages_done
        remaining = (self.total_pages - self.pages_done) * per_page
        return round(remaining, 1)


class JobQueue:
    """Thread-safe in-memory job store."""

    def __init__(self, max_jobs: int = 100):
        self._jobs: Dict[str, Job] = {}
        self._max_jobs = max_jobs

    def create_job(self, file_name: str, total_pages: int) -> Job:
        """Create a new job and return it."""
        # Evict oldest completed jobs if at capacity
        if len(self._jobs) >= self._max_jobs:
            self._evict_old()

        job_id = uuid.uuid4().hex[:8]
        job = Job(job_id=job_id, file_name=file_name, total_pages=total_pages)
        self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def update_progress(self, job_id: str, pages_done: int) -> None:
        job = self._jobs.get(job_id)
        if job:
            job.pages_done = pages_done

    def mark_started(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job:
            job.status = JobStatus.PROCESSING
            job.started_at = time.time()

    def mark_completed(self, job_id: str, result: Any) -> None:
        job = self._jobs.get(job_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.result = result
            job.finished_at = time.time()
            job.pages_done = job.total_pages

    def mark_failed(self, job_id: str, error: str) -> None:
        job = self._jobs.get(job_id)
        if job:
            job.status = JobStatus.FAILED
            job.error = error
            job.finished_at = time.time()

    def _evict_old(self) -> None:
        """Remove oldest completed/failed jobs to make room."""
        terminal = [
            j for j in self._jobs.values()
            if j.status in (JobStatus.COMPLETED, JobStatus.FAILED)
        ]
        terminal.sort(key=lambda j: j.created_at)
        to_remove = max(1, len(terminal) // 2)
        for j in terminal[:to_remove]:
            del self._jobs[j.job_id]


# Singleton instance used by the app
job_queue = JobQueue()
