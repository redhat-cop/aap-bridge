import { useState, useEffect, useRef } from 'react';
import { createJobLogSocket, api } from '../api/client';
import type { Job } from '../types/resources';

const EVENT_WS_PREFIX = '\t';

export interface MigrationEvent {
  _event: string;
  [key: string]: unknown;
}

export interface MigrationStartEvent extends MigrationEvent {
  _event: 'migration_start';
  total_phases: number;
}

export interface PhaseStartEvent extends MigrationEvent {
  _event: 'phase_start';
  phase_num: number;
  total_phases: number;
  description: string;
  resource_type?: string;
}

export interface PhaseProgressEvent extends MigrationEvent {
  _event: 'phase_progress';
  phase_num: number;
  exported: number;
  created: number;
  skipped: number;
  failed: number;
  rate: string;
  elapsed: string;
}

export interface PhaseCompleteEvent extends MigrationEvent {
  _event: 'phase_complete';
  phase_num: number;
  description: string;
  created: number;
  updated: number;
  skipped: number;
  failed: number;
  exported: number;
  duration: string;
  warnings: Record<string, number>;
  warning_samples?: Record<string, string[]>;
}

export interface PhaseErrorEvent extends MigrationEvent {
  _event: 'phase_error';
  phase_num: number;
  error: string;
}

export interface ResourceResultEvent extends MigrationEvent {
  _event: 'resource_result';
  phase_num: number;
  name: string;
  resource_type: string;
  result: 'created' | 'updated' | 'skipped' | 'exists' | 'failed';
  detail: string;
}

export interface MigrationCompleteEvent extends MigrationEvent {
  _event: 'migration_complete';
  total_created: number;
  total_updated: number;
  total_skipped: number;
  total_failed: number;
}

function isEventMessage(line: string): boolean {
  return line.charAt(0) === EVENT_WS_PREFIX;
}

function parseEventMessage(line: string): MigrationEvent | null {
  try {
    return JSON.parse(line.slice(1)) as MigrationEvent;
  } catch {
    return null;
  }
}

export function useJobLogs(jobId: string) {
  const [textLines, setTextLines] = useState<string[]>([]);
  const [events, setEvents] = useState<MigrationEvent[]>([]);
  const [status, setStatus] = useState<string>('connecting');
  const wsReceivedRef = useRef(false);

  useEffect(() => {
    if (!jobId) {
      setStatus('empty');
      return;
    }

    setTextLines([]);
    setEvents([]);
    setStatus('connecting');
    wsReceivedRef.current = false;
    let closed = false;

    const ws = createJobLogSocket(
      jobId,
      (line) => {
        wsReceivedRef.current = true;
        if (isEventMessage(line)) {
          const evt = parseEventMessage(line);
          if (evt) setEvents(prev => [...prev, evt]);
        } else {
          setTextLines(prev => [...prev, line]);
        }
        setStatus('streaming');
      },
      (reason) => {
        const finalStatus = reason || 'closed';
        setStatus(finalStatus);
        if (!wsReceivedRef.current && !closed) {
          loadFromRest();
        }
      },
    );

    async function loadFromRest() {
      try {
        const job = (await api.getJob(jobId)) as Job;
        if (job.output && job.output.length > 0) {
          const text: string[] = [];
          const evts: MigrationEvent[] = [];
          for (const line of job.output) {
            if (isEventMessage(line)) {
              const evt = parseEventMessage(line);
              if (evt) evts.push(evt);
            } else {
              text.push(line);
            }
          }
          setTextLines(text);
          if (evts.length > 0) setEvents(evts);
        }
        if (events.length === 0) {
          const meta = job.job_metadata;
          if (meta && Array.isArray(meta.events)) {
            setEvents(meta.events as MigrationEvent[]);
          }
        }
        setStatus(job.status || 'empty');
      } catch {
        setStatus('error');
      }
    }

    return () => {
      closed = true;
      ws.close();
    };
  }, [jobId]);

  return { textLines, events, status };
}
