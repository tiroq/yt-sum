import assert from "node:assert/strict";
import test from "node:test";
import { groupVideos, sortVideos } from "../app/video-library.js";

const videos = [
  { video_id: "2", title: "Яблоко", tags: ["Science"] },
  { video_id: "1", title: "apple 10", tags: ["Work", "Science"], topics: ["AI"] },
  { video_id: "3", title: "Apple 2", tags: [] },
];

test("sortVideos orders titles alphabetically with a stable ID tie-breaker", () => {
  assert.deepEqual(sortVideos(videos).map((video) => video.video_id), ["3", "1", "2"]);
  assert.deepEqual(sortVideos(videos, "desc").map((video) => video.video_id), ["2", "1", "3"]);
});

test("groupVideos keeps a tagged video in every matching tag group", () => {
  const groups = groupVideos(sortVideos(videos), "tag", "Uncategorized");
  assert.deepEqual(groups.map((group) => group.label), ["Science", "Uncategorized", "Work"]);
  assert.deepEqual(groups[0].videos.map((video) => video.video_id), ["1", "2"]);
  assert.deepEqual(groups[1].videos.map((video) => video.video_id), ["3"]);
});

test("groupVideos accepts future classifier topics without a UI change", () => {
  const groups = groupVideos(sortVideos(videos), "topic", "Uncategorized");
  assert.deepEqual(groups.map((group) => group.label), ["AI", "Uncategorized"]);
  assert.deepEqual(groups[0].videos.map((video) => video.video_id), ["1"]);
});

test("sortVideos falls back to the stable video ID when titles are equal", () => {
  const sameTitleVideos = [
    { video_id: "b", title: "same title" },
    { video_id: "a", title: "same title" },
  ];

  assert.deepEqual(sortVideos(sameTitleVideos).map((video) => video.video_id), ["a", "b"]);
});

test("groupVideos falls back to an uncategorized bucket for unknown groupings", () => {
  const groups = groupVideos(
    [
      { video_id: "1", title: "Alpha", tags: ["Work"] },
      { video_id: "2", title: "Beta" },
    ],
    "unknown",
    "Uncategorized",
  );

  assert.deepEqual(groups.map((group) => group.label), ["Uncategorized"]);
  assert.deepEqual(groups[0].videos.map((video) => video.video_id), ["1", "2"]);
});
