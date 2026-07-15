import { describe, it, expect, beforeEach } from 'vitest';
import { usePendingFind } from './pendingFind';

describe('usePendingFind', () => {
  beforeEach(() => usePendingFind.setState({ pending: null }));

  it('consume returns and clears a matching pending find', () => {
    usePendingFind.getState().set({ tid: 't1', query: 'budget', fuzzy: true, segmentIndex: 4 });
    const p = usePendingFind.getState().consume('t1');
    expect(p).toEqual({ tid: 't1', query: 'budget', fuzzy: true, segmentIndex: 4 });
    expect(usePendingFind.getState().consume('t1')).toBeNull();
  });

  it('consume for a different tid returns null and keeps the pending find', () => {
    usePendingFind.getState().set({ tid: 't1', query: 'q', fuzzy: false, segmentIndex: 0 });
    expect(usePendingFind.getState().consume('t2')).toBeNull();
    expect(usePendingFind.getState().pending?.tid).toBe('t1');
  });
});
