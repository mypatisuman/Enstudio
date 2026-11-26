import { describe, it, expect } from 'vitest';
import { DIGITISE_STAGES, stagesAt } from './PIDIngestPage';

describe('upload page follows the digitiser', () => {
  it('lists the backend passes in order', () => {
    expect(DIGITISE_STAGES.map(s => s.id)).toEqual(
      ['upload', 'read', 'verify', 'symbols', 'connect', 'headers', 'store']);
  });

  it('marks earlier passes done and the reported one running', () => {
    const s = stagesAt('symbols', 'running');
    expect(s.map(x => x.status)).toEqual(['done', 'done', 'done', 'running', 'idle', 'idle', 'idle']);
  });

  it('shows where a failed read stopped, and all done at the end', () => {
    expect(stagesAt('connect', 'error')[4].status).toBe('error');
    expect(stagesAt('store', 'done').every(x => x.status === 'done')).toBe(true);
  });
});
