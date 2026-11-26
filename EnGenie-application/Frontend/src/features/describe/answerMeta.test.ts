import { describe, it, expect } from 'vitest';
import { answerMeta, MODE_LABELS } from './answerMeta';

describe('grounded answers in the describe chat', () => {
  it('turns cited tags into canvas-focus chips and keeps the mode', () => {
    const meta = answerMeta({ status: 'success', mode: 'question', citations: ['LIC-101', 'V-101'],
                              sources: ['node:V-101'] });
    expect(meta.mode).toBe('question');
    expect(meta.results).toEqual([{ tag: 'LIC-101', title: 'LIC-101', detail: '' },
                                  { tag: 'V-101', title: 'V-101', detail: '' }]);
    expect(meta.sources).toEqual(['node:V-101']);
  });

  it('adds nothing for a change with no citations', () => {
    expect(answerMeta({ status: 'success', mode: 'build', citations: [] })).toEqual(
      { mode: 'build', results: undefined, sources: undefined });
    expect(MODE_LABELS.mixed).toBe('Build + Answer');
  });
});
