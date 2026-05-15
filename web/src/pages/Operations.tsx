import { useState, useEffect, useCallback } from 'react';
import {
  Button,
  Title,
  TextContent,
  Text,
  Alert,
  Label,
  Split,
  SplitItem,
  Flex,
  FlexItem,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
} from '@patternfly/react-core';
import TimesIcon from '@patternfly/react-icons/dist/esm/icons/times-icon';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { LogViewer } from '../components/LogViewer';
import type { Connection } from '../types/connection';

interface ActiveJob {
  id: string;
  connName: string;
  operation: string;
}

export function Operations() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeJobs, setActiveJobs] = useState<ActiveJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [runningOperation, setRunningOperation] = useState<string | null>(null);
  const navigate = useNavigate();

  const loadConnections = useCallback(async () => {
    const conns = await api.listConnections() as Connection[];
    setConnections(conns);
  }, []);

  useEffect(() => { loadConnections(); }, [loadConnections]);

  const handleOperation = async (id: string, op: 'cleanup' | 'export') => {
    setError(null);
    if (op === 'cleanup') {
      const conn = connections.find(c => c.id === id);
      const confirmed = window.confirm(
        `Run cleanup on "${conn?.name || id}"? This deletes non-default resources from the selected destination.`
      );
      if (!confirmed) return;
    }

    setRunningOperation(`${id}:${op}`);
    try {
      let result: { job_id: string };
      switch (op) {
        case 'cleanup': result = await api.runCleanup(id); break;
        case 'export': result = await api.runExport(id); break;
      }
      const conn = connections.find(c => c.id === id);
      setActiveJobs(prev => [...prev, {
        id: result.job_id,
        connName: conn?.name || id,
        operation: op,
      }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunningOperation(null);
    }
  };

  const dismissJob = (jobId: string) => {
    setActiveJobs(prev => prev.filter(j => j.id !== jobId));
  };

  const selected = connections.find(c => c.id === selectedId);

  return (
    <>
      <Title headingLevel="h1" size="2xl">Operations</Title>
      <TextContent style={{ marginBottom: 16 }}>
        <Text>Select a connection and run operations against it.</Text>
      </TextContent>

      {connections.length === 0 && (
        <Alert variant="info" isInline title="No connections configured. Add connections first." />
      )}

      {connections.filter(c => c.role === 'source').length > 0 && (
        <>
          <Title headingLevel="h2" size="lg" style={{ marginBottom: 8 }}>Sources</Title>
          <Flex style={{ marginBottom: 16 }}>
            {connections.filter(c => c.role === 'source').map(conn => (
              <FlexItem key={conn.id}>
                <Button
                  variant={selectedId === conn.id ? 'primary' : 'secondary'}
                  onClick={() => setSelectedId(conn.id)}
                >
                  <Split hasGutter>
                    <SplitItem>{conn.name}</SplitItem>
                    <SplitItem>
                      <Label color={conn.type === 'awx' ? 'blue' : 'purple'} isCompact>
                        {conn.type.toUpperCase()}
                      </Label>
                    </SplitItem>
                  </Split>
                </Button>
              </FlexItem>
            ))}
          </Flex>
        </>
      )}

      {connections.filter(c => c.role === 'destination').length > 0 && (
        <>
          <Title headingLevel="h2" size="lg" style={{ marginBottom: 8 }}>Destinations</Title>
          <Flex style={{ marginBottom: 16 }}>
            {connections.filter(c => c.role === 'destination').map(conn => (
              <FlexItem key={conn.id}>
                <Button
                  variant={selectedId === conn.id ? 'primary' : 'secondary'}
                  onClick={() => setSelectedId(conn.id)}
                >
                  <Split hasGutter>
                    <SplitItem>{conn.name}</SplitItem>
                    <SplitItem>
                      <Label color={conn.type === 'awx' ? 'blue' : 'purple'} isCompact>
                        {conn.type.toUpperCase()}
                      </Label>
                    </SplitItem>
                  </Split>
                </Button>
              </FlexItem>
            ))}
          </Flex>
        </>
      )}

      {error && (
        <Alert variant="danger" isInline title={error} style={{ marginBottom: 16 }} />
      )}

      {selected && selected.ping_status === 'error' && (
        <Alert
          variant="warning"
          isInline
          title={`Connection "${selected.name}" is unreachable${selected.ping_error ? ': ' + selected.ping_error : ''}`}
          style={{ marginBottom: 16 }}
        />
      )}

      {selected && selected.auth_status === 'error' && (
        <Alert
          variant="warning"
          isInline
          title={`Connection "${selected.name}" authentication failed${selected.auth_error ? ': ' + selected.auth_error : ''}`}
          style={{ marginBottom: 16 }}
        />
      )}

      {selected && selected.role === 'source' && (
        <Alert
          variant="info"
          isInline
          title={`Cleanup is disabled for source connection "${selected.name}" to avoid deleting data from the platform you are migrating from.`}
          style={{ marginBottom: 16 }}
        />
      )}

      {selected && (
        <Card>
          <CardHeader>
            <CardTitle>
              <Split hasGutter>
                <SplitItem>{selected.name}</SplitItem>
                <SplitItem>
                  <Label color={selected.type === 'awx' ? 'blue' : 'purple'}>{selected.type.toUpperCase()}</Label>
                </SplitItem>
                <SplitItem>
                  <Label isCompact>{selected.url}</Label>
                </SplitItem>
              </Split>
            </CardTitle>
          </CardHeader>
          <CardBody>
            <Flex>
              <FlexItem>
                <Button variant="secondary" onClick={() => navigate(`/browse?conn=${selected.id}`)}>Browse</Button>
              </FlexItem>
              <FlexItem>
                <Button
                  variant="secondary"
                  onClick={() => handleOperation(selected.id, 'export')}
                  isDisabled={runningOperation !== null}
                  isLoading={runningOperation === `${selected.id}:export`}
                >
                  Export
                </Button>
              </FlexItem>
              <FlexItem>
                <Button
                  variant="warning"
                  onClick={() => handleOperation(selected.id, 'cleanup')}
                  isDisabled={selected.role !== 'destination' || runningOperation !== null}
                  isLoading={runningOperation === `${selected.id}:cleanup`}
                >
                  Cleanup
                </Button>
              </FlexItem>
            </Flex>
          </CardBody>
        </Card>
      )}

      {activeJobs.map(job => (
        <div key={job.id} style={{ marginTop: 24 }}>
          <Split hasGutter>
            <SplitItem isFilled>
              <Title headingLevel="h3">
                {job.connName} — {job.operation}
              </Title>
            </SplitItem>
            <SplitItem>
              <Button variant="plain" aria-label="Dismiss" onClick={() => dismissJob(job.id)}>
                <TimesIcon />
              </Button>
            </SplitItem>
          </Split>
          <LogViewer jobId={job.id} />
        </div>
      ))}
    </>
  );
}
