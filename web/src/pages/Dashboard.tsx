import { useState, useEffect, useCallback } from 'react';
import {
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CardTitle,
  Title,
  TextContent,
  Text,
  Gallery,
  Label,
  Split,
  SplitItem,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  Alert,
} from '@patternfly/react-core';
import { Dropdown, DropdownItem, KebabToggle } from '@patternfly/react-core/deprecated';
import { api } from '../api/client';
import { ConnectionForm } from '../components/ConnectionForm';
import type { Connection, ConnectionPayload } from '../types/connection';

export function Dashboard() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editConn, setEditConn] = useState<Connection | null>(null);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);

  const loadConnections = useCallback(async () => {
    try {
      const conns = await api.listConnections() as Connection[];
      setConnections(conns);
    } catch (err) {
      console.error('Failed to load connections:', err);
    }
  }, []);

  useEffect(() => { loadConnections(); }, [loadConnections]);

  const handleSave = async (conn: ConnectionPayload) => {
    if (editConn) {
      await api.updateConnection(editConn.id, conn);
    } else {
      await api.createConnection(conn);
    }
    setShowForm(false);
    setEditConn(null);
    loadConnections();
  };

  const handleDelete = async (id: string) => {
    setConnections(prev => prev.filter(c => c.id !== id));
    try {
      await api.deleteConnection(id);
    } catch { /* already removed from UI */ }
    loadConnections();
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    setConnections(prev => prev.map(c =>
      c.id === id ? { ...c, ping_status: 'unknown', auth_status: 'unknown', ping_error: undefined, auth_error: undefined } : c
    ));
    try {
      await api.testConnection(id);
    } finally {
      setTesting(null);
      loadConnections();
    }
  };

  const dropdownItems = (conn: Connection) => [
    <DropdownItem key="edit" onClick={() => { setEditConn(conn); setShowForm(true); }}>Edit</DropdownItem>,
    <DropdownItem key="delete" onClick={() => handleDelete(conn.id)} style={{ color: '#c9190b' }}>Delete</DropdownItem>,
  ];

  const sources = connections.filter(c => c.role === 'source');
  const destinations = connections.filter(c => c.role === 'destination');

  const pingLabel = (conn: Connection) => {
    switch (conn.ping_status) {
      case 'ok': return <Label color="green" isCompact>Ping OK</Label>;
      case 'error': return <Label color="red" isCompact>Unreachable</Label>;
      default: return <Label color="grey" isCompact>Ping ?</Label>;
    }
  };

  const authLabel = (conn: Connection) => {
    switch (conn.auth_status) {
      case 'ok': return <Label color="green" isCompact>Auth OK</Label>;
      case 'error': return <Label color="red" isCompact>Auth Failed</Label>;
      default: return <Label color="grey" isCompact>Auth ?</Label>;
    }
  };

  const renderCard = (conn: Connection) => {
    return (
      <Card key={conn.id}>
        <CardHeader
          actions={{
            actions: (
              <Dropdown
                isOpen={openMenu === conn.id}
                onSelect={() => setOpenMenu(null)}
                toggle={<KebabToggle onToggle={(_e, open) => setOpenMenu(open ? conn.id : null)} />}
                isPlain
                dropdownItems={dropdownItems(conn)}
                position="right"
              />
            ),
          }}
        >
          <CardTitle>
            <Split hasGutter>
              <SplitItem>{conn.name}</SplitItem>
              <SplitItem>
                <Label color="purple">
                  AAP{conn.version ? ` v${conn.version}` : ''}
                </Label>
              </SplitItem>
              <SplitItem>{pingLabel(conn)}</SplitItem>
              <SplitItem>{authLabel(conn)}</SplitItem>
            </Split>
          </CardTitle>
        </CardHeader>
        <CardBody>
          <DescriptionList isHorizontal isCompact>
            <DescriptionListGroup>
              <DescriptionListTerm>URL</DescriptionListTerm>
              <DescriptionListDescription>{conn.url}</DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>Token</DescriptionListTerm>
              <DescriptionListDescription>{conn.token ? '********' : 'Not set'}</DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>SSL Verify</DescriptionListTerm>
              <DescriptionListDescription>{conn.verify_ssl ? 'On' : 'Off'}</DescriptionListDescription>
            </DescriptionListGroup>
          </DescriptionList>
          {conn.ping_status === 'error' && conn.ping_error && (
            <Alert variant="danger" isInline isPlain title={conn.ping_error} style={{ marginTop: 8 }} />
          )}
          {conn.auth_status === 'error' && conn.auth_error && (
            <Alert variant="danger" isInline isPlain title={conn.auth_error} style={{ marginTop: 8 }} />
          )}
        </CardBody>
        <CardFooter>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleTest(conn.id)}
            isLoading={testing === conn.id}
            isDisabled={testing === conn.id}
          >
            {testing === conn.id ? 'Testing...' : 'Test'}
          </Button>
        </CardFooter>
      </Card>
    );
  };

  return (
    <>
      <Title headingLevel="h1" size="2xl">Settings</Title>
      <TextContent style={{ marginBottom: 16 }}>
        <Text>Configure connections and application settings.</Text>
      </TextContent>

      <Title headingLevel="h2" size="xl" style={{ marginTop: 8, marginBottom: 8 }}>Connections</Title>
      <Button variant="primary" onClick={() => { setEditConn(null); setShowForm(true); }} style={{ marginBottom: 16 }}>
        Add Connection
      </Button>

      {connections.length === 0 && (
        <Alert variant="info" isInline title="No connections yet. Click 'Add Connection' to get started." />
      )}

      {sources.length > 0 && (
        <>
          <Title headingLevel="h2" size="xl" style={{ marginTop: 16, marginBottom: 8 }}>Sources</Title>
          <Gallery hasGutter minWidths={{ default: '350px' }}>
            {sources.map(conn => renderCard(conn))}
          </Gallery>
        </>
      )}

      {destinations.length > 0 && (
        <>
          <Title headingLevel="h2" size="xl" style={{ marginTop: 24, marginBottom: 8 }}>Destinations</Title>
          <Gallery hasGutter minWidths={{ default: '350px' }}>
            {destinations.map(conn => renderCard(conn))}
          </Gallery>
        </>
      )}

      <ConnectionForm
        key={editConn?.id || 'new'}
        isOpen={showForm}
        initial={editConn || undefined}
        onSave={handleSave}
        onClose={() => { setShowForm(false); setEditConn(null); }}
      />
    </>
  );
}
