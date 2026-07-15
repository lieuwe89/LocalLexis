import { describe, it, expect } from 'vitest';
import { findMatches } from './fuzzyMatch';

const segs = (...texts: string[]) => texts.map(text => ({ text }));

describe('findMatches exact mode', () => {
  it('finds every occurrence with char ranges', () => {
    const m = findMatches(segs('the cat sat on the cat mat'), 'cat', false);
    expect(m).toEqual([
      { segmentIndex: 0, start: 4, end: 7 },
      { segmentIndex: 0, start: 19, end: 22 },
    ]);
  });

  it('is case-insensitive and spans segments', () => {
    const m = findMatches(segs('Budget review', 'no match', 'BUDGET!'), 'budget', false);
    expect(m.map(x => x.segmentIndex)).toEqual([0, 2]);
  });

  it('returns [] for empty query', () => {
    expect(findMatches(segs('anything'), '  ', false)).toEqual([]);
  });
});

describe('findMatches fuzzy mode', () => {
  it('matches phonetically equivalent words', () => {
    const m = findMatches(segs('then Kaitlyn presented'), 'Catelin', true);
    expect(m).toHaveLength(1);
    const seg = 'then Kaitlyn presented';
    expect(seg.slice(m[0].start, m[0].end)).toBe('Kaitlyn');
  });

  it('matches single-letter typos in words of 5+ chars', () => {
    const m = findMatches(segs('quarterly budgett review'), 'budget', true);
    expect(m).toHaveLength(1);
  });

  it('does not typo-match short words with different codes', () => {
    // 'car' vs 'cat': 3 chars (below the 5-char typo threshold) and
    // different metaphone codes (KR vs KT) → no match
    expect(findMatches(segs('nice car'), 'cat', true)).toEqual([]);
  });

  it('matches multi-word queries as consecutive token sequences', () => {
    const m = findMatches(segs('the anual budgett was fine'), 'annual budget', true);
    expect(m).toHaveLength(1);
    const seg = 'the anual budgett was fine';
    expect(seg.slice(m[0].start, m[0].end)).toBe('anual budgett');
  });

  it('unencodable tokens (numbers) compare exactly', () => {
    expect(findMatches(segs('room 2024 booked'), '2024', true)).toHaveLength(1);
    expect(findMatches(segs('room 2025 booked'), '2024', true)).toEqual([]);
  });
});
