import { useState, useEffect, useCallback, useRef } from 'react';
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
  FormGroup,
  FormSelect,
  FormSelectOption,
} from '@patternfly/react-core';
import TimesIcon from '@patternfly/react-icons/dist/esm/icons/times-icon';
import { api } from '../api/client';
import { LogViewer } from '../components/LogViewer';
import { MigrationPreview } from '../components/MigrationPreview';
import type { Connection } from '../types/connection';
import type { MigrationPreviewData } from '../types/resources';

type Step = 'select' | 'preview' | 'run';

export function Migrate() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [sourceId, setSourceId] = useState('');
  const [destId, setDestId] = useState('');
  const [step, setStep] = useState<Step>('select');
  const [previewJobId, setPreviewJobId] = useState('');
  const [runJobId, setRunJobId] = useState('');
  const [previewData, setPreviewData] = useState<MigrationPreviewData | null>(null);
  const [previewError, setPreviewError] = useState('');
  const [loading, setLoading] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [migrationDone, setMigrationDone] = useState(false);
  const [runError, setRunError] = useState('');
  const [clearMsg, setClearMsg] = useState('');
  const [clearVariant, setClearVariant] = useState<'success' | 'danger'>('success');
  const [clearingState, setClearingState] = useState(false);
  const activePreviewJobId = useRef('');
  const MAX_PREVIEW_POLL_ATTEMPTS = 600;

  const loadConnections = useCallback(async () => {
    const conns = await api.listConnections() as Connection[];
    setConnections(conns);
  }, []);

  useEffect(() => { loadConnections(); }, [loadConnections]);

  const handlePreview = async () => {
    if (!sourceId || !destId) return;
    if (sourceId === destId) return;

    activePreviewJobId.current = '';
    setLoading(true);
    setPreviewData(null);
    setPreviewError('');

    try {
      const result = await api.migrationPreview(sourceId, destId);
      activePreviewJobId.current = result.job_id;
      setPreviewJobId(result.job_id);
      setStep('preview');
      pollPreview(result.job_id);
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const pollPreview = async (jobId: string) => {
    const poll = async (attempt = 0) => {
      try {
        const resp = await api.getMigrationPreview(jobId) as MigrationPreviewData;
        if (activePreviewJobId.current !== jobId) return;
        setPreviewData(resp);
      } catch (err) {
        try {
          const job = await api.getJob(jobId) as { status: string; error?: string };
          if (job.status === 'failed') {
            if (activePreviewJobId.current !== jobId) return;
            setPreviewError(job.error || 'Preview failed');
            return;
          }
          if (job.status === 'cancelled') {
            if (activePreviewJobId.current !== jobId) return;
            setPreviewError(job.error || 'Preview cancelled');
            return;
          }
          if (attempt >= MAX_PREVIEW_POLL_ATTEMPTS) {
            if (activePreviewJobId.current !== jobId) return;
            setPreviewError('Preview timed out before results were ready. The job may still be running.');
            return;
          }
          setTimeout(() => { void poll(attempt + 1); }, 1500);
        } catch (jobErr) {
          if (attempt >= MAX_PREVIEW_POLL_ATTEMPTS) {
            if (activePreviewJobId.current !== jobId) return;
            const message = jobErr instanceof Error
              ? jobErr.message
              : err instanceof Error
                ? err.message
                : 'Preview failed';
            setPreviewError(message);
            return;
          }
          setTimeout(() => { void poll(attempt + 1); }, 1500);
        }
      }
    };
    setTimeout(() => { void poll(); }, 2000);
  };

  const handleRun = async () => {
    if (!previewJobId) return;
    setLoading(true);
    setCancelling(false);
    setMigrationDone(false);
    setRunError('');
    try {
      const result = await api.migrationRun(sourceId, destId, previewJobId);
      setRunJobId(result.job_id);
      setStep('run');
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!runJobId || cancelling) return;
    setCancelling(true);
    try {
      await api.cancelJob(runJobId);
    } catch (err) {
      setCancelling(false);
      setRunError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleBack = () => {
    activePreviewJobId.current = '';
    setStep('select');
    setPreviewJobId('');
    setRunJobId('');
    setPreviewData(null);
    setPreviewError('');
    setRunError('');
    setCancelling(false);
    setMigrationDone(false);
  };

  const handleLogClose = (status: string) => {
    if (!['completed', 'failed', 'cancelled'].includes(status)) {
      return;
    }
    setMigrationDone(true);
    if (status === 'cancelled') {
      setCancelling(false);
    }
  };

  const sourceConn = connections.find(c => c.id === sourceId);
  const destConn = connections.find(c => c.id === destId);

  return (
    <>
      <Title headingLevel="h1" size="2xl">Migrate</Title>
      <TextContent style={{ marginBottom: 16 }}>
        <Text>Migrate resources from a source AWX/AAP platform to a destination AAP platform.</Text>
      </TextContent>

      {connections.length < 2 && (
        <Alert variant="info" isInline title="You need at least 2 connections configured to perform a migration." />
      )}

      {clearMsg && (
        <Alert variant={clearVariant} isInline title={clearMsg} style={{ marginBottom: 16 }} />
      )}

      {step === 'select' && (
        <Card>
          <CardBody>
            <Flex direction={{ default: 'column' }} spaceItems={{ default: 'spaceItemsMd' }}>
              <FlexItem>
                <FormGroup label="Source" fieldId="source-select">
                  <FormSelect
                    id="source-select"
                    value={sourceId}
                    onChange={(_e, val) => setSourceId(val)}
                    aria-label="Select source connection"
                  >
                    <FormSelectOption key="" value="" label="-- Select source --" isDisabled />
                    {connections.filter(c => c.role === 'source').map(c => (
                      <FormSelectOption
                        key={c.id}
                        value={c.id}
                        label={`${c.name} (${c.type.toUpperCase()} — ${c.url})`}
                        isDisabled={c.id === destId}
                      />
                    ))}
                  </FormSelect>
                </FormGroup>
              </FlexItem>
              <FlexItem>
                <FormGroup label="Destination" fieldId="dest-select">
                  <FormSelect
                    id="dest-select"
                    value={destId}
                    onChange={(_e, val) => setDestId(val)}
                    aria-label="Select destination connection"
                  >
                    <FormSelectOption key="" value="" label="-- Select destination (AAP only) --" isDisabled />
                    {connections.filter(c => c.type === 'aap' && c.role === 'destination').map(c => (
                      <FormSelectOption
                        key={c.id}
                        value={c.id}
                        label={`${c.name} (${c.type.toUpperCase()} — ${c.url})`}
                        isDisabled={c.id === sourceId}
                      />
                    ))}
                  </FormSelect>
                </FormGroup>
              </FlexItem>
              {sourceId && destId && sourceId === destId && (
                <FlexItem>
                  <Alert variant="danger" isInline title="Source and destination cannot be the same connection." />
                </FlexItem>
              )}
              {previewError && (
                <FlexItem>
                  <Alert variant="danger" isInline title={previewError} />
                </FlexItem>
              )}
              <FlexItem>
                <Flex spaceItems={{ default: 'spaceItemsMd' }}>
                  <FlexItem>
                    <Button
                      variant="primary"
                      onClick={handlePreview}
                      isDisabled={!sourceId || !destId || sourceId === destId || loading}
                      isLoading={loading}
                    >
                      Preview Migration
                    </Button>
                  </FlexItem>
                  <FlexItem>
                    <Button
                      variant="warning"
                      onClick={async () => {
                        if (clearingState) return;
                        const confirmed = window.confirm(
                          'Clear saved migration progress and ID mappings? This cannot be undone.'
                        );
                        if (!confirmed) return;
                        setClearMsg('');
                        setClearingState(true);
                        try {
                          const result = await api.clearMigrationState();
                          setClearVariant('success');
                          setClearMsg(`Cleared ${result.cleared_progress} progress records and ${result.deleted_mappings} ID mappings`);
                        } catch (err) {
                          setClearVariant('danger');
                          setClearMsg(`Error: ${err instanceof Error ? err.message : String(err)}`);
                        } finally {
                          setClearingState(false);
                        }
                      }}
                      isDisabled={clearingState}
                      isLoading={clearingState}
                    >
                      {clearingState ? 'Clearing...' : 'Clear Migration State'}
                    </Button>
                  </FlexItem>
                </Flex>
              </FlexItem>
            </Flex>
          </CardBody>
        </Card>
      )}

      {step === 'preview' && (
        <>
          <Card style={{ marginBottom: 16 }}>
            <CardBody>
              <Split hasGutter>
                <SplitItem>
                  <Label color="blue" isCompact>Source</Label>{' '}
                  {sourceConn?.name} ({sourceConn?.type.toUpperCase()})
                </SplitItem>
                <SplitItem>&rarr;</SplitItem>
                <SplitItem>
                  <Label color="purple" isCompact>Destination</Label>{' '}
                  {destConn?.name} ({destConn?.type.toUpperCase()})
                </SplitItem>
              </Split>
            </CardBody>
          </Card>

          {previewJobId && (
            <div style={{ marginBottom: 16 }}>
              <Split hasGutter>
                <SplitItem isFilled>
                  <Title headingLevel="h3">Preview Log</Title>
                </SplitItem>
              </Split>
              <LogViewer jobId={previewJobId} />
            </div>
          )}

          {previewError && (
            <Alert variant="danger" isInline title={previewError} style={{ marginBottom: 16 }} />
          )}

          {previewData && (
            <div style={{ marginBottom: 16 }}>
              <Title headingLevel="h3" style={{ marginBottom: 8 }}>Preview Results</Title>
              <MigrationPreview preview={previewData} />
            </div>
          )}

          <Flex>
            <FlexItem>
              <Button variant="secondary" onClick={handleBack}>Back</Button>
            </FlexItem>
            {previewData && (
              <FlexItem>
                <Button
                  variant="primary"
                  onClick={handleRun}
                  isDisabled={loading}
                  isLoading={loading}
                >
                  Start Migration
                </Button>
              </FlexItem>
            )}
          </Flex>
        </>
      )}

      {step === 'run' && (
        <>
          <Card style={{ marginBottom: 16 }}>
            <CardBody>
              <Split hasGutter>
                <SplitItem>
                  <Label color="blue" isCompact>Source</Label>{' '}
                  {sourceConn?.name}
                </SplitItem>
                <SplitItem>&rarr;</SplitItem>
                <SplitItem>
                  <Label color="purple" isCompact>Destination</Label>{' '}
                  {destConn?.name}
                </SplitItem>
              </Split>
            </CardBody>
          </Card>

          {runJobId && (
            <div style={{ marginBottom: 16 }}>
              <Split hasGutter>
                <SplitItem isFilled>
                  <Title headingLevel="h3">Migration Log</Title>
                </SplitItem>
                <SplitItem>
                  {!migrationDone && (
                    <Button
                      variant="danger"
                      onClick={handleCancel}
                      isDisabled={cancelling}
                      isLoading={cancelling}
                    >
                      {cancelling ? 'Cancelling...' : 'Cancel Migration'}
                    </Button>
                  )}
                </SplitItem>
                <SplitItem>
                  <Button variant="plain" aria-label="Back" onClick={handleBack}>
                    <TimesIcon />
                  </Button>
                </SplitItem>
              </Split>
              <LogViewer jobId={runJobId} onClose={handleLogClose} />
            </div>
          )}

          {runError && (
            <Alert variant="danger" isInline title={runError} style={{ marginBottom: 16 }} />
          )}

          <Button variant="secondary" onClick={handleBack} style={{ marginTop: 16 }}>
            New Migration
          </Button>
        </>
      )}
    </>
  );
}
