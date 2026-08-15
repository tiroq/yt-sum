/**
 * Presentation-only library ordering. Keep topic resolution here so a future
 * classifier can add `topics` to a video without changing the sidebar UI.
 */
export const GROUPING_OPTIONS = [
  { id: "none", label: "Без группировки", labelEn: "No grouping" },
  { id: "tag", label: "По тегам", labelEn: "By tags" },
  { id: "topic", label: "По темам", labelEn: "By topics" },
];

const titleCollator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

export function sortVideos(videos, direction = "asc") {
  return [...videos].sort((left, right) => {
    const result = titleCollator.compare(left.title || "", right.title || "");
    if (result !== 0) return direction === "desc" ? -result : result;
    return left.video_id.localeCompare(right.video_id);
  });
}

/** Extension point: API/classifier clients may attach `topics: string[]`. */
export function topicsFor(video) {
  return Array.isArray(video.topics) ? video.topics.filter(Boolean) : [];
}

function groupNames(video, grouping) {
  if (grouping === "tag") return video.tags?.filter(Boolean) ?? [];
  if (grouping === "topic") return topicsFor(video);
  return [];
}

export function groupVideos(videos, grouping = "none", uncategorizedLabel = "Без категории") {
  // The caller owns ordering so grouping composes with either title direction.
  const ordered = [...videos];
  if (grouping === "none") return [{ id: "all", label: "", videos: ordered }];

  const groups = new Map();
  for (const video of ordered) {
    const names = groupNames(video, grouping);
    for (const name of names.length ? names : [uncategorizedLabel]) {
      const key = name.toLocaleLowerCase();
      const group = groups.get(key) ?? { id: key, label: name, videos: [] };
      group.videos.push(video);
      groups.set(key, group);
    }
  }
  return [...groups.values()].sort((left, right) => titleCollator.compare(left.label, right.label));
}
