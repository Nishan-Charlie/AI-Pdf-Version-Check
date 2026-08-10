export type ChangeType =
  | "Unchanged"
  | "Minor Edit"
  | "Significant Change"
  | "Added"
  | "Removed";

export interface Jurisdiction {
  code: string;
  name: string;
  sigil: string;
  authority: string;
  instrument: string;
  parser_profile: string;
}

export interface LibraryStats {
  documents: number;
  versions: number;
  clauses: number;
  by_country: Record<string, number>;
}

export interface Meta {
  jurisdictions: Jurisdiction[];
  change_types: ChangeType[];
  thresholds: { unchanged: number; minor_edit: number };
  model: string;
  stats: LibraryStats;
}

export interface VersionRecord {
  id: number;
  document_id: number;
  document_name: string;
  country_code: string;
  country_name: string;
  doc_type: string | null;
  version_label: string;
  source_file: string | null;
  parser_profile: string | null;
  parser_confidence: string | null;
  page_count: number | null;
  clause_count: number;
  uploaded_at: string | null;
}

export interface ClauseSide {
  clause_number: string;
  title: string | null;
  section: string | null;
  content: string;
  ordinal: number;
}

export interface Redline {
  html_v1: string;
  html_v2: string;
  html_unified: string;
  words_removed: number;
  words_added: number;
  words_unchanged: number;
  word_change_ratio: number;
}

export interface ClauseComparison {
  index: number;
  label: string;
  change_type: ChangeType;
  similarity_score: number | null;
  match_score: number | null;
  match_method: string;
  v1: ClauseSide | null;
  v2: ClauseSide | null;
  redline: Redline;
}

export interface VersionRef {
  version_id: number | null;
  document_name: string;
  version_label: string;
  country_code: string;
  country_name: string;
}

export interface ComparisonSummary {
  total_clauses: number;
  unchanged: number;
  minor_edits: number;
  significant_changes: number;
  added: number;
  removed: number;
  words_added: number;
  words_removed: number;
  changed: number;
  change_rate: number;
}

export interface ModelInfo {
  key: string;
  id: string;
  dimensions: number;
  window: number;
  size_mb: number;
  /** Weights are on disk — switching to it is instant. */
  downloaded: boolean;
  /** Weights are resident in the service right now. */
  loaded: boolean;
  is_default: boolean;
}

export type DownloadState =
  | "idle"
  | "resolving"
  | "downloading"
  | "loading"
  | "ready"
  | "error";

export interface DownloadStatus {
  model: string;
  state: DownloadState;
  percent: number;
  done_bytes: number;
  total_bytes: number;
  message: string;
  error: string;
  elapsed_seconds: number;
}

export interface ComparisonReport {
  v1: VersionRef;
  v2: VersionRef;
  alignment_method: "identifier" | "semantic";
  /** Which encoder produced the similarity scores. */
  model: string;
  identifier_overlap: number;
  is_cross_country: boolean;
  duration_seconds: number;
  summary: ComparisonSummary;
  comparisons: ClauseComparison[];
}

export interface CorpusEntry {
  key: string;
  title: string;
  jurisdiction: string;
  publisher: string;
  edition: string;
  kind: "base" | "amendment" | "circular";
  access: "open" | "licensed";
  url: string;
  filename: string;
  present: boolean;
  size_bytes: number;
  notes: string;
}

export interface CorpusStatus {
  summary: {
    total: number;
    collected: number;
    downloadable: number;
    downloadable_collected: number;
    licensed: number;
    licensed_collected: number;
    bytes: number;
  };
  entries: CorpusEntry[];
}

export interface SearchHit {
  id: number;
  clause_number: string;
  title: string | null;
  content: string;
  section: string | null;
  level: number;
  ordinal: number;
  version_id: number;
  version_label: string;
  document_id: number;
  document_name: string;
  country_code: string;
  country_name: string;
  excerpt: string;
}
