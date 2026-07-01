import { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import {
  Label,
  Progress,
  ProgressMeasureLocation,
  Button,
  Tooltip,
  Modal,
  ModalVariant,
} from '@patternfly/react-core';
import CheckCircleIcon from '@patternfly/react-icons/dist/esm/icons/check-circle-icon';
import ExclamationCircleIcon from '@patternfly/react-icons/dist/esm/icons/exclamation-circle-icon';
import ExclamationTriangleIcon from '@patternfly/react-icons/dist/esm/icons/exclamation-triangle-icon';
import InProgressIcon from '@patternfly/react-icons/dist/esm/icons/in-progress-icon';
import PendingIcon from '@patternfly/react-icons/dist/esm/icons/pending-icon';
import AngleRightIcon from '@patternfly/react-icons/dist/esm/icons/angle-right-icon';
import AngleDownIcon from '@patternfly/react-icons/dist/esm/icons/angle-down-icon';
import AngleDoubleDownIcon from '@patternfly/react-icons/dist/esm/icons/angle-double-down-icon';
import AngleDoubleUpIcon from '@patternfly/react-icons/dist/esm/icons/angle-double-up-icon';
import CompressIcon from '@patternfly/react-icons/dist/esm/icons/compress-icon';
import ExpandIcon from '@patternfly/react-icons/dist/esm/icons/expand-icon';
import type {
  MigrationEvent,
  PhaseStartEvent,
  PhaseProgressEvent,
  PhaseCompleteEvent,
  PhaseErrorEvent,
  ResourceResultEvent,
} from '../hooks/useJobLogs';
import './MigrationProgressView.css';

interface ResourceItem {
  name: string;
  resourceType: string;
  result: 'created' | 'updated' | 'skipped' | 'exists' | 'failed';
  detail: string;
}

interface PhaseState {
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

interface MigrationState {
  totalPhases: number;
  phases: PhaseState[];
  totalCreated: number;
  totalUpdated: number;
  totalSkipped: number;
  totalFailed: number;
  status: 'running' | 'complete' | 'failed';
}

function buildMigrationState(events: MigrationEvent[]): MigrationState {
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

function PhaseStatusIcon({ status }: { status: PhaseState['status'] }) {
  switch (status) {
    case 'complete':
      return <CheckCircleIcon className="mpv-icon--success" />;
    case 'failed':
      return <ExclamationCircleIcon className="mpv-icon--danger" />;
    case 'running':
      return <InProgressIcon className="mpv-icon--info mpv-icon--spin" />;
    default:
      return <PendingIcon className="mpv-icon--muted" />;
  }
}

function ResourceResultIcon({ result }: { result: ResourceItem['result'] }) {
  switch (result) {
    case 'created':
      return <CheckCircleIcon className="mpv-icon--success" />;
    case 'failed':
      return <ExclamationCircleIcon className="mpv-icon--danger" />;
    case 'skipped':
    case 'exists':
      return <ExclamationTriangleIcon className="mpv-icon--warning" />;
  }
}

function MigrationStatusBar({ migration }: { migration: MigrationState }) {
  const completedPhases = migration.phases.filter(
    (p) => p.status === 'complete' || p.status === 'failed',
  ).length;

  return (
    <div className="mpv-status-bar">
      <div className="mpv-status-bar__left">
        <span className="mpv-status-bar__title">Migration Output</span>
        <Label color="grey" isCompact>
          {completedPhases}/{migration.totalPhases} phases
        </Label>
      </div>
      <div className="mpv-status-bar__right">
        <Label color="green" isCompact>
          {migration.totalCreated} created
        </Label>
        {migration.totalUpdated > 0 && (
          <Label color="blue" isCompact>
            {migration.totalUpdated} updated
          </Label>
        )}
        {migration.totalSkipped > 0 && (
          <Label color="orange" isCompact>
            {migration.totalSkipped} skipped
          </Label>
        )}
        {migration.totalFailed > 0 && (
          <Label color="red" isCompact>
            {migration.totalFailed} failed
          </Label>
        )}
      </div>
    </div>
  );
}

function MigrationDistributionBar({ migration }: { migration: MigrationState }) {
  const total = migration.totalCreated + migration.totalUpdated + migration.totalSkipped + migration.totalFailed;
  if (total === 0) return null;

  const pctCreated = (migration.totalCreated / total) * 100;
  const pctUpdated = (migration.totalUpdated / total) * 100;
  const pctSkipped = (migration.totalSkipped / total) * 100;
  const pctFailed = (migration.totalFailed / total) * 100;

  return (
    <div className="mpv-dist-bar">
      {pctCreated > 0 && (
        <Tooltip content={`${migration.totalCreated} created`}>
          <div className="mpv-dist-bar__segment mpv-dist-bar__segment--created" style={{ width: `${pctCreated}%` }} />
        </Tooltip>
      )}
      {pctUpdated > 0 && (
        <Tooltip content={`${migration.totalUpdated} updated`}>
          <div className="mpv-dist-bar__segment" style={{ width: `${pctUpdated}%`, backgroundColor: 'var(--pf-v5-global--info-color--100, #06c)' }} />
        </Tooltip>
      )}
      {pctSkipped > 0 && (
        <Tooltip content={`${migration.totalSkipped} skipped`}>
          <div className="mpv-dist-bar__segment mpv-dist-bar__segment--skipped" style={{ width: `${pctSkipped}%` }} />
        </Tooltip>
      )}
      {pctFailed > 0 && (
        <Tooltip content={`${migration.totalFailed} failed`}>
          <div className="mpv-dist-bar__segment mpv-dist-bar__segment--failed" style={{ width: `${pctFailed}%` }} />
        </Tooltip>
      )}
    </div>
  );
}

interface ToolbarProps {
  allExpanded: boolean;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  onScrollTop: () => void;
  onScrollBottom: () => void;
}

function MigrationOutputToolbar({ allExpanded, onExpandAll, onCollapseAll, onScrollTop, onScrollBottom }: ToolbarProps) {
  return (
    <div className="mpv-toolbar">
      <div className="mpv-toolbar__group">
        <Tooltip content={allExpanded ? 'Collapse all' : 'Expand all'}>
          <Button variant="plain" size="sm" onClick={allExpanded ? onCollapseAll : onExpandAll} aria-label={allExpanded ? 'Collapse all' : 'Expand all'}>
            {allExpanded ? <CompressIcon /> : <ExpandIcon />}
          </Button>
        </Tooltip>
      </div>
      <div className="mpv-toolbar__spacer" />
      <div className="mpv-toolbar__group">
        <Tooltip content="Scroll to top">
          <Button variant="plain" size="sm" onClick={onScrollTop} aria-label="Scroll to top">
            <AngleDoubleUpIcon />
          </Button>
        </Tooltip>
        <Tooltip content="Scroll to bottom">
          <Button variant="plain" size="sm" onClick={onScrollBottom} aria-label="Scroll to bottom">
            <AngleDoubleDownIcon />
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}

function ResourceRow({ item }: { item: ResourceItem }) {
  const labelMap: Record<ResourceItem['result'], string> = {
    created: 'Created', updated: 'Updated', skipped: 'Skipped', exists: 'Exists', failed: 'Failed',
  };

  return (
    <div className={`mpv-resource-row mpv-resource-row--${item.result}`}>
      <div className="mpv-resource-row__icon"><ResourceResultIcon result={item.result} /></div>
      <div className="mpv-resource-row__name">{item.name}</div>
      {item.resourceType && (
        <div className="mpv-resource-row__type">
          <Label color="grey" isCompact>{item.resourceType.replace(/_/g, ' ')}</Label>
        </div>
      )}
      <div className="mpv-resource-row__status">
        <Label color={item.result === 'created' ? 'green' : item.result === 'updated' ? 'blue' : item.result === 'failed' ? 'red' : 'orange'} isCompact>
          {labelMap[item.result]}
        </Label>
      </div>
      {item.detail && <div className="mpv-resource-row__detail">{item.detail}</div>}
    </div>
  );
}

interface PhaseGroupProps {
  phase: PhaseState;
  totalPhases: number;
  isExpanded: boolean;
  onToggle: () => void;
  onErrorClick: (error: string) => void;
}

function MigrationPhaseGroup({ phase, totalPhases, isExpanded, onToggle, onErrorClick }: PhaseGroupProps) {
  const hasContent = phase.resources.length > 0 || !!phase.error || phase.status === 'running';
  const phaseTotal = phase.created + phase.updated + phase.skipped + phase.failed;
  const phasePct = phase.exported > 0 ? (phaseTotal / phase.exported) * 100 : phase.status === 'complete' ? 100 : 0;

  return (
    <div className={`mpv-phase-group mpv-phase-group--${phase.status}`}>
      <div className={`mpv-phase-group__header${hasContent ? ' mpv-phase-group__header--clickable' : ''}`} onClick={hasContent ? onToggle : undefined}>
        <div className="mpv-phase-group__gutter">[{phase.num}/{totalPhases}]</div>
        <div className="mpv-phase-group__toggle">
          {hasContent ? (isExpanded ? <AngleDownIcon /> : <AngleRightIcon />) : <span className="mpv-phase-group__toggle-spacer" />}
        </div>
        <div className="mpv-phase-group__icon"><PhaseStatusIcon status={phase.status} /></div>
        <div className="mpv-phase-group__name">{phase.description}</div>
        <div className="mpv-phase-group__counts">
          {phase.status !== 'pending' && phaseTotal > 0 && (
            <>
              <Label color="green" isCompact>{phase.created}</Label>
              {phase.updated > 0 && <Label color="blue" isCompact>{phase.updated}</Label>}
              {phase.skipped > 0 && <Label color="orange" isCompact>{phase.skipped}</Label>}
              {phase.failed > 0 && <Label color="red" isCompact>{phase.failed}</Label>}
            </>
          )}
        </div>
        <div className="mpv-phase-group__duration">{phase.duration || (phase.status === 'running' ? phase.elapsed : '')}</div>
      </div>

      {isExpanded && hasContent && (
        <div className="mpv-phase-group__body">
          {phase.status === 'running' && phase.exported > 0 && (
            <div className="mpv-phase-group__progress">
              <Progress value={phasePct} size="sm" measureLocation={ProgressMeasureLocation.none} />
              <span className="mpv-phase-group__progress-text">{phaseTotal}/{phase.exported} &middot; {phase.rate}</span>
            </div>
          )}
          {phase.resources.map((item, i) => <ResourceRow key={i} item={item} />)}
          {phase.error && (
            <div className="mpv-item-row mpv-item-row--error mpv-item-row--clickable" onClick={() => onErrorClick(phase.error!)} role="button" tabIndex={0}>
              <div className="mpv-item-row__gutter"><ExclamationCircleIcon className="mpv-icon--danger" /></div>
              <div className="mpv-item-row__content">{phase.error}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface DetailModalData { title: string; message: string; }

function DetailModal({ data, onClose }: { data: DetailModalData | null; onClose: () => void }) {
  if (!data) return null;
  return (
    <Modal variant={ModalVariant.medium} isOpen onClose={onClose} title={data.title} actions={[<Button key="close" variant="primary" onClick={onClose}>Close</Button>]}>
      <p>{data.message}</p>
    </Modal>
  );
}

interface Props { events: MigrationEvent[]; jobStatus: string; }

export function MigrationProgressView({ events, jobStatus }: Props) {
  const migration = useMemo(() => buildMigrationState(events), [events]);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [modalData, setModalData] = useState<DetailModalData | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);

  useEffect(() => {
    const next: Record<number, boolean> = { ...expanded };
    for (const p of migration.phases) {
      if (p.status === 'running' && !(p.num in next)) next[p.num] = true;
    }
    setExpanded(next);
  }, [migration.phases.length]);

  useEffect(() => {
    if (autoScrollRef.current && scrollRef.current && migration.status === 'running') {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [migration.phases.length, events.length, migration.status]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const handleScroll = () => { autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60; };
    el.addEventListener('scroll', handleScroll);
    return () => el.removeEventListener('scroll', handleScroll);
  }, []);

  const toggleExpand = useCallback((num: number) => { setExpanded(prev => ({ ...prev, [num]: !prev[num] })); }, []);
  const expandAll = useCallback(() => { const next: Record<number, boolean> = {}; migration.phases.forEach(p => { next[p.num] = true; }); setExpanded(next); }, [migration.phases]);
  const collapseAll = useCallback(() => { setExpanded({}); }, []);
  const allExpanded = migration.phases.length > 0 && migration.phases.every(p => expanded[p.num]);
  const scrollToTop = useCallback(() => { scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' }); }, []);
  const scrollToBottom = useCallback(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }); }, []);
  const handleErrorClick = useCallback((error: string) => { setModalData({ title: 'Error Details', message: error }); }, []);

  if (events.length === 0) {
    return (
      <div className="mpv-output">
        <div className="mpv-empty">
          {jobStatus === 'running' || jobStatus === 'streaming' || jobStatus === 'connecting'
            ? 'Waiting for migration events...'
            : 'No migration progress data available.'}
        </div>
      </div>
    );
  }

  return (
    <div className="mpv-output">
      <MigrationStatusBar migration={migration} />
      <MigrationDistributionBar migration={migration} />
      <MigrationOutputToolbar allExpanded={allExpanded} onExpandAll={expandAll} onCollapseAll={collapseAll} onScrollTop={scrollToTop} onScrollBottom={scrollToBottom} />
      <div className="mpv-scroll" ref={scrollRef}>
        {migration.phases.map(phase => (
          <MigrationPhaseGroup key={phase.num} phase={phase} totalPhases={migration.totalPhases} isExpanded={!!expanded[phase.num]} onToggle={() => toggleExpand(phase.num)} onErrorClick={handleErrorClick} />
        ))}
        {migration.status !== 'running' && (
          <div className="mpv-summary">
            Migration {migration.status === 'complete' ? 'completed' : 'finished with errors'}:{' '}
            <strong>{migration.totalCreated}</strong> created,{' '}
            {migration.totalUpdated > 0 && (<><strong>{migration.totalUpdated}</strong> updated,{' '}</>)}
            <strong>{migration.totalSkipped}</strong> skipped,{' '}
            <strong>{migration.totalFailed}</strong> failed
          </div>
        )}
      </div>
      <DetailModal data={modalData} onClose={() => setModalData(null)} />
    </div>
  );
}
