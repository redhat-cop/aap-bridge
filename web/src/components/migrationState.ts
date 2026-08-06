import type {
  MigrationEvent,
  PhaseStartEvent,
  PhaseProgressEvent,
  PhaseCompleteEvent,
  PhaseErrorEvent,
  ResourceResultEvent,
} from '../hooks/useJobLogs';

export interface ResourceItem {
  name: string;
  resourceType: string;
  result: 'created' | 'updated' | 'skipped' | 'exists' | 'failed';
  detail: string;
}

export interface PhaseState {
  num: number;
  description: string;
  status: 'pending' | 'running' | 'complete' | 'failed';
  exported: number;
  created: number;
  updated: number;
  skipped: number;
  failed: number;
  rate: string;
  elapsed: string;
  duration: string;
  resources: ResourceItem[];
  error?: string;
}

export interface MigrationState {
  totalPhases: number;
  phases: PhaseState[];
  totalCreated: number;
  totalUpdated: number;
  totalSkipped: number;
  totalFailed: number;
  status: 'running' | 'complete' | 'failed';
}

/** Reduce a stream of migration WS/REST events into UI progress state. */
export function buildMigrationState(events: MigrationEvent[]): MigrationState {
  const state: MigrationState = {
    totalPhases: 0,
    phases: [],
    totalCreated: 0,
    totalUpdated: 0,
    totalSkipped: 0,
    totalFailed: 0,
    status: 'running',
  };

  const phaseMap = new Map<number, PhaseState>();

  for (const evt of events) {
    switch (evt._event) {
      case 'migration_start':
        state.totalPhases = evt.total_phases as number;
        break;

      case 'phase_start': {
        const e = evt as PhaseStartEvent;
        if (e.total_phases && e.total_phases > state.totalPhases) {
          state.totalPhases = e.total_phases;
        }
        phaseMap.set(e.phase_num, {
          num: e.phase_num,
          description: e.description,
          status: 'running',
          exported: 0,
          created: 0,
          updated: 0,
          skipped: 0,
          failed: 0,
          rate: '--/s',
          elapsed: '0s',
          duration: '',
          resources: [],
        });
        break;
      }

      case 'phase_progress': {
        const e = evt as PhaseProgressEvent;
        const phase = phaseMap.get(e.phase_num);
        if (phase) {
          phase.exported = e.exported;
          phase.created = e.created;
          phase.skipped = e.skipped;
          phase.failed = e.failed;
          phase.rate = e.rate;
          phase.elapsed = e.elapsed;
        }
        break;
      }

      case 'resource_result': {
        const e = evt as ResourceResultEvent;
        const phase = phaseMap.get(e.phase_num);
        if (phase) {
          phase.resources.push({
            name: e.name,
            resourceType: e.resource_type,
            result: e.result,
            detail: e.detail,
          });
          if (phase.resources.length > 200) {
            phase.resources = phase.resources.slice(-200);
          }
        }
        break;
      }

      case 'phase_complete': {
        const e = evt as PhaseCompleteEvent;
        const phase = phaseMap.get(e.phase_num);
        if (phase) {
          phase.status = e.failed > 0 ? 'failed' : 'complete';
          phase.created = e.created;
          phase.updated = e.updated || 0;
          phase.skipped = e.skipped;
          phase.failed = e.failed;
          phase.exported = e.exported;
          phase.duration = e.duration;
        }
        break;
      }

      case 'phase_error': {
        const e = evt as PhaseErrorEvent;
        const phase = phaseMap.get(e.phase_num);
        if (phase) {
          phase.status = 'failed';
          phase.error = e.error;
        }
        break;
      }

      case 'migration_complete': {
        state.totalCreated = evt.total_created as number;
        state.totalUpdated = (evt.total_updated as number) || 0;
        state.totalSkipped = evt.total_skipped as number;
        state.totalFailed = evt.total_failed as number;
        state.status = state.totalFailed > 0 ? 'failed' : 'complete';
        break;
      }
    }
  }

  state.phases = Array.from(phaseMap.values()).sort((a, b) => a.num - b.num);

  if (state.status === 'running') {
    const computed = { created: 0, updated: 0, skipped: 0, failed: 0 };
    for (const p of state.phases) {
      computed.created += p.created;
      computed.updated += p.updated;
      computed.skipped += p.skipped;
      computed.failed += p.failed;
    }
    state.totalCreated = computed.created;
    state.totalUpdated = computed.updated;
    state.totalSkipped = computed.skipped;
    state.totalFailed = computed.failed;
  }

  return state;
}
