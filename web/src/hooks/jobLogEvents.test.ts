import { describe, expect, it } from 'vitest';
import { EVENT_WS_PREFIX, isEventMessage, parseEventMessage } from './jobLogEvents';

describe('jobLogEvents', () => {
  it('detects tab-prefixed event lines', () => {
    expect(isEventMessage(`${EVENT_WS_PREFIX}{"_event":"x"}`)).toBe(true);
    expect(isEventMessage('plain log line')).toBe(false);
  });

  it('parses valid event JSON after the prefix', () => {
    const evt = parseEventMessage(`${EVENT_WS_PREFIX}{"_event":"phase_start","phase_num":1}`);
    expect(evt).toEqual({ _event: 'phase_start', phase_num: 1 });
  });

  it('returns null for invalid JSON', () => {
    expect(parseEventMessage(`${EVENT_WS_PREFIX}{not-json`)).toBeNull();
  });
});
