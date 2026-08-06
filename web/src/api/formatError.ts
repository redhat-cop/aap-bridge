/** Format API error payloads for user-facing Error messages. */
export function formatErrorValue(value: unknown, fallback: string): string {
  if (typeof value === 'string' && value) return value;
  if (value === null || value === undefined) return fallback;
  try {
    return JSON.stringify(value);
  } catch {
    return fallback;
  }
}
