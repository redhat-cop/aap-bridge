import { describe, expect, it } from 'vitest';
import { buildMigrationState } from './migrationState';
import type { MigrationEvent } from '../hooks/useJobLogs';

describe('buildMigrationState', () => {
  it('aggregates phase totals while running', () => {
    const events: MigrationEvent[] = [
      { _event: 'migration_start', total_phases: 2 },
      {
        _event: 'phase_start',
        phase_num: 1,
        total_phases: 2,
        description: 'orgs',
      },
      {
        _event: 'phase_progress',
        phase_num: 1,
        exported: 3,
        created: 2,
        skipped: 1,
        failed: 0,
        rate: '1/s',
        elapsed: '1s',
      },
    ];

    const state = buildMigrationState(events);
    expect(state.status).toBe('running');
    expect(state.totalPhases).toBe(2);
    expect(state.phases).toHaveLength(1);
    expect(state.phases[0].created).toBe(2);
    expect(state.phases[0].skipped).toBe(1);
    expect(state.totalCreated).toBe(2);
  });

  it('marks migration failed when migration_complete reports failures', () => {
    const events: MigrationEvent[] = [
      { _event: 'migration_start', total_phases: 1 },
      {
        _event: 'phase_start',
        phase_num: 1,
        total_phases: 1,
        description: 'orgs',
      },
      {
        _event: 'phase_error',
        phase_num: 1,
        error: 'boom',
      },
      {
        _event: 'migration_complete',
        total_created: 0,
        total_updated: 0,
        total_skipped: 0,
        total_failed: 1,
      },
    ];

    const state = buildMigrationState(events);
    expect(state.status).toBe('failed');
    expect(state.phases[0].status).toBe('failed');
    expect(state.phases[0].error).toBe('boom');
    expect(state.totalFailed).toBe(1);
  });
});
