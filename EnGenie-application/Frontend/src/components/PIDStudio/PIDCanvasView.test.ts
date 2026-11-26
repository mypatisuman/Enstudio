import { describe, it, expect } from 'vitest';
import { edgeLabel, provenanceStyle } from './PIDCanvasView';
import { provenanceOf } from '../../features/canvas/components/SidePanel';
import { edgeStyle } from '../../features/canvas/utils/edgeHelpers';

describe('digitised P&ID on the canvas', () => {
  it('labels a connection with its printed line number, else its size and spec', () => {
    expect(edgeLabel({ printed_line_no: 'H2-1001-1/4-T035.316-NI', size: '1/4"' })).toBe('H2-1001-1/4-T035.316-NI');
    expect(edgeLabel({ size: '1/2"', spec: 'T9L' })).toBe('1/2" T9L');
    expect(edgeLabel({ label: 'L-001' })).toBe('');
  });

  it('marks inferred, untagged and placeholder symbols differently from read ones', () => {
    expect(provenanceStyle({ inferred: true })?.outline).toContain('dashed');
    expect(provenanceStyle({ untagged: true })?.outline).toContain('dotted');
    expect(provenanceStyle({ placeholder: true })).toBeDefined();
    expect(provenanceStyle({ source: 'brownfield_vision' })).toBeUndefined();
  });

  it('tells the engineer how each symbol was obtained', () => {
    expect(provenanceOf({ inferred: true })?.text).toMatch(/confirm/);
    expect(provenanceOf({ untagged: true })?.text).toMatch(/Untagged/);
    expect(provenanceOf({ source: 'brownfield_vision' })?.text).toMatch(/Read from the drawing/);
    expect(provenanceOf({})).toBeNull();
  });

  it('draws every connection kind the digitiser produces', () => {
    expect(edgeStyle('signal').strokeDasharray).toBe('6 4');
    expect(edgeStyle('impulse').strokeDasharray).toBe('1 4');
    expect(edgeStyle('utility').strokeDasharray).toBe('2 2');
    expect(edgeStyle('process').strokeDasharray).toBeUndefined();
  });
});
