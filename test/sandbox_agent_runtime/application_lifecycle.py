from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx
from sandbox_agent_runtime.runtime_config.models import ResolvedApplication

logger = logging.getLogger(__name__)


class ApplicationLifecycleManager:
    def __init__(self, *, workspace_dir: str | Path) -> None:
        self._workspace_dir = Path(workspace_dir)
        self._procs: dict[str, asyncio.subprocess.Process] = {}

    async def start_all(self, apps: list[ResolvedApplication]) -> None:
        for app in apps:
            await self._start_app(app)
            await self._wait_healthy(app)

    async def stop_all(self, apps: list[ResolvedApplication]) -> None:
        for app in apps:
            proc = self._procs.pop(app.app_id, None)
            if proc is None:
                continue
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=10)
            except Exception:
                logger.warning("Failed to stop app %s — killing", app.app_id)
                try:
                    proc.kill()
                except Exception:
                    pass

    def get_mcp_url(self, app: ResolvedApplication) -> str:
        return f"http://localhost:{app.mcp.port}{app.mcp.path}"

    async def _start_app(self, app: ResolvedApplication) -> None:
        if not app.start_command:
            raise RuntimeError(f"App '{app.app_id}' has no start_command; cannot launch via subprocess")

        app_dir = self._workspace_dir / "apps" / app.app_id
        proc = await asyncio.create_subprocess_shell(
            app.start_command,
            cwd=str(app_dir),
            env={**os.environ},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._procs[app.app_id] = proc
        logger.info("Started app '%s' (pid=%s)", app.app_id, proc.pid)

    async def _wait_healthy(self, app: ResolvedApplication) -> None:
        hc = app.health_check
        health_url = f"http://localhost:{app.mcp.port}{hc.path}"

        loop = asyncio.get_event_loop()
        deadline = loop.time() + hc.timeout_s

        while loop.time() < deadline:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(health_url, timeout=5)
                if resp.status_code == 200:
                    logger.info("App '%s' is healthy", app.app_id)
                    return
            except Exception as exc:
                logger.debug("Health check for %s not ready: %s", app.app_id, exc)
            await asyncio.sleep(hc.interval_s)

        raise RuntimeError(f"App '{app.app_id}' did not become healthy within {hc.timeout_s}s")
