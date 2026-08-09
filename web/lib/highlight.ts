/**
 * Preparing redline HTML for the DOM.
 *
 * The comparison service escapes every clause before marking it up, so the
 * HTML it returns contains nothing but the <del> and <ins> tags it wrote
 * itself. Clause text nonetheless originates in an arbitrary uploaded PDF, so
 * `sanitize` re-checks that on the client before anything is injected: any tag
 * that is not one of the three this interface writes is removed outright,
 * attributes and all. Both gates have to fail for markup to reach the page.
 */

const ALLOWED_TAGS = new Set([
  '<del class="rl-del">',
  "</del>",
  '<ins class="rl-ins">',
  "</ins>",
  '<mark class="hit">',
  "</mark>",
]);

// Matches a complete tag, and an unterminated one at end of input, so a
// truncated "<img src=" cannot survive as a tag opening.
const ANY_TAG = /<[^>]*>?/g;

const MARKUP = /(<[^>]+>|&[a-zA-Z]+;|&#\d+;)/g;

export function sanitize(html: string): string {
  if (!html) return "";
  return html.replace(ANY_TAG, (tag) => (ALLOWED_TAGS.has(tag) ? tag : ""));
}

/** Escape text that is not already markup — clause titles arrive raw. */
export function escapeText(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Wrap search hits in <mark>, without matching inside a tag or an entity.
 *
 * Splitting on both and rewriting only the text between them is exact here
 * because the input is already reduced to a known three-tag vocabulary.
 */
export function highlight(html: string, term: string): string {
  const safe = sanitize(html);
  const needle = term.trim();
  if (needle.length < 2 || !safe) return safe;

  const matcher = new RegExp(escapeRegExp(needle), "gi");

  return safe
    .split(MARKUP)
    .map((part) =>
      part.startsWith("<") || part.startsWith("&")
        ? part
        : part.replace(matcher, (found) => `<mark class="hit">${found}</mark>`),
    )
    .join("");
}

/** True when any of these texts mentions the term. */
export function matches(
  haystacks: (string | null | undefined)[],
  term: string,
): boolean {
  const needle = term.trim().toLowerCase();
  if (needle.length < 2) return true;
  return haystacks.some((text) => text?.toLowerCase().includes(needle));
}
