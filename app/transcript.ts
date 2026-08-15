export type TranscriptSegment = {
  timestamp: string;
  href: string | null;
  speaker: string | null;
  text: string;
};

const FRONTMATTER = /^---\n[\s\S]*?\n---\n/;
const SEGMENT = /^\[([^\]]+)\]\(([^)]+)\)\s*(.*)$/;
const SPEAKER = /^\*\*([^*]+):\*\*\s*(.*)$/;

export function parseTranscriptMarkdown(markdown: string): TranscriptSegment[] {
  const segments: TranscriptSegment[] = [];

  for (const line of markdown.replace(FRONTMATTER, "").split("\n")) {
    if (!line.trim() || line.startsWith("#")) continue;
    const match = line.match(SEGMENT);
    if (!match) {
      if (segments.length) segments[segments.length - 1].text += ` ${line.trim()}`;
      continue;
    }
    const [, timestamp, href, content] = match;
    const speakerMatch = content.match(SPEAKER);
    segments.push({
      timestamp,
      href,
      speaker: speakerMatch?.[1] ?? null,
      text: speakerMatch?.[2] ?? content,
    });
  }

  return segments;
}

export function transcriptText(segments: TranscriptSegment[]): string {
  return segments.map(({ speaker, text }) => `${speaker ? `${speaker}: ` : ""}${text}`).join("\n");
}
