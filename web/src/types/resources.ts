export interface ResourceType {
  name: string;
  label: string;
  api_path: string;
}

export interface Job {
  id: string;
  type: string;
  connection_id: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  started_at: string;
  finished_at?: string;
  error?: string;
  output: string[];
}

export interface MigrationResource {
  source_id: number;
  name: string;
  type: string;
  action: string;
  dest_id?: number;
}

export interface MigrationPreviewSummary {
  total: number;
  create: number;
  skip_exists: number;
  displayed: number;
  truncated: boolean;
}

export interface MigrationPreviewData {
  source_id: string;
  destination_id: string;
  resources: Record<string, MigrationResource[]>;
  resource_summaries: Record<string, MigrationPreviewSummary>;
  warnings: string[];
  host_counts?: Record<string, number>;
  group_counts?: Record<string, number>;
}

export interface DefaultExclusions {
  migration: Record<string, string[]>;
  cleanup: Record<string, Record<string, string[]>>;
}
