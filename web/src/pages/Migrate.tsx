import { useState, useEffect, useCallback } from 'react';
import {
  Button,
  Title,
  TextContent,
  Text,
  Alert,
  Flex,
  FlexItem,
  Card,
  CardBody,
  CardHeader,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Checkbox,
  Grid,
  GridItem,
  Label,
  Tooltip,
} from '@patternfly/react-core';
import QuestionCircleIcon from '@patternfly/react-icons/dist/esm/icons/question-circle-icon';
import { api } from '../api/client';
import { LogViewer } from '../components/LogViewer';
import { MigrationPreview } from '../components/MigrationPreview';
import type { Connection } from '../types/connection';
import type { MigrationPreviewData } from '../types/resources';

type RunningAction =
  | 'cleanup' | 'prep'
  | 'export' | 'transform' | 'import1'
  | 'pipeline'
  | 'import2'
  | 'preview'
  | null;

const FULL_CLEANUP_HELP =
  'Clears migration state, deletes migrated resources on the selected destination, '
  + 'cancels active jobs on that destination, and removes local exports/ and xformed/ '
  + 'files. Use before re-running a full migration to the same destination.';

const CLEAR_STATE_HELP =
  'Clears migration state tables and local exports/ and xformed/ files for all '
  + 'configured source/destination pairs. Does not delete resources on any AAP instance. '
  + 'Use when switching pairs or forcing the next import to re-create resources '
  + 'instead of skipping previously migrated ones.';

function CleanupInfo({ content }: { content: string }) {
  return (
    <Tooltip content={<div style={{ maxWidth: 300 }}>{content}</div>}>
      <button
        type="button"
        aria-label="More information"
        style={{
          background: 'none',
          border: 'none',
          padding: 0,
          cursor: 'help',
          display: 'inline-flex',
          color: 'var(--pf-v5-global--icon--Color--light--dark, #6a6e73)',
        }}
      >
        <QuestionCircleIcon />
      </button>
    </Tooltip>
  );
}

