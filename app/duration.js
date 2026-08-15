/**
 * Returns a consistent, human-readable video duration in Russian.
 *
 * Every unit is shown so durations remain unambiguous in compact UI elements.
 */
export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "";

  const totalSeconds = Math.floor(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;

  return `${hours} ч ${String(minutes).padStart(2, "0")} мин ${String(remainingSeconds).padStart(2, "0")} сек`;
}
