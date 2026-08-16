import asyncio
from pathlib import Path

from ytsum.pipeline import ResourceCoordinator
from ytsum.queue import ProcessingQueue
from ytsum.storage import LibraryStorage


async def test_yt_dlp_resource_is_globally_serialized_and_wait_is_truthful(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    first = storage.enqueue("first-video", "https://youtu.be/first-video")
    second = storage.enqueue("second-video", "https://youtu.be/second-video")
    resources = ResourceCoordinator(lambda: storage)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()

    async def run_first() -> None:
        async with resources.stage(first, "metadata", "yt_dlp", progress=0.1, message="First metadata"):
            first_started.set()
            await release_first.wait()

    async def run_second() -> None:
        async with resources.stage(second, "metadata", "yt_dlp", progress=0.1, message="Second metadata"):
            second_started.set()

    first_task = asyncio.create_task(run_first())
    await first_started.wait()
    second_task = asyncio.create_task(run_second())
    await asyncio.sleep(0)

    snapshot = next(item for item in resources.snapshots() if item.id == "yt_dlp")
    assert snapshot.capacity == 1
    assert snapshot.in_use == 1
    assert snapshot.waiting == 1
    assert storage.get_stage_task(first.workflow_id, "metadata").state == "running"
    assert storage.get_stage_task(second.workflow_id, "metadata").state == "waiting_resource"
    assert not second_started.is_set()

    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert storage.get_stage_task(first.workflow_id, "metadata").state == "succeeded"
    assert storage.get_stage_task(second.workflow_id, "metadata").state == "succeeded"
    assert storage.list_attempts(first.workflow_id)[0]["state"] == "succeeded"
    assert storage.list_attempts(second.workflow_id)[0]["state"] == "succeeded"


async def test_resource_coordinator_emits_wait_and_release_debug_events() -> None:
    storage = LibraryStorage(Path("/tmp/yt-sum-resource-debug"))
    job = storage.enqueue("wait-debug-video", "https://youtu.be/wait-debug-video")
    resources = ResourceCoordinator(lambda: storage)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with resources.stage(job, "metadata", "yt_dlp", progress=0.1, message="hold"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await entered.wait()
    snapshot = next(item for item in resources.snapshots() if item.id == "yt_dlp")
    assert snapshot.in_use == 1
    assert snapshot.waiting == 0

    release.set()
    await task
    assert storage.get_stage_task(job.workflow_id, "metadata").state == "succeeded"


async def test_pause_blocks_the_next_atomic_operation_until_resume() -> None:
    queue = ProcessingQueue(None, lambda: None)  # type: ignore[arg-type]
    queue.pause()
    checkpoint = asyncio.create_task(queue._wait_until_resumed())
    await asyncio.sleep(0)
    assert not checkpoint.done()
    queue.resume()
    await asyncio.wait_for(checkpoint, timeout=1)


def test_pipeline_aggregates_separate_live_state_from_history(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    running = storage.enqueue("running-id", "https://youtu.be/running-id")
    waiting = storage.enqueue("waiting-id", "https://youtu.be/waiting-id")
    finished = storage.enqueue("finished-id", "https://youtu.be/finished-id")

    storage.transition_stage(running.id, "metadata", "running", resource_id="yt_dlp")
    storage.transition_stage(
        waiting.id,
        "metadata",
        "waiting_resource",
        resource_id="yt_dlp",
        waiting_for={"resource_id": "yt_dlp", "reason": "Resource is busy"},
    )
    storage.transition_stage(finished.id, "metadata", "succeeded", resource_id="yt_dlp")

    metadata = next(item for item in storage.pipeline_aggregates() if item["id"] == "metadata")
    assert metadata["count"] == 2
    assert metadata["running"] == 1
    assert metadata["waiting"] == 1
    assert metadata["succeeded"] == 1


def test_workflow_snapshot_and_monotonic_events_survive_reopen(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    job = storage.enqueue(
        "Gn64NNr3bqU",
        "https://youtu.be/Gn64NNr3bqU",
        settings_snapshot={"primary_language": "ru", "secondary_language": "en"},
    )
    storage.transition_stage(job.id, "metadata", "waiting_resource", resource_id="yt_dlp")
    storage.transition_stage(job.id, "metadata", "running", resource_id="yt_dlp")
    storage.transition_stage(job.id, "metadata", "succeeded", resource_id="yt_dlp")

    reopened = LibraryStorage(tmp_path)
    workflow = reopened.get_workflow(job.workflow_id)
    events = reopened.list_pipeline_events(workflow_id=job.workflow_id)

    assert workflow is not None
    assert workflow.settings_snapshot["primary_language"] == "ru"
    assert [item.sequence for item in events] == sorted(item.sequence for item in events)
    assert events[-1].to_state == "succeeded"


def test_finishing_workflow_closes_all_non_terminal_stage_tasks(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    job = storage.enqueue("cancel-id", "https://youtu.be/cancel-id")
    storage.transition_stage(job.id, "summarizing", "queued", progress=0.7)
    storage.transition_stage(job.id, "summary-plan", "queued", progress=0.7)

    storage.update_job(job.id, status="cancelled", execution_state="cancelled")
    storage.finish_workflow(job.id, "cancelled")

    tasks = storage.list_stage_tasks(workflow_id=job.workflow_id)
    assert {task.stage: task.state for task in tasks}["summarizing"] == "cancelled"
    assert {task.stage: task.state for task in tasks}["summary-plan"] == "cancelled"
    assert not [task for task in storage.list_stage_tasks(live_only=True) if task.workflow_id == job.workflow_id]


def test_reopen_reconciles_orphaned_active_stages_of_terminal_workflow(tmp_path: Path) -> None:
    storage = LibraryStorage(tmp_path)
    job = storage.enqueue("legacy-id", "https://youtu.be/legacy-id")
    storage.transition_stage(job.id, "summary-map", "queued", progress=0.4)
    with storage._connect() as connection:
        connection.execute(
            "UPDATE workflows SET status='requires_attention' WHERE id=?",
            (job.workflow_id,),
        )

    reopened = LibraryStorage(tmp_path)
    task = reopened.get_stage_task(job.workflow_id, "summary-map")

    assert task is not None
    assert task.state == "skipped"
    assert reopened.list_pipeline_events(workflow_id=job.workflow_id)[-1].event == "reconciled"