export function Migrate() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [sourceId, setSourceId] = useState('');
  const [destId, setDestId] = useState('');
  const [activeJobId, setActiveJobId] = useState('');
  const [runningAction, setRunningAction] = useState<RunningAction>(null);
  const [pipelinePhaseLabel, setPipelinePhaseLabel] = useState('');
  const [error, setError] = useState('');
  const [statusMsg, setStatusMsg] = useState('');
  const [previewData, setPreviewData] = useState<MigrationPreviewData | null>(null);
  const [previewJobId, setPreviewJobId] = useState('');
  const [prepForce, setPrepForce] = useState(false);
  const [clearStateMsg, setClearStateMsg] = useState('');
  const [clearStateBusy, setClearStateBusy] = useState(false);

  const loadConnections = useCallback(async () => {
    const conns = await api.listConnections() as Connection[];
    setConnections(conns);
  }, []);

  useEffect(() => { loadConnections(); }, [loadConnections]);

  const pairSelected = Boolean(sourceId && destId && sourceId !== destId);
  const busy = runningAction !== null || clearStateBusy;

  // Poll a job until it completes or fails; resolves/rejects accordingly.
  const waitForJob = useCallback((jobId: string): Promise<void> =>
    new Promise((resolve, reject) => {
      const poll = (attempt = 0) => {
        void (api.getJob(jobId) as Promise<{ status: string; error?: string }>)
          .then(job => {
            if (job.status === 'completed') { resolve(); return; }
            if (job.status === 'failed' || job.status === 'cancelled') {
              reject(new Error(job.error || job.status));
              return;
            }
            if (attempt < 600) setTimeout(() => poll(attempt + 1), 2000);
            else reject(new Error('Job timed out'));
          })
          .catch(err => {
            if (attempt < 600) setTimeout(() => poll(attempt + 1), 2000);
            else reject(err instanceof Error ? err : new Error(String(err)));
          });
      };
      setTimeout(() => poll(), 1500);
    }), []);

  const runAction = async (action: Exclude<RunningAction, 'pipeline' | 'preview' | null>) => {
    if (!pairSelected || busy) return;
    setError(''); setStatusMsg(''); setPreviewData(null);
    setRunningAction(action);
    try {
      let result: { job_id: string };
      switch (action) {
        case 'cleanup':   result = await api.migrationCleanup(sourceId, destId); break;
        case 'prep':      result = await api.migrationPrep(sourceId, destId, prepForce); break;
        case 'export':    result = await api.migrationExport(sourceId, destId); break;
        case 'transform': result = await api.migrationTransform(sourceId, destId); break;
        case 'import1':   result = await api.migrationImport(sourceId, destId, 'phase1'); break;
        case 'import2':   result = await api.migrationImport(sourceId, destId, 'phase2'); break;
      }
      setActiveJobId(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setRunningAction(null);
    }
  };

  const runClearState = async () => {
    if (busy) return;
    setError('');
    setStatusMsg('');
    setClearStateMsg('');
    setClearStateBusy(true);
    try {
      const result = await api.clearMigrationState();
      const dirs = result.directories_cleared.length > 0
        ? ` Cleared local ${result.directories_cleared.join(' and ')} directories.`
        : '';
      setClearStateMsg(
        `Cleared ${result.cleared_progress} progress records and ${result.deleted_mappings} ID mappings.${dirs}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setClearStateBusy(false);
    }
  };

  const runPipeline = async () => {
    if (!pairSelected || busy) return;
    setError(''); setStatusMsg(''); setPreviewData(null);
    setRunningAction('pipeline');

    const steps: Array<{ label: string; fn: () => Promise<{ job_id: string }> }> = [
      { label: '2. Export (All)',              fn: () => api.migrationExport(sourceId, destId) },
      { label: '3. Transform (All)',           fn: () => api.migrationTransform(sourceId, destId) },
      { label: '4. Import Phase 1',            fn: () => api.migrationImport(sourceId, destId, 'phase1') },
    ];

    let lastLabel = '';
    try {
      for (const step of steps) {
        lastLabel = step.label;
        setPipelinePhaseLabel(step.label);
        const { job_id } = await step.fn();
        setActiveJobId(job_id);
        await waitForJob(job_id);
      }
      setStatusMsg('Pipeline completed: Export → Transform → Import Phase 1');
    } catch (err) {
      setError(`Pipeline failed at ${lastLabel}: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setRunningAction(null);
      setPipelinePhaseLabel('');
    }
  };

  const runPreview = async () => {
    if (!pairSelected || busy) return;
    setError(''); setStatusMsg(''); setPreviewData(null);
    setRunningAction('preview');
    try {
      const result = await api.migrationPreview(sourceId, destId);
      setActiveJobId(result.job_id);
      setPreviewJobId(result.job_id);
      pollPreview(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setRunningAction(null);
    }
  };

  const pollPreview = (jobId: string) => {
    const poll = async (attempt = 0) => {
      try {
        const resp = await api.getMigrationPreview(jobId) as MigrationPreviewData;
        setPreviewData(resp);
        setRunningAction(null);
        setStatusMsg('Preview complete.');
      } catch {
        try {
          const job = await api.getJob(jobId) as { status: string; error?: string };
          if (job.status === 'failed') { setError(job.error || 'Preview failed'); setRunningAction(null); return; }
          if (job.status === 'completed') { setRunningAction(null); return; }
          if (attempt < 600) setTimeout(() => { void poll(attempt + 1); }, 1500);
          else { setError('Preview timed out'); setRunningAction(null); }
        } catch (jobErr) {
          if (attempt < 600) setTimeout(() => { void poll(attempt + 1); }, 1500);
          else { setError(jobErr instanceof Error ? jobErr.message : 'Preview failed'); setRunningAction(null); }
        }
      }
    };
    setTimeout(() => { void poll(); }, 2000);
  };

  const handleJobClose = (status: string) => {
    // Pipeline manages its own state via waitForJob — don't reset here.
    if (runningAction === 'pipeline') return;
    setRunningAction(null);
    if (status === 'completed') setStatusMsg('Job completed successfully.');
    else if (status === 'failed') setError('Job failed. See log for details.');
    else if (status === 'cancelled') setStatusMsg('Job cancelled.');
  };

  const sources = connections.filter(c => c.role === 'source');
  const destinations = connections.filter(c => c.role === 'destination');

  const btnStyle = { justifyContent: 'flex-start', width: '100%' };

  return (
    <>
      <Title headingLevel="h1" size="2xl">Migrate</Title>
      <TextContent style={{ marginBottom: 16 }}>
        <Text>
          Select source and destination, then run <strong>1. Prep Phase</strong> first to
          discover endpoints and collect schemas. Once prep is complete, run the remaining
          phases individually or use the pipeline to run Export → Transform → Import Phase 1
          in one step.
        </Text>
      </TextContent>

      {connections.length < 2 && (
        <Alert variant="info" isInline title="You need at least 2 connections configured." style={{ marginBottom: 16 }} />
      )}

      {/* Connection selectors */}
      <Card style={{ marginBottom: 16, maxWidth: 800 }}>
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
                  {sources.map(c => (
                    <FormSelectOption key={c.id} value={c.id} isDisabled={c.id === destId}
                      label={`${c.name} (v${c.version || '?'}) — ${c.url}`} />
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
                  <FormSelectOption key="" value="" label="-- Select destination --" isDisabled />
                  {destinations.map(c => (
                    <FormSelectOption key={c.id} value={c.id} isDisabled={c.id === sourceId}
                      label={`${c.name} (v${c.version || '?'}) — ${c.url}`} />
                  ))}
                </FormSelect>
              </FormGroup>
            </FlexItem>
            {sourceId && destId && sourceId === destId && (
              <FlexItem>
                <Alert variant="danger" isInline title="Source and destination cannot be the same connection." />
              </FlexItem>
            )}
          </Flex>
        </CardBody>
      </Card>

      {/* Preview Migration */}
      <Card style={{ marginBottom: 16, maxWidth: 800 }}>
        <CardBody>
          <Button
            variant="secondary"
            onClick={() => { void runPreview(); }}
            isDisabled={!pairSelected || busy}
            isLoading={runningAction === 'preview'}
          >
            Preview Migration
          </Button>
        </CardBody>
      </Card>

      {/* Migration */}
      <Card style={{ marginBottom: 16, maxWidth: 800 }}>
        <CardBody>
          <Grid hasGutter>

            {/* Row 1: Cleanup options */}
            <GridItem span={12}>
              <Card isPlain style={{ border: '1px solid var(--pf-v5-global--BorderColor--100, #d2d2d2)' }}>
                <CardHeader>
                  <Title headingLevel="h4" size="md">Cleanup</Title>
                </CardHeader>
                <CardBody>
                  <Grid hasGutter>
                    <GridItem span={6}>
                      <Flex alignItems={{ default: 'alignItemsCenter' }} spaceItems={{ default: 'spaceItemsSm' }}>
                        <Button
                          variant="warning"
                          onClick={() => { void runAction('cleanup'); }}
                          isDisabled={!pairSelected || busy}
                          isLoading={runningAction === 'cleanup'}
                        >
                          0. Full Cleanup
                        </Button>
                        <CleanupInfo content={FULL_CLEANUP_HELP} />
                      </Flex>
                    </GridItem>
                    <GridItem span={6}>
                      <Flex alignItems={{ default: 'alignItemsCenter' }} spaceItems={{ default: 'spaceItemsSm' }}>
                        <Button
                          variant="secondary"
                          onClick={() => { void runClearState(); }}
                          isDisabled={busy}
                          isLoading={clearStateBusy}
                        >
                          Clear Migration State Only
                        </Button>
                        <CleanupInfo content={CLEAR_STATE_HELP} />
                      </Flex>
                    </GridItem>
                  </Grid>
                  {clearStateMsg && (
                    <Alert variant="success" isInline title={clearStateMsg} style={{ marginTop: 16 }} />
                  )}
                </CardBody>
              </Card>
            </GridItem>

            {/* Row 2: Prep — full width */}
            <GridItem span={12}>
              <Flex direction={{ default: 'column' }} spaceItems={{ default: 'spaceItemsSm' }}>
                <FlexItem>
                  <Button
                    variant="secondary"
                    onClick={() => { void runAction('prep'); }}
                    isDisabled={!pairSelected || busy}
                    isLoading={runningAction === 'prep'}
                    style={btnStyle}
                  >
                    1. Prep Phase (Discover &amp; Schema)
                  </Button>
                </FlexItem>
                <FlexItem>
                  <Checkbox
                    id="prep-force"
                    label="Force schema re-collection (even if schemas already exist)"
                    isChecked={prepForce}
                    onChange={(_e, checked) => setPrepForce(checked)}
                    isDisabled={!pairSelected || busy}
                  />
                </FlexItem>
              </Flex>
            </GridItem>

            {/* Row 3: Left = individual 2/3/4, Right = pipeline */}
            <GridItem span={6}>
              <Card isPlain style={{ height: '100%', border: '1px solid var(--pf-v5-global--BorderColor--100, #d2d2d2)' }}>
                <CardHeader>
                  <Title headingLevel="h4" size="md">Run individually</Title>
                </CardHeader>
                <CardBody>
                  <Flex direction={{ default: 'column' }} spaceItems={{ default: 'spaceItemsSm' }}>
                    <FlexItem>
                      <Button
                        variant="secondary"
                        onClick={() => { void runAction('export'); }}
                        isDisabled={!pairSelected || busy}
                        isLoading={runningAction === 'export'}
                        style={btnStyle}
                      >
                        2. Export (All)
                      </Button>
                    </FlexItem>
                    <FlexItem>
                      <Button
                        variant="secondary"
                        onClick={() => { void runAction('transform'); }}
                        isDisabled={!pairSelected || busy}
                        isLoading={runningAction === 'transform'}
                        style={btnStyle}
                      >
                        3. Transform (All)
                      </Button>
                    </FlexItem>
                    <FlexItem>
                      <Button
                        variant="secondary"
                        onClick={() => { void runAction('import1'); }}
                        isDisabled={!pairSelected || busy}
                        isLoading={runningAction === 'import1'}
                        style={btnStyle}
                      >
                        4. Import Phase 1 (Base Resources)
                      </Button>
                    </FlexItem>
                  </Flex>
                </CardBody>
              </Card>
            </GridItem>

            <GridItem span={6}>
              <Card isPlain style={{ height: '100%', border: '1px solid var(--pf-v5-global--BorderColor--100, #d2d2d2)' }}>
                <CardHeader>
                  <Title headingLevel="h4" size="md">Run together</Title>
                </CardHeader>
                <CardBody>
                  <TextContent style={{ marginBottom: 16 }}>
                    <Text>
                      Runs Export → Transform → Import Phase 1 sequentially.
                      Each phase streams its log below as it runs.
                    </Text>
                  </TextContent>
                  <Button
                    variant="primary"
                    onClick={() => { void runPipeline(); }}
                    isDisabled={!pairSelected || busy}
                    isLoading={runningAction === 'pipeline'}
                    style={btnStyle}
                  >
                    ▶ Run Pipeline (2 → 3 → 4)
                  </Button>
                  {pipelinePhaseLabel && (
                    <Flex style={{ marginTop: 12 }} spaceItems={{ default: 'spaceItemsSm' }}>
                      <FlexItem>
                        <Label color="blue" isCompact>Running</Label>
                      </FlexItem>
                      <FlexItem>{pipelinePhaseLabel}</FlexItem>
                    </Flex>
                  )}
                </CardBody>
              </Card>
            </GridItem>

            {/* Row 4: Import Phase 2 — full width */}
            <GridItem span={12}>
              <Alert
                variant="info"
                isInline
                title="Before running Phase 2: ensure credentials have been entered into the target AAP."
                style={{ marginBottom: 8 }}
              />
              <Button
                variant="secondary"
                onClick={() => { void runAction('import2'); }}
                isDisabled={!pairSelected || busy}
                isLoading={runningAction === 'import2'}
                style={btnStyle}
              >
                5. Import Phase 2 (Patch Projects + Automation)
              </Button>
            </GridItem>

          </Grid>

        </CardBody>
      </Card>

      {error && <Alert variant="danger" isInline title={error} style={{ marginBottom: 16 }} />}
      {statusMsg && <Alert variant="success" isInline title={statusMsg} style={{ marginBottom: 16 }} />}

      {activeJobId && (
        <div style={{ marginBottom: 16 }}>
          <Title headingLevel="h3" style={{ marginBottom: 8 }}>
            Job Log
            {runningAction === 'pipeline' && pipelinePhaseLabel && (
              <Label color="blue" isCompact style={{ marginLeft: 12, verticalAlign: 'middle' }}>
                {pipelinePhaseLabel}
              </Label>
            )}
          </Title>
          <LogViewer jobId={activeJobId} onClose={handleJobClose} />
        </div>
      )}

      {previewData && previewJobId && (
        <div style={{ marginBottom: 16 }}>
          <Title headingLevel="h3" style={{ marginBottom: 8 }}>Preview Results</Title>
          <MigrationPreview preview={previewData} />
        </div>
      )}
    </>
  );
}
