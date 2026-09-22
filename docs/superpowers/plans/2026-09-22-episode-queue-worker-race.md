# Per-Group Episode Queue Worker Race Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure exactly one background worker processes queued episodes for each group while allowing distinct groups to progress concurrently.

**Architecture:** Replace the per-group Boolean with the actual worker task, assigning each task to the map synchronously when it is created. Route both episode tools through one enqueue helper, and have the worker remove only its own task on exit; if cancellation leaves queued work behind, start a replacement worker after the exiting task has finished its work.

**Tech Stack:** Python 3.10+, asyncio, pytest, MCP server and Graphiti Core 0.29.x.

**Spec:** llm/episode-queue-worker-race-report.md (source report at revision ab45ac0).

## Global Constraints

- Preserve the expected invariant: “one worker and one active episode processor for a single group.”
- Preserve the expected invariant: “Different groups should remain able to process concurrently.”
- The repository supports Python 3.10+.
- Keep the runtime dependency range at graphiti-core>=0.29.0,<0.30.0.
- Queue regression tests must not connect to Neo4j or require an LLM or embeddings provider.

## Review Focus

- Concurrent add_memory and add_conversation_memory calls for the same group must share one worker and execute one episode processor at a time; pin this in test_concurrent_add_memory_and_conversation_share_one_group_worker.
- Calls for distinct groups must still overlap; pin this in test_different_groups_process_concurrently.
- Cancelling an idle worker must clear its task-map entry, and a later enqueue must create a different worker; pin this in test_cancelled_idle_worker_is_removed_and_replaced_on_enqueue.
- If a worker is cancelled while another job is waiting, the pending job must run after cancellation cleanup; pin this in test_cancelled_worker_restarts_when_queue_has_pending_work.
- If one job raises, queue accounting must complete and the next job must run; pin this in test_failed_job_marks_done_and_worker_processes_next_job.

## Scope Note

This PR addresses the duplicate per-group queue worker race. The report also describes Graphiti 0.29.3 mutating a shared client driver when different group IDs are used, and a separate delete_episode/get_episodes inconsistency. The fake-client queue tests below do not establish cross-group safety of the real Graphiti client and do not claim to fix the deletion anomaly. Keep the requested queue fix scoped to the report's worker recommendation, and identify the shared-client behavior as a separate follow-up if it remains reproducible.

## File Structure

- Modify mcp-server/megamem_mcp_server.py: own the task map, shared enqueue path, worker startup, and identity-safe worker cleanup.
- Create tests/test_episode_queue.py: exercise both public enqueue paths and the queue lifecycle with a fake Graphiti client and async callbacks.
- Create pytest.ini: register the unit marker consumed by the existing npm run test:py script.
- Create docs/superpowers/plans/2026-09-22-episode-queue-worker-race.md: preserve this reviewed implementation plan.

---

### Task 1: Serialize episode processing per group

**Files:**
- Modify: mcp-server/megamem_mcp_server.py
- Create: tests/test_episode_queue.py
- Create: pytest.ini
- Create: docs/superpowers/plans/2026-09-22-episode-queue-worker-race.md

**Interfaces:**
- Consumes: ObsidianMegaMemMCPServer, its process_episode_queue(group_id: str) coroutine, and the existing add_memory and add_conversation_memory handler branches.
- Produces: ObsidianMegaMemMCPServer._enqueue_episode(group_id: str, process_func: Callable[[], Awaitable[None]]) -> int; ObsidianMegaMemMCPServer._ensure_episode_queue_worker(group_id: str) -> asyncio.Task[None]; queue_workers: Dict[str, asyncio.Task[None]].

- [ ] **Step 1: Create the fork contribution branch from current upstream main**

Run:

~~~bash
git fetch origin
git switch -c codex/fix-episode-queue-worker-race origin/main
~~~

Expected: the task branch starts at origin/main and contains the uncommitted plan file. The local main branch remains unchanged.

- [ ] **Step 2: Add the focused pytest configuration and regression tests**

Create pytest.ini:

~~~ini
[pytest]
testpaths = tests
markers =
    unit: tests that require no external services
~~~

Create tests/test_episode_queue.py. Import asyncio, json, sys, Path, SimpleNamespace, AsyncMock, pytest; add the repository's mcp-server directory to sys.path before importing ObsidianMegaMemMCPServer. Use pytest.mark.unit on each test. Define this fake Graphiti client:

~~~python
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
~~~

Implement test_concurrent_add_memory_and_conversation_share_one_group_worker with this scenario: create ObsidianMegaMemMCPServer inside asyncio.run; set initialization_complete to True and bridge_config to SimpleNamespace(default_namespace="default"); set megamem_client to RecordingGraphitiClient and replace _get_graphiti_client with AsyncMock(return_value=client). Write a temporary JSON config containing {"useCustomOntology": false} and set OBSIDIAN_CONFIG_PATH to it. Call _handle_graphiti_tool concurrently for add_memory with name "fact", content "alpha", group_id "shared", and for add_conversation_memory with a one-message user conversation containing "beta" and group_id "shared". Await server.episode_queues["shared"].join(), assert both responses report success, and assert client.max_active == 1. Cancel the remaining idle worker and await it before asyncio.run returns.

Implement four additional tests using a normally initialized server and the produced _enqueue_episode interface:

- test_different_groups_process_concurrently: enqueue one callback in group-a and one in group-b; have each callback add its group to a set, signal an asyncio.Event when both groups have started, and await that event with asyncio.wait_for(..., timeout=1). Await both queue.join() calls and assert the peak active callback count was 2.
- test_cancelled_idle_worker_is_removed_and_replaced_on_enqueue: enqueue and finish a no-op; cancel and await the idle worker; assert its group_id is absent from queue_workers; enqueue a callback that appends to a list; assert its task is not the cancelled task, await queue.join(), and assert the list contains one item.
- test_cancelled_worker_restarts_when_queue_has_pending_work: enqueue a callback that sets a started event and waits indefinitely; wait for started, enqueue a second callback that records completion, cancel and await the worker, then await queue.join() and assert the pending callback ran once.
- test_failed_job_marks_done_and_worker_processes_next_job: enqueue a callback that raises ValueError("expected test failure") followed by a callback that records completion; await queue.join() and assert the second callback ran once.

- [ ] **Step 3: Run the new tests before changing production code**

Run: python -m pytest tests/test_episode_queue.py -q
Expected: FAIL because the server does not yet expose the shared enqueue and worker-task interfaces, and the current duplicate-worker startup permits the fake Graphiti calls for the same group to overlap. No test should attempt a database, LLM, or embeddings connection.

- [ ] **Step 4: Implement task-based worker registration and a common enqueue path**

Add Awaitable and Callable to the typing imports. In ObsidianMegaMemMCPServer.__init__, replace Dict[str, bool] with Dict[str, asyncio.Task[None]] for queue_workers. Add these methods:

~~~python
def _ensure_episode_queue_worker(self, group_id: str) -> asyncio.Task[None]:
    worker = self.queue_workers.get(group_id)
    if worker is None or worker.done():
        worker = asyncio.create_task(self.process_episode_queue(group_id))
        self.queue_workers[group_id] = worker
    return worker

async def _enqueue_episode(
    self,
    group_id: str,
    process_func: Callable[[], Awaitable[None]],
) -> int:
    queue = self.episode_queues.setdefault(group_id, asyncio.Queue())
    position = queue.qsize() + 1
    await queue.put(process_func)
    self._ensure_episode_queue_worker(group_id)
    return position
~~~

Keep process_episode_queue's existing loop, exception logging, and task_done behavior. In its finally block, get asyncio.current_task(); only if queue_workers.get(group_id) is that task, remove the map entry. If the corresponding queue is non-empty, call _ensure_episode_queue_worker(group_id) after removing the old entry so work queued during cancellation is not stranded. Do not await between removing the old task and scheduling the replacement.

In both add_memory and add_conversation_memory, replace the duplicated queue creation, put, Boolean check, and create_task blocks with a call to await self._enqueue_episode(group_id, process_episode), using group_id_str in the first branch and group_id in the second. Keep the existing response text and position value unchanged.

- [ ] **Step 5: Run the targeted regression suite**

Run: python -m pytest tests/test_episode_queue.py -q
Expected: PASS for all five tests. Same-group fake client calls must have max_active == 1; different-group callbacks must reach a peak of 2; cancellation and exceptions must not leave unfinished queue items.

- [ ] **Step 6: Run the repository's unit test command**

Run: npm run test:py
Expected: PASS. This invokes pytest -m unit -v and discovers the new tests through pytest.ini. It must not require Neo4j, an LLM, or an embeddings service.

- [ ] **Step 7: Review the final diff and commit only this fix**

Run git diff --check, inspect git diff, and confirm the only changed files are mcp-server/megamem_mcp_server.py, tests/test_episode_queue.py, pytest.ini, and this plan. Commit with:

~~~bash
git add mcp-server/megamem_mcp_server.py tests/test_episode_queue.py pytest.ini docs/superpowers/plans/2026-09-22-episode-queue-worker-race.md
git commit -m "fix: prevent duplicate episode queue workers"
~~~

- [ ] **Step 8: Push the branch on the user's fork and open the upstream PR**

Start from the fetched origin/main revision on branch codex/fix-episode-queue-worker-race. Verify the active GitHub account with gh auth status --hostname github.com. Push the branch to fork:

~~~bash
git push -u fork codex/fix-episode-queue-worker-race
~~~

Create the PR in C-Bjorn/MegaMem with base main and head EthanJStark:codex/fix-episode-queue-worker-race. Use title "fix: prevent duplicate episode queue workers" and this body:

~~~text
## Summary
- Track each per-group episode worker task before another handler can start a duplicate.
- Route add_memory and add_conversation_memory through the same enqueue path.
- Cover same-group serialization, different-group concurrency, cancellation, and failed jobs without external services.

## Validation
- python -m pytest tests/test_episode_queue.py -q
- npm run test:py

## Scope
This fixes the queue worker startup race. It does not investigate the separately reported Graphiti shared-client driver mutation or delete_episode/get_episodes inconsistency.
~~~

Write the exact body to /tmp/episode-queue-worker-race-pr-body.md and pass it with gh pr create --repo C-Bjorn/MegaMem --base main --head EthanJStark:codex/fix-episode-queue-worker-race --title "fix: prevent duplicate episode queue workers" --body-file /tmp/episode-queue-worker-race-pr-body.md. Attach the resulting pull request to the current Codex task.

---

## Self-Review

- Spec coverage: both enqueue handlers, same-group serialization, different-group concurrency, worker cancellation, pending work during cancellation, exception handling, task_done accounting, unit validation, and the requested fork-to-upstream PR route are assigned to Task 1.
- Placeholder scan: every test name, helper signature, test command, commit message, branch name, PR target, and PR body is specified.
- Type consistency: queue_workers stores asyncio.Task[None]; _ensure_episode_queue_worker returns that type; _enqueue_episode accepts Callable[[], Awaitable[None]] and returns the queue position as int.
- Review focus coverage: each listed failure mode has a named regression test in Task 1.
