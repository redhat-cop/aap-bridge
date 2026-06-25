import { useState, useEffect, useCallback, Component, type ReactNode } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Title,
  Button,
  Label,
  Split,
  SplitItem,
  Card,
  CardBody,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  Spinner,
  Alert,
  Tabs,
  Tab,
  TabTitleText,
} from '@patternfly/react-core';
import ArrowLeftIcon from '@patternfly/react-icons/dist/esm/icons/arrow-left-icon';
import { LogViewer } from '../components/LogViewer';
import { MigrationProgressView } from '../components/MigrationProgressView';
import { useJobLogs } from '../hooks/useJobLogs';
import { api } from '../api/client';
import type { Job } from '../types/resources';

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <Alert variant="danger" isInline title="Component Error">
          <p>{this.state.error.message}</p>
          <pre style={{ fontSize: '0.8em', whiteSpace: 'pre-wrap' }}>{this.state.error.stack}</pre>
        </Alert>
      );
    }
    return this.props.children;
  }
}

export function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [activeTab, setActiveTab] = useState<string>('results');

  const jobLogs = useJobLogs(id ?? '');

  const loadJob = useCallback(async () => {
    if (!id) return;
    try {
      const data = await api.getJob(id) as Job;
      setJob(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load job');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadJob();
    const interval = setInterval(loadJob, 5000);
    return () => clearInterval(interval);
  }, [loadJob]);

  useEffect(() => {
    if (!job || job.type !== 'migration-run') return;
    const s = jobLogs.status;
    if (s && !['streaming', 'connecting'].includes(s)) {
      setJob(prev => prev ? { ...prev, status: s as Job['status'] } : prev);
    }
  }, [job?.type, jobLogs.status]);

  const handleCancel = async () => {
    if (!id || cancelling) return;
    setCancelling(true);
    try {
      await api.cancelJob(id);
      loadJob();
    } catch {
      // Job may have already finished
    } finally {
      setCancelling(false);
    }
  };

  const handleLogClose = (status: string) => {
    if (job) {
      setJob({ ...job, status: status as Job['status'] });
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case 'running': return 'blue';
      case 'completed': return 'green';
      case 'failed': return 'red';
      case 'cancelled': return 'orange';
      default: return 'grey';
    }
  };

  const formatTime = (iso?: string) => {
    if (!iso) return '—';
    return new Date(iso).toLocaleString();
  };

  const formatDuration = (j: Job) => {
    const start = new Date(j.started_at).getTime();
    const end = j.finished_at ? new Date(j.finished_at).getTime() : Date.now();
    const sec = Math.round((end - start) / 1000);
    if (sec < 60) return `${sec}s`;
    return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spinner size="xl" />
      </div>
    );
  }

  if (error || !job) {
    return (
      <>
        <Button variant="link" icon={<ArrowLeftIcon />} onClick={() => navigate('/jobs')}>
          Back to Jobs
        </Button>
        <Alert variant="danger" isInline title={error || 'Job not found'} style={{ marginTop: 16 }} />
      </>
    );
  }

  const isMigrationRun = job.type === 'migration-run';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Split hasGutter style={{ marginBottom: 16, alignItems: 'center' }}>
        <SplitItem>
          <Button variant="link" icon={<ArrowLeftIcon />} onClick={() => navigate('/jobs')}>
            Back to Jobs
          </Button>
        </SplitItem>
        <SplitItem isFilled>
          <Title headingLevel="h1" size="xl">
            Job #{job.seq_id ?? '—'}: {job.type}
          </Title>
        </SplitItem>
        <SplitItem>
          {job.status === 'running' && (
            <Button
              variant="danger"
              onClick={handleCancel}
              isDisabled={cancelling}
              isLoading={cancelling}
            >
              {cancelling ? 'Cancelling...' : 'Cancel Job'}
            </Button>
          )}
        </SplitItem>
      </Split>

      <Card isCompact style={{ marginBottom: 16 }}>
        <CardBody>
          <DescriptionList isHorizontal isCompact columnModifier={{ default: '3Col' }}>
            <DescriptionListGroup>
              <DescriptionListTerm>Status</DescriptionListTerm>
              <DescriptionListDescription>
                <Label color={statusColor(job.status)}>{job.status}</Label>
              </DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>Type</DescriptionListTerm>
              <DescriptionListDescription>{job.type}</DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>Duration</DescriptionListTerm>
              <DescriptionListDescription>{formatDuration(job)}</DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>Started</DescriptionListTerm>
              <DescriptionListDescription>{formatTime(job.started_at)}</DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>Finished</DescriptionListTerm>
              <DescriptionListDescription>{formatTime(job.finished_at)}</DescriptionListDescription>
            </DescriptionListGroup>
            {job.error && (
              <DescriptionListGroup>
                <DescriptionListTerm>Error</DescriptionListTerm>
                <DescriptionListDescription>
                  <Label color="red" isCompact>{job.error}</Label>
                </DescriptionListDescription>
              </DescriptionListGroup>
            )}
          </DescriptionList>
        </CardBody>
      </Card>

      {isMigrationRun ? (
        <ErrorBoundary>
          <Tabs activeKey={activeTab} onSelect={(_e, k) => setActiveTab(k as string)} style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <Tab eventKey="results" title={<TabTitleText>Output</TabTitleText>} style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              <div style={{ padding: '16px 0', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                <MigrationProgressView events={jobLogs.events} jobStatus={jobLogs.status} />
              </div>
            </Tab>
            <Tab eventKey="logs" title={<TabTitleText>Logs</TabTitleText>}>
              <div style={{ padding: '16px 0', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                <LogViewer jobId={job.id} externalLines={jobLogs.textLines} externalStatus={jobLogs.status} fullPage />
              </div>
            </Tab>
          </Tabs>
        </ErrorBoundary>
      ) : (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <LogViewer jobId={job.id} onClose={handleLogClose} fullPage />
        </div>
      )}
    </div>
  );
}
