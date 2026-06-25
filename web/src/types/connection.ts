export interface Connection {
  id: string;
  name: string;
  type: string;
  role: 'source' | 'destination';
  url: string;
  token: string | null;
  verify_ssl: boolean;
  version?: string;
  api_prefix?: string;
  ping_status?: 'unknown' | 'ok' | 'error';
  ping_error?: string;
  auth_status?: 'unknown' | 'ok' | 'error';
  auth_error?: string;
  last_checked?: string;
}

export type ConnectionPayload = Omit<Connection, 'id' | 'token' | 'type' | 'version'> & {
  version: string;
  token?: string;
};

export interface SupportedVersions {
  source_versions: string[];
  target_versions: string[];
}

export interface TestResult {
  ok: boolean;
  error?: string;
}
