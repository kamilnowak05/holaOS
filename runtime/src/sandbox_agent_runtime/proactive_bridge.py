from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, Field

from sandbox_agent_runtime.memory.operations import memory_get, memory_search, memory_status, memory_sync, memory_upsert
from sandbox_agent_runtime.product_config import resolve_product_runtime_config
from sandbox_agent_runtime.runtime_local_state import create_task_proposal, get_workspace

logger = logging.getLogger("sandbox_agent_runtime.proactive_bridge")


class ProactiveBridgeJobType(str, Enum):
    task_proposal_create = "task_proposal.create"
    workspace_snapshot_capture = "workspace.snapshot.capture"
    workspace_memory_status = "workspace.memory.status"
    workspace_memory_search = "workspace.memory.search"
    workspace_memory_get = "workspace.memory.get"
    workspace_memory_upsert = "workspace.memory.upsert"
    workspace_memory_sync = "workspace.memory.sync"
    workspace_memory_refresh = "workspace.memory.refresh"


class ProactiveBridgeResultStatus(str, Enum):
    succeeded = "succeeded"
    failed = "failed"
    unsupported = "unsupported"


class TaskProposalCreateJobPayload(BaseModel):
    workspace_id: str
    task_name: str
    task_prompt: str
    task_generation_rationale: str
    source_event_ids: list[str] = Field(default_factory=list)
    holaboss_user_id: str | None = None


class WorkspaceSnapshotCaptureJobPayload(BaseModel):
    workspace_id: str
    reason: str | None = None


class WorkspaceMemoryRefreshJobPayload(BaseModel):
    workspace_id: str
    reason: str | None = None
    force: bool = False


class WorkspaceMemoryStatusJobPayload(BaseModel):
    workspace_id: str


class WorkspaceMemorySearchJobPayload(BaseModel):
    workspace_id: str
    query: str
    max_results: int = 6
    min_score: float = 0.0


class WorkspaceMemoryGetJobPayload(BaseModel):
    workspace_id: str
    path: str
    from_line: int | None = None
    lines: int | None = None


class WorkspaceMemoryUpsertJobPayload(BaseModel):
    workspace_id: str
    path: str
    content: str
    append: bool = False


class WorkspaceMemorySyncJobPayload(BaseModel):
    workspace_id: str
    reason: str | None = None
    force: bool = False


ProactiveBridgePayload = (
    TaskProposalCreateJobPayload
    | WorkspaceSnapshotCaptureJobPayload
    | WorkspaceMemoryRefreshJobPayload
    | WorkspaceMemoryStatusJobPayload
    | WorkspaceMemorySearchJobPayload
    | WorkspaceMemoryGetJobPayload
    | WorkspaceMemoryUpsertJobPayload
    | WorkspaceMemorySyncJobPayload
)


class ProactiveBridgeJob(BaseModel):
    job_id: str
    job_type: ProactiveBridgeJobType
    workspace_id: str
    sandbox_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    lease_expires_at: datetime | None = None
    payload: ProactiveBridgePayload


class ProactiveBridgeJobResult(BaseModel):
    job_id: str
    status: ProactiveBridgeResultStatus
    workspace_id: str
    job_type: ProactiveBridgeJobType
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    output: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


