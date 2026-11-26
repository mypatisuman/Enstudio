import { describe, it, expect } from 'vitest';
import { nodeConfidence, confidenceBucket } from './confidence';

describe('review confidence of digitised symbols', () => {
  it('puts what must be confirmed in the low bucket', () => {
    expect(confidenceBucket(nodeConfidence({ inferred: true, source: 'brownfield_vision' }))).toBe('low');
    expect(confidenceBucket(nodeConfidence({ untagged: true, source: 'brownfield_vision' }))).toBe('low');
  });
  it('rates a tag placed on its printed text above an estimated one', () => {
    const exact = nodeConfidence({ source: 'brownfield_vision', snapped: true });
    const estimated = nodeConfidence({ source: 'brownfield_vision' });
    expect(exact).toBeGreaterThan(estimated);
    expect(confidenceBucket(estimated)).toBe('high');
  });
  it('keeps an explicit score and the page default otherwise', () => {
    expect(nodeConfidence({ confidence: 0.4, inferred: true })).toBe(0.4);
    expect(nodeConfidence({}, 0.92)).toBe(0.92);
  });
});
