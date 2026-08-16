#!/usr/bin/env bash
# Format the API health response in human-readable format

jq -r '
  "\n=== YT Sum Status ===\n" +
  "Status: \(.status)\n" +
  "Queue Paused: \(.queue_paused)\n" +
  "Library: \(.library)\n\n" +
  "--- Queues ---\n" +
  "Download: \(.queues.download.total) total | \(.queues.download.processing) processing | \(.queues.download.queued) queued | \(.queues.download.blocked) blocked | \(.queues.download.failed) failed\n" +
  "LLM:      \(.queues.llm.total) total | \(.queues.llm.processing) processing | \(.queues.llm.queued) queued | \(.queues.llm.blocked) blocked | \(.queues.llm.failed) failed\n" +
  "TTS:      \(.queues.tts.total) total | \(.queues.tts.processing) processing | \(.queues.tts.queued) queued | \(.queues.tts.blocked) blocked | \(.queues.tts.failed) failed\n\n" +
  "--- Components ---\n" +
  "yt-dlp: \(.components.yt_dlp.version)\n" +
  "ffmpeg: \(if .components.ffmpeg.ready then "ready" else "missing" end)\n" +
  "ASR Engine: \(.components.native_transcriber.engine) (\(if .components.native_transcriber.ready then "ready" else "not ready" end))\n" +
  "TTS Engine: \(.components.text_to_speech.engine) (\(if .components.text_to_speech.ready then "ready" else "not ready" end))\n" +
  "Cookies: \(if .components.cookies.ready then "ready" else "not ready" end)\n\n" +
  "--- Resources (\(.resources | length)) ---\n" +
  (.resources | map("  \(.label): \(.in_use)/\(.capacity) in use | health: \(.health)") | join("\n")) +
  "\n"
'

