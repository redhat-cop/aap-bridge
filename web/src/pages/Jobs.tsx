import { useState, useEffect, useCallback } from 'react';
import {
  Title,
  Label,
  Button,
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { Job } from '../types/resources';

export function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const navigate = useNavigate();

  const loadJobs = useCallback(async () => {
    try {
      const data = await api.listJobs();
      setJobs(data as Job[]);
    } catch { /* API may be restarting */ }
  }, []);

  useEffect(() => {
    loadJobs();
    const interval = setInterval(loadJobs, 3000);
    return () => clearInterval(interval);
  }, [loadJobs]);

  const statusColor = (status: string) => {
    switch (status) {
      case 'pending': return 'grey';
      case 'running': return 'blue';
      case 'completed': return 'green';
      case 'failed': return 'red';
      case 'cancelled': return 'orange';
      default: return 'grey';
    }
  };

  const formatTime = (iso: string) => {
    return new Date(iso).toLocaleString();
  };

  const formatDuration = (job: Job) => {
    const start = new Date(job.started_at).getTime();
    const end = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
    const sec = Math.round((end - start) / 1000);
    if (sec < 60) return `${sec}s`;
    return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  };

  return (
    <>
      <Title headingLevel="h1" size="2xl">Jobs</Title>
      <Button variant="secondary" onClick={loadJobs} style={{ marginBottom: 16, marginTop: 8 }}>Refresh</Button>

      <Table aria-label="Jobs" variant="compact">
        <Thead>
          <Tr>
            <Th width={10}>#</Th>
            <Th>Name</Th>
            <Th>Type</Th>
            <Th>Status</Th>
            <Th>Started</Th>
            <Th>Duration</Th>
            <Th>Actions</Th>
          </Tr>
        </Thead>
        <Tbody>
          {jobs.map(job => (
            <Tr
              key={job.id}
              isClickable
              onRowClick={() => navigate(`/jobs/${job.id}`)}
              style={{ cursor: 'pointer' }}
            >
              <Td><strong>{job.seq_id ?? '—'}</strong></Td>
              <Td>{job.name || job.type}</Td>
              <Td>{job.type}</Td>
              <Td>
                <Label color={statusColor(job.status)}>{job.status}</Label>
              </Td>
              <Td>{formatTime(job.started_at)}</Td>
              <Td>{formatDuration(job)}</Td>
              <Td>
                <Button variant="link" onClick={(e) => { e.stopPropagation(); navigate(`/jobs/${job.id}`); }}>
                  View
                </Button>
              </Td>
            </Tr>
          ))}
          {jobs.length === 0 && (
            <Tr>
              <Td colSpan={7}>No jobs yet. Start a migration to see jobs here.</Td>
            </Tr>
          )}
        </Tbody>
      </Table>
    </>
  );
}