def bridge_enabled() -> bool:
    raw = (os.getenv("PROACTIVE_ENABLE_REMOTE_BRIDGE") or "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def bridge_poll_interval_seconds() -> float:
    raw = (os.getenv("PROACTIVE_BRIDGE_POLL_INTERVAL_SECONDS") or "").strip()
    if not raw:
        return 5.0
    try:
        return min(max(float(raw), 0.5), 300.0)
    except ValueError:
        return 5.0


def bridge_max_items() -> int:
    raw = (os.getenv("PROACTIVE_BRIDGE_MAX_ITEMS") or "").strip()
    if not raw:
        return 10
    try:
        return min(max(int(raw), 1), 100)
    except ValueError:
        return 10


class HttpPollingLocalBridgeReceiver:
    def __init__(self, *, base_url: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = max(timeout_seconds, 1.0)

    @classmethod
    def from_environment(cls) -> HttpPollingLocalBridgeReceiver:
        base_url = (os.getenv("PROACTIVE_BRIDGE_BASE_URL") or "").strip().rstrip("/")
        if not base_url:
            raise RuntimeError("PROACTIVE_BRIDGE_BASE_URL is required for remote proactive bridge")
        timeout_raw = (os.getenv("PROACTIVE_BRIDGE_TIMEOUT_SECONDS") or "").strip()
        timeout_seconds = 30.0
        if timeout_raw:
            try:
                timeout_seconds = float(timeout_raw)
            except ValueError as exc:
                raise RuntimeError("Invalid PROACTIVE_BRIDGE_TIMEOUT_SECONDS") from exc
        return cls(base_url=base_url, timeout_seconds=timeout_seconds)

    async def receive_jobs(self, *, limit: int = 10) -> list[ProactiveBridgeJob]:
        payload = await self._request_json(
            method="GET",
            path="/api/v1/proactive/bridge/jobs",
            params={"limit": limit},
        )
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            return []
        return [ProactiveBridgeJob.model_validate(item) for item in jobs if isinstance(item, dict)]

    async def report_result(self, result: ProactiveBridgeJobResult) -> None:
        await self._request_json(
            method="POST",
            path="/api/v1/proactive/bridge/results",
            payload=result.model_dump(mode="json"),
        )

    def _headers(self) -> dict[str, str]:
        config = resolve_product_runtime_config(require_auth=True, require_user=False, require_base_url=False)
        headers = dict(config.headers)
        if "X-API-Key" not in headers:
            raise RuntimeError("Runtime bridge auth token is not configured")
        return headers

    async def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                headers=self._headers(),
                trust_env=False,
            ) as client:
                response = await client.request(
                    method=method.upper(),
                    url=f"{self._base_url}{path}",
                    json=payload,
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("Failed to call proactive bridge endpoint") from exc

        if response.status_code >= 400:
            detail = response.text.strip() or f"status={response.status_code}"
            raise RuntimeError(f"Proactive bridge request failed: {detail}")

        if response.status_code == 204 or not response.content:
            return {}

        parsed = response.json()
        if not isinstance(parsed, dict):
            raise TypeError("Proactive bridge endpoint returned invalid payload")
        return parsed


class LocalRuntimeProactiveBridgeExecutor:
    async def execute(self, job: ProactiveBridgeJob) -> ProactiveBridgeJobResult:
        try:
            return await self._execute(job)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(
                "Remote proactive bridge job failed",
                extra={
                    "event": "runtime.proactive_bridge.job",
                    "outcome": "error",
                    "job_id": job.job_id,
                    "job_type": job.job_type.value,
                    "workspace_id": job.workspace_id,
                },
            )
            return ProactiveBridgeJobResult(
                job_id=job.job_id,
                status=ProactiveBridgeResultStatus.failed,
                workspace_id=job.workspace_id,
                job_type=job.job_type,
                error_code="job_execution_failed",
                error_message=str(exc),
            )

    async def _execute(self, job: ProactiveBridgeJob) -> ProactiveBridgeJobResult:
        workspace = get_workspace(job.workspace_id)
        if workspace is None or workspace.deleted_at_utc:
            return ProactiveBridgeJobResult(
                job_id=job.job_id,
                status=ProactiveBridgeResultStatus.failed,
                workspace_id=job.workspace_id,
                job_type=job.job_type,
                error_code="workspace_not_found",
                error_message=f"Workspace '{job.workspace_id}' was not found",
            )

        if job.job_type == ProactiveBridgeJobType.task_proposal_create:
            payload = self._coerce_payload(job.payload, TaskProposalCreateJobPayload)
            if payload is None:
                return ProactiveBridgeJobResult(
                    job_id=job.job_id,
                    status=ProactiveBridgeResultStatus.failed,
                    workspace_id=job.workspace_id,
                    job_type=job.job_type,
                    error_code="invalid_payload",
                    error_message="task_proposal.create job received an invalid payload",
                )
            proposal = create_task_proposal(
                proposal_id=job.job_id,
                workspace_id=payload.workspace_id,
                task_name=payload.task_name,
                task_prompt=payload.task_prompt,
                task_generation_rationale=payload.task_generation_rationale,
                source_event_ids=payload.source_event_ids,
                created_at=datetime.now(UTC).isoformat(),
                state="not_reviewed",
            )
            return ProactiveBridgeJobResult(
                job_id=job.job_id,
                status=ProactiveBridgeResultStatus.succeeded,
                workspace_id=job.workspace_id,
                job_type=job.job_type,
                output={"proposal_id": proposal["proposal_id"]},
            )

        if job.job_type == ProactiveBridgeJobType.workspace_memory_status:
            payload = self._coerce_payload(job.payload, WorkspaceMemoryStatusJobPayload)
            if payload is None:
                return self._invalid_payload_result(job, "workspace.memory.status")
            return ProactiveBridgeJobResult(
                job_id=job.job_id,
                status=ProactiveBridgeResultStatus.succeeded,
                workspace_id=job.workspace_id,
                job_type=job.job_type,
                output={"status": memory_status(workspace_id=payload.workspace_id)},
            )

        if job.job_type == ProactiveBridgeJobType.workspace_memory_search:
            payload = self._coerce_payload(job.payload, WorkspaceMemorySearchJobPayload)
            if payload is None:
                return self._invalid_payload_result(job, "workspace.memory.search")
            return ProactiveBridgeJobResult(
                job_id=job.job_id,
                status=ProactiveBridgeResultStatus.succeeded,
                workspace_id=job.workspace_id,
                job_type=job.job_type,
                output=memory_search(
                    workspace_id=payload.workspace_id,
                    query=payload.query,
                    max_results=payload.max_results,
                    min_score=payload.min_score,
                ),
            )

        if job.job_type == ProactiveBridgeJobType.workspace_memory_get:
            payload = self._coerce_payload(job.payload, WorkspaceMemoryGetJobPayload)
            if payload is None:
                return self._invalid_payload_result(job, "workspace.memory.get")
            return ProactiveBridgeJobResult(
                job_id=job.job_id,
                status=ProactiveBridgeResultStatus.succeeded,
                workspace_id=job.workspace_id,
                job_type=job.job_type,
                output=memory_get(
                    workspace_id=payload.workspace_id,
                    path=payload.path,
                    from_line=payload.from_line,
                    lines=payload.lines,
                ),
            )

        if job.job_type == ProactiveBridgeJobType.workspace_memory_upsert:
            payload = self._coerce_payload(job.payload, WorkspaceMemoryUpsertJobPayload)
            if payload is None:
                return self._invalid_payload_result(job, "workspace.memory.upsert")
            return ProactiveBridgeJobResult(
                job_id=job.job_id,
                status=ProactiveBridgeResultStatus.succeeded,
                workspace_id=job.workspace_id,
                job_type=job.job_type,
                output=memory_upsert(
                    workspace_id=payload.workspace_id,
                    path=payload.path,
                    content=payload.content,
                    append=payload.append,
                ),
            )

        if job.job_type in {
            ProactiveBridgeJobType.workspace_memory_sync,
            ProactiveBridgeJobType.workspace_memory_refresh,
        }:
            expected_model = (
                WorkspaceMemoryRefreshJobPayload
                if job.job_type == ProactiveBridgeJobType.workspace_memory_refresh
                else WorkspaceMemorySyncJobPayload
            )
            payload = self._coerce_payload(job.payload, expected_model)
            if payload is None:
                return self._invalid_payload_result(job, job.job_type.value)
            sync_payload = memory_sync(
                workspace_id=payload.workspace_id,
                reason=payload.reason or "bridge_sync",
                force=payload.force,
            )
            output = {"sync": sync_payload}
            if job.job_type == ProactiveBridgeJobType.workspace_memory_refresh:
                output["alias"] = "workspace.memory.sync"
            return ProactiveBridgeJobResult(
                job_id=job.job_id,
                status=ProactiveBridgeResultStatus.succeeded,
                workspace_id=job.workspace_id,
                job_type=job.job_type,
                output=output,
            )

        return ProactiveBridgeJobResult(
            job_id=job.job_id,
            status=ProactiveBridgeResultStatus.unsupported,
            workspace_id=job.workspace_id,
            job_type=job.job_type,
            error_code="unsupported_job_type",
            error_message=f"Unsupported bridge job type: {job.job_type.value}",
        )

    @staticmethod
    def _coerce_payload(payload: object, model_type: type[BaseModel]) -> BaseModel | None:
        if isinstance(payload, model_type):
            return payload
        try:
            if isinstance(payload, BaseModel):
                return model_type.model_validate(payload.model_dump())
            return model_type.model_validate(payload)
        except Exception:
            return None

    @staticmethod
    def _invalid_payload_result(job: ProactiveBridgeJob, job_name: str) -> ProactiveBridgeJobResult:
        return ProactiveBridgeJobResult(
            job_id=job.job_id,
            status=ProactiveBridgeResultStatus.failed,
            workspace_id=job.workspace_id,
            job_type=job.job_type,
            error_code="invalid_payload",
            error_message=f"{job_name} job received an invalid payload",
        )


@dataclass
class RemoteBridgeWorker:
    receiver: HttpPollingLocalBridgeReceiver
    executor: LocalRuntimeProactiveBridgeExecutor
    stop_event: asyncio.Event
    poll_interval_seconds: float
    max_items: int

    async def run_forever(self) -> None:
        while not self.stop_event.is_set():
            try:
                jobs = await self.receiver.receive_jobs(limit=self.max_items)
                for job in jobs:
                    result = await self.executor.execute(job)
                    await self.receiver.report_result(result)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Remote proactive bridge poll failed",
                    extra={"event": "runtime.proactive_bridge.poll", "outcome": "error"},
                )
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.poll_interval_seconds)
            except TimeoutError:
                continue
