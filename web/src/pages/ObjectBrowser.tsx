import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Title,
  TextContent,
  Text,
  FormSelect,
  FormSelectOption,
  FormGroup,
  Form,
  Alert,
  Spinner,
} from '@patternfly/react-core';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { ResourceTable } from '../components/ResourceTable';
import type { Connection } from '../types/connection';
import type { ResourceType } from '../types/resources';

export function ObjectBrowser() {
  const [searchParams] = useSearchParams();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [selectedConn, setSelectedConn] = useState(searchParams.get('conn') || '');
  const [resourceTypes, setResourceTypes] = useState<ResourceType[]>([]);
  const [selectedType, setSelectedType] = useState('');
  const [resources, setResources] = useState<Record<string, unknown>[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [search, setSearch] = useState('');
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const typeRequestIdRef = useRef(0);
  const resourceRequestIdRef = useRef(0);

  useEffect(() => {
    api.listConnections().then(c => setConnections(c as Connection[]));
  }, []);

  useEffect(() => {
    if (!selectedConn) return;
    typeRequestIdRef.current += 1;
    const requestId = typeRequestIdRef.current;
    setLoadError('');
    setLoading(false);
    void api.listResourceTypes(selectedConn).then(rt => {
      if (requestId !== typeRequestIdRef.current) return;
      const types = rt as ResourceType[];
      setResourceTypes(types);
      setSelectedType(types.length > 0 ? types[0].name : '');
      if (types.length === 0) {
        setLoading(false);
      }
    }).catch(err => {
      if (requestId !== typeRequestIdRef.current) return;
      setResourceTypes([]);
      setSelectedType('');
      setResources([]);
      setLoading(false);
      setLoadError(err instanceof Error ? err.message : String(err));
    });
  }, [selectedConn]);

  const loadResources = useCallback(async () => {
    if (!selectedConn || !selectedType) return;
    resourceRequestIdRef.current += 1;
    const requestId = resourceRequestIdRef.current;
    setLoading(true);
    setLoadError('');
    try {
      const res = await api.listResources(selectedConn, selectedType, {
        page,
        pageSize,
        search,
      });
      if (requestId !== resourceRequestIdRef.current) return;
      setResources((res.results || []) as Record<string, unknown>[]);
      setTotalCount(res.count || 0);
    } catch (err) {
      if (requestId !== resourceRequestIdRef.current) return;
      setResources([]);
      setTotalCount(0);
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      if (requestId === resourceRequestIdRef.current) {
        setLoading(false);
      }
    }
  }, [page, pageSize, search, selectedConn, selectedType]);

  useEffect(() => { loadResources(); }, [loadResources]);

  return (
    <>
      <Title headingLevel="h1" size="2xl">Object Browser</Title>
      <Form isHorizontal onSubmit={(e) => e.preventDefault()} style={{ marginBottom: 16, maxWidth: 600, marginTop: 8 }}>
        <FormGroup label="Connection" fieldId="conn-select">
          <FormSelect
            id="conn-select"
            value={selectedConn}
            onChange={(_e, v) => {
              setSelectedConn(v);
              setSelectedType('');
              setResourceTypes([]);
              setResources([]);
              setLoading(false);
              setPage(1);
              setSearch('');
              setTotalCount(0);
            }}
          >
            <FormSelectOption value="" label="-- Select connection --" isDisabled />
            {connections.map(c => (
              <FormSelectOption key={c.id} value={c.id} label={`${c.name} (${c.type.toUpperCase()})`} />
            ))}
          </FormSelect>
        </FormGroup>
        {resourceTypes.length > 0 && (
          <FormGroup label="Resource Type" fieldId="type-select">
            <FormSelect
              id="type-select"
              value={selectedType}
              onChange={(_e, v) => {
                setSelectedType(v);
                setPage(1);
                setSearch('');
              }}
            >
              {resourceTypes.map(rt => (
                <FormSelectOption key={rt.name} value={rt.name} label={rt.label} />
              ))}
            </FormSelect>
          </FormGroup>
        )}
      </Form>

      {loading && <Spinner size="lg" />}

      {!loading && loadError && (
        <Alert variant="danger" isInline title={loadError} style={{ marginBottom: 16 }} />
      )}

      {!loading && selectedConn && selectedType && !loadError && (
        <ResourceTable
          resources={resources}
          totalCount={totalCount}
          page={page}
          pageSize={pageSize}
          search={search}
          onSearchChange={(value) => {
            setSearch(value);
            setPage(1);
          }}
          onPageChange={(nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          }}
        />
      )}

      {!loading && !loadError && selectedConn && selectedType && resources.length === 0 && (
        <Alert variant="info" isInline title="No resources found for this type." />
      )}
    </>
  );
}
