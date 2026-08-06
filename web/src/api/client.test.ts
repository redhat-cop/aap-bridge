import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './client';

describe('api client', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('listConnections GETs /api/connections', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([{ id: '1' }]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.listConnections()).resolves.toEqual([{ id: '1' }]);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/connections',
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('throws Error using JSON detail on failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'nope' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    await expect(api.testConnection('x')).rejects.toThrow('nope');
  });
});
