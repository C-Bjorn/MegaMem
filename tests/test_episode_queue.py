import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server"))
from megamem_mcp_server import ObsidianMegaMemMCPServer


class RecordingGraphitiClient:
    def __init__(self):
        self.active = 0
        self.max_active = 0

    async def add_episode(self, **kwargs):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
        finally:
            self.active -= 1


@pytest.mark.unit
def test_concurrent_add_memory_and_conversation_share_one_group_worker(tmp_path, monkeypatch):
    async def scenario():
        server = ObsidianMegaMemMCPServer()
        server.initialization_complete = True
        server.bridge_config = SimpleNamespace(default_namespace="default")
        client = RecordingGraphitiClient()
        server.megamem_client = client
        server._get_graphiti_client = AsyncMock(return_value=client)
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"useCustomOntology": False}))
        monkeypatch.setenv("OBSIDIAN_CONFIG_PATH", str(config_path))

        responses = await asyncio.gather(
            server._handle_graphiti_tool(
                "add_memory", {"name": "fact", "content": "alpha", "group_id": "shared"}
            ),
            server._handle_graphiti_tool(
                "add_conversation_memory",
                {
                    "conversation": [{"role": "user", "content": "beta"}],
                    "group_id": "shared",
                },
            ),
        )
        await server.episode_queues["shared"].join()

        assert all(json.loads(response[0].text)["success"] for response in responses)
        assert client.max_active == 1

        worker = server.queue_workers["shared"]
        worker.cancel()
        await worker

    asyncio.run(scenario())


@pytest.mark.unit
def test_different_groups_process_concurrently():
    async def scenario():
        server = ObsidianMegaMemMCPServer()
        started_groups = set()
        both_started = asyncio.Event()
        active = 0
        max_active = 0

        def callback(group):
            async def process():
                nonlocal active, max_active
                active += 1
                max_active = max(max_active, active)
                started_groups.add(group)
                if len(started_groups) == 2:
                    both_started.set()
                try:
                    await asyncio.wait_for(both_started.wait(), timeout=1)
                finally:
                    active -= 1

            return process

        await server._enqueue_episode("group-a", callback("group-a"))
        await server._enqueue_episode("group-b", callback("group-b"))
        await asyncio.gather(
            server.episode_queues["group-a"].join(),
            server.episode_queues["group-b"].join(),
        )
        assert max_active == 2

        workers = list(server.queue_workers.values())
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers)

    asyncio.run(scenario())


@pytest.mark.unit
def test_cancelled_idle_worker_is_removed_and_replaced_on_enqueue():
    async def scenario():
        server = ObsidianMegaMemMCPServer()
        await server._enqueue_episode("group", lambda: asyncio.sleep(0))
        await server.episode_queues["group"].join()
        cancelled_worker = server.queue_workers["group"]
        cancelled_worker.cancel()
        await cancelled_worker

        assert "group" not in server.queue_workers

        completed = []

        async def record_completion():
            completed.append(True)

        await server._enqueue_episode("group", record_completion)
        replacement_worker = server.queue_workers["group"]
        assert replacement_worker is not cancelled_worker
        await server.episode_queues["group"].join()
        assert completed == [True]

        replacement_worker.cancel()
        await replacement_worker

    asyncio.run(scenario())


@pytest.mark.unit
def test_cancelled_worker_restarts_when_queue_has_pending_work():
    async def scenario():
        server = ObsidianMegaMemMCPServer()
        started = asyncio.Event()
        completed = []

        async def wait_until_cancelled():
            started.set()
            await asyncio.Event().wait()

        async def record_completion():
            completed.append(True)

        await server._enqueue_episode("group", wait_until_cancelled)
        await asyncio.wait_for(started.wait(), timeout=1)
        await server._enqueue_episode("group", record_completion)
        worker = server.queue_workers["group"]
        worker.cancel()
        await worker

        await asyncio.wait_for(server.episode_queues["group"].join(), timeout=1)
        assert completed == [True]

        replacement_worker = server.queue_workers["group"]
        replacement_worker.cancel()
        await replacement_worker

    asyncio.run(scenario())


@pytest.mark.unit
def test_failed_job_marks_done_and_worker_processes_next_job():
    async def scenario():
        server = ObsidianMegaMemMCPServer()
        completed = []

        async def fail():
            raise ValueError("expected test failure")

        async def record_completion():
            completed.append(True)

        await server._enqueue_episode("group", fail)
        await server._enqueue_episode("group", record_completion)
        await asyncio.wait_for(server.episode_queues["group"].join(), timeout=1)
        assert completed == [True]

        worker = server.queue_workers["group"]
        worker.cancel()
        await worker

    asyncio.run(scenario())
