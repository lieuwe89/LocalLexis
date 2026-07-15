import { doubleMetaphone } from 'double-metaphone';

/** One search hit inside a transcript: char offsets into that segment's text. */
export interface FindMatch {
  segmentIndex: number;
  start: number;
  end: number;
}

interface Token { text: string; start: number; end: number; code: string }

// Letters and digits, unicode-aware — mirrors the backend's WORD_RE.
const WORD_RE = /[\p{L}\p{N}]+/gu;

function tokenize(text: string): Token[] {
  const out: Token[] = [];
  for (const m of text.matchAll(WORD_RE)) {
    const raw = m[0];
    const lower = raw.toLowerCase();
    out.push({
      text: lower,
      start: m.index,
      end: m.index + raw.length,
      // Unencodable tokens (numbers, symbols) fall back to exact comparison.
      code: doubleMetaphone(raw)[0] || lower,
    });
  }
  return out;
}

/** True when a and b are within one insertion/deletion/substitution. */
function withinOneEdit(a: string, b: string): boolean {
  if (a === b) return true;
  const la = a.length, lb = b.length;
  if (Math.abs(la - lb) > 1) return false;
  if (la === lb) {
    let diff = 0;
    for (let i = 0; i < la; i++) if (a[i] !== b[i] && ++diff > 1) return false;
    return true;
  }
  const [s, l] = la < lb ? [a, b] : [b, a];
  let i = 0, j = 0, skipped = false;
  while (i < s.length && j < l.length) {
    if (s[i] === l[j]) { i++; j++; }
    else if (skipped) return false;
    else { skipped = true; j++; }
  }
  return true;
}

function tokensMatch(q: Token, t: Token): boolean {
  if (q.text === t.text) return true;
  if (q.code === t.code) return true;
  // Typo tolerance only for words long enough that one edit is unambiguous.
  return q.text.length >= 5 && t.text.length >= 5 && withinOneEdit(q.text, t.text);
}

/**
 * Find all matches of `query` across transcript segments.
 *
 * Exact mode: case-insensitive substring, one FindMatch per occurrence.
 * Fuzzy mode: the query's word tokens must match a consecutive run of the
 * segment's word tokens, each pair matching by Double Metaphone code
 * equality or edit distance ≤ 1 (both tokens ≥ 5 chars).
 */
export function findMatches(
  segments: { text: string }[],
  query: string,
  fuzzy: boolean,
): FindMatch[] {
  const q = query.trim();
  if (!q) return [];
  const out: FindMatch[] = [];

  if (!fuzzy) {
    const ql = q.toLowerCase();
    segments.forEach((seg, si) => {
      const lower = seg.text.toLowerCase();
      for (let hit = lower.indexOf(ql); hit !== -1; hit = lower.indexOf(ql, hit + ql.length)) {
        out.push({ segmentIndex: si, start: hit, end: hit + ql.length });
      }
    });
    return out;
  }

  const qTokens = tokenize(q);
  if (!qTokens.length) return [];
  segments.forEach((seg, si) => {
    const tokens = tokenize(seg.text);
    for (let p = 0; p + qTokens.length <= tokens.length; p++) {
      let ok = true;
      for (let j = 0; j < qTokens.length; j++) {
        if (!tokensMatch(qTokens[j], tokens[p + j])) { ok = false; break; }
      }
      if (ok) {
        out.push({
          segmentIndex: si,
          start: tokens[p].start,
          end: tokens[p + qTokens.length - 1].end,
        });
        p += qTokens.length - 1; // no overlapping matches
      }
    }
  });
  return out;
}
