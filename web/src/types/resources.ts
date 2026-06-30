export interface ResourceType {
  name: string;
  label: string;
  api_path: string;
}

export interface JobMetadata {
  events?: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface Job {
  id: string;
  seq_id?: number;
  name?: string;
  type: string;
  connection_id?: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  started_at: string;
  finished_at?: string;
  error?: string;
  output?: string[];
  job_metadata?: JobMetadata;
}

export interface MigrationResource {
  source_id: number;
  name: string;
  type: string;
  action: string;
  dest_id?: number;
}

export interface MigrationPreviewData {
  source_id: string;
  destination_id: string;
  resources: Record<string, MigrationResource[]>;
  resource_summaries?: Record<string, { total: number; create: number; skip_exists: number; displayed: number; truncated: boolean }>;
  warnings: string[];
  host_counts?: Record<string, number>;
  group_counts?: Record<string, number>;
}

export interface DefaultExclusions {
  migration: Record<string, string[]>;
  cleanup: Record<string, Record<string, string[]>>;
}
