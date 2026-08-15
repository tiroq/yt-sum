# Diagnostics Contract

Status: approved on 2026-08-15.

Diagnostics is an operational control center. It has four linked sections:

1. System health and actionable warnings.
2. Resource capacity and queues.
3. A branched data-dependency DAG.
4. Live tasks/events with access to history and performance views.

The DAG never appends ready, failed, or cancelled as processing stages. Those are outcomes shown in counters and task rows. Optional branches are collapsible. Selecting a stage filters real stage tasks; selecting a resource highlights stages that require it. Selecting a task opens its workflow and video.

## Node counters

The primary node count is `blocked + queued + waiting_resource + running`. A node additionally shows running, waiting, queued, blocked, and failed counts, throughput for the selected period, median duration, and required resource.

Historical succeeded/cancelled records never appear as current load. Old failures do not make the live graph look active.

## Resource cards

Each card exposes health, used/total slots, RPM consumption, queue depth, current owners, last success, last error, and cooldown. The yt-dlp card must visibly report capacity `1`.

## Transport

The API provides a complete snapshot with a monotonic cursor and Server-Sent Events carrying later sequence numbers. Clients discard stale responses. On a gap or reconnect, the client obtains another snapshot. Polling is a compatibility fallback only.

## UX requirements

- Wide screens use a zoomable/pannable DAG; narrow screens use a vertical branch list.
- Color is supplemented by text and iconography.
- User-facing labels are localized; technical IDs are in expanded diagnostics.
- Task details show dependencies, attempts, wait reason, resource, progress, events, artifacts, and valid controls.
- The application-update widget is a normal system-health card and never overlays content.

