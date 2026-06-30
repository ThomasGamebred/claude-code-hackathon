export interface SourceInfo {
  name: string;
  row_count: number;
  quality_score: number;
  last_ingested_at: string;
  anomaly_count: number;
  notes?: string;
}

export interface CustomerSummary {
  id: string;
  full_name: string;
  city: string | null;
  region: string | null;
  n_sources: number;
  record_confidence: number;
}

export interface SourceContribution {
  source: string;
  source_id: string;
  source_row: number;
  ingested_at: string;
  fields: Record<string, string | null>;
  field_quality_flags: string[];
}

export interface FieldProvenance {
  field: string;
  value: string | null;
  source: string;
  confidence: number;
  rationale?: string;
}

export interface CustomerDetail {
  id: string;
  full_name: string;
  city: string | null;
  region: string | null;
  birth_year: number | null;
  n_sources: number;
  record_confidence: number;
  fields: FieldProvenance[];
  contributions: SourceContribution[];
}

export interface ReviewPair {
  id: string;
  score: number;
  left: ReviewSide;
  right: ReviewSide;
  reason: string;
}

export interface ReviewSide {
  source: string;
  source_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  address: string | null;
  dob: string | null;
}

export interface QualityCheck {
  name: string;
  level: "BLOCK" | "ALERT" | "INFO";
  status: "pass" | "fail";
  message: string;
  ran_at: string;
}

export interface LineageNode {
  id: string;
  kind: "master" | "xref" | "conformed" | "raw";
  label: string;
  meta?: Record<string, string | number | null>;
}

export interface LineageEdge {
  from: string;
  to: string;
}

export interface LineageGraph {
  root: string;
  nodes: LineageNode[];
  edges: LineageEdge[];
}
