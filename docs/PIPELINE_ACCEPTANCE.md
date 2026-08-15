# Pipeline Acceptance Tests

Status: approved on 2026-08-15.

The implementation is accepted when automated tests demonstrate:

1. Two simultaneous yt-dlp operations can never acquire leases.
2. ASR/LLM/TTS can proceed while another workflow owns yt-dlp.
3. Claimed or resource-waiting work is not counted as running.
4. Dependency, terminal, retry, skip, pause, cancel, and recovery transitions follow the state machine.
5. Stop terminates subprocess ownership before releasing its lease.
6. Restart resumes from committed artifacts and does not repeat YouTube access unnecessarily.
7. Endpoint RPM, in-flight capacity, cooldown, and circuit breaker are independent.
8. LLM chunks use all idle compatible endpoints and remain fair across videos.
9. A map result survives a later map/reduce failure.
10. Optional failures produce partial readiness without invalidating required artifacts.
11. Diagnostics aggregates equal complete database state rather than a paginated list.
12. Snapshot/event cursors reject stale updates and recover gaps.
13. Every task row links to its video and individual workflow route.
14. Original captions remain byte-identical while normalized derived text removes rolling overlap.
15. Migration is idempotent and preserves legacy history.

Unit tests use deterministic resource fakes for delays, 429 responses, timeouts, hangs, process termination, and storage failures. Real YouTube/Ollama/Meeting Transcriber checks are optional smoke tests.

