import type { MigrationEvent } from './useJobLogs';

/** WebSocket / REST log lines that carry structured migration events are tab-prefixed. */
export const EVENT_WS_PREFIX = '\t';

export function isEventMessage(line: string): boolean {
  return line.charAt(0) === EVENT_WS_PREFIX;
}

export function parseEventMessage(line: string): MigrationEvent | null {
  try {
    return JSON.parse(line.slice(1)) as MigrationEvent;
  } catch {
    return null;
  }
}
