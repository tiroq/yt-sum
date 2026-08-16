#!/usr/bin/env bash
# Format the API health response in human-readable format with colors

# Use actual ANSI escape codes via $'...' syntax
GREEN=$'\033[0;32m'
RED=$'\033[0;31m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
NC=$'\033[0m'

# Pass colors to jq as separate strings to avoid escaping issues
jq -r --arg GREEN "$GREEN" --arg RED "$RED" --arg YELLOW "$YELLOW" --arg BLUE "$BLUE" --arg NC "$NC" '
  def green: $GREEN + . + $NC;
  def red: $RED + . + $NC;
  def yellow: $YELLOW + . + $NC;
  def blue: $BLUE + . + $NC;
  
  "\n" + ("=== YT Sum Status ===" | blue) + "\n" +
  "Status: " + (.status | green) + "\n" +
  "Queue Paused: " + (if .queue_paused then "true" | red else "false" | green end) + "\n" +
  "Library: \(.library)\n\n" +
  ("--- Queues ---" | blue) + "\n" +
  "Download: \(.queues.download.total) total | \(.queues.download.processing) processing | \(.queues.download.queued) queued | \(.queues.download.blocked) blocked | " + (if .queues.download.failed > 0 then (.queues.download.failed | tostring | red) else (.queues.download.failed | tostring | green) end) + " failed\n" +
  "LLM:      \(.queues.llm.total) total | \(.queues.llm.processing) processing | \(.queues.llm.queued) queued | \(.queues.llm.blocked) blocked | " + (if .queues.llm.failed > 0 then (.queues.llm.failed | tostring | red) else (.queues.llm.failed | tostring | green) end) + " failed\n" +
  "TTS:      \(.queues.tts.total) total | \(.queues.tts.processing) processing | \(.queues.tts.queued) queued | \(.queues.tts.blocked) blocked | " + (if .queues.tts.failed > 0 then (.queues.tts.failed | tostring | red) else (.queues.tts.failed | tostring | green) end) + " failed\n\n" +
  ("--- Components ---" | blue) + "\n" +
  "yt-dlp: \(.components.yt_dlp.version)\n" +
  "ffmpeg: " + (if .components.ffmpeg.ready then "ready" | green else "missing" | red end) + "\n" +
  "ASR Engine: \(.components.native_transcriber.engine) (" + (if .components.native_transcriber.ready then "ready" | green else "not ready" | red end) + ")\n" +
  "TTS Engine: \(.components.text_to_speech.engine) (" + (if .components.text_to_speech.ready then "ready" | green else "not ready" | red end) + ")\n" +
  "Cookies: " + (if .components.cookies.ready then "ready" | green else "not ready" | red end) + "\n\n" +
  ("--- Resources (\(.resources | length)) ---" | blue) + "\n" +
  (.resources | map("  \(.label): \(.in_use)/\(.capacity) in use | health: " + (if .health == "healthy" then .health | green elif .health == "degraded" then .health | yellow else .health | red end)) | join("\n")) +
  "\n"
'

