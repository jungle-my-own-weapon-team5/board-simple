export type MarkdownHeading = {
  id: string;
  level: number;
  text: string;
};

const markdownHeadingDomIdPrefix = "user-content-";

function toMarkdownHeadingDomId(id: string) {
  return `${markdownHeadingDomIdPrefix}${id}`;
}

function createHeadingSlug(value: string) {
  const slug = value
    .trim()
    .toLowerCase()
    .normalize("NFKC")
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");

  return slug || "section";
}

export function createHeadingIdGenerator() {
  const seen = new Map<string, number>();

  return (value: string) => {
    const slug = createHeadingSlug(value);
    const count = seen.get(slug) ?? 0;

    seen.set(slug, count + 1);

    return count === 0 ? slug : `${slug}-${count + 1}`;
  };
}

export function normalizeMarkdownHeadingText(value: string) {
  return value
    .replace(/\+\+([^+\n]+?)\+\+/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/<[^>]*>/g, "")
    .replace(/\\([\\`*{}\[\]()#+\-.!_>])/g, "$1")
    .replace(/[`*_~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function extractMarkdownHeadings(content: string): MarkdownHeading[] {
  const createHeadingId = createHeadingIdGenerator();
  const headings: MarkdownHeading[] = [];
  let isInsideFence = false;

  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();

    if (/^(`{3,}|~{3,})/.test(trimmed)) {
      isInsideFence = !isInsideFence;
      continue;
    }

    if (isInsideFence) {
      continue;
    }

    const match = line.match(/^(#{1,3})\s+(.+?)\s*$/);

    if (!match) {
      continue;
    }

    const text = normalizeMarkdownHeadingText(match[2].replace(/\s+#+\s*$/, ""));

    if (!text) {
      continue;
    }

    headings.push({
      id: toMarkdownHeadingDomId(createHeadingId(text)),
      level: match[1].length,
      text,
    });
  }

  return headings;
}
