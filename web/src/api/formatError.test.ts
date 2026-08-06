import { describe, expect, it } from 'vitest';
import { formatErrorValue } from './formatError';

describe('formatErrorValue', () => {
  it('returns non-empty strings as-is', () => {
    expect(formatErrorValue('boom', 'fallback')).toBe('boom');
  });

  it('uses fallback for nullish values', () => {
    expect(formatErrorValue(null, 'fallback')).toBe('fallback');
    expect(formatErrorValue(undefined, 'fallback')).toBe('fallback');
  });

  it('JSON-stringifies empty string (same as other non-nullish non-text)', () => {
    expect(formatErrorValue('', 'fallback')).toBe('""');
  });

  it('JSON-stringifies objects', () => {
    expect(formatErrorValue({ code: 1 }, 'fallback')).toBe('{"code":1}');
  });
});
