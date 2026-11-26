import { describe, it, expect } from 'vitest';
import { actionsFor } from '../../services/pidReviewService';

describe('digitisation review actions', () => {
  it('offers the right fix for each kind of item', () => {
    expect(actionsFor({ kind: 'tag' })).toEqual(['confirm', 'rename', 'reject']);
    expect(actionsFor({ kind: 'link' })).toEqual(['confirm', 'reject']);
    expect(actionsFor({ kind: 'missing' })).toEqual(['add_link', 'confirm']);
  });
});
