export interface Instrument { review_status: string }
export interface GapsData { orphans: unknown[]; low_confidence: unknown[]; lonely_equipment: unknown[] }
export interface Source { uploaded: string; cached: boolean; filename?: string }
export interface Stats { node_count: number; edge_count: number }
export interface HomeData { instruments: Instrument[]; gaps: GapsData; exportFiles: string[]; sources: Source[]; stats: Stats }
