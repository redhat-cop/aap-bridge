import { useState, useEffect } from 'react';
import {
  Alert,
  Label,
  ExpandableSection,
} from '@patternfly/react-core';
import { api } from '../api/client';
import type { MigrationPreviewData, DefaultExclusions } from '../types/resources';

const resourceTypeLabels: Record<string, string> = {
  organizations: 'Organizations',
  teams: 'Teams',
  users: 'Users',
  credential_types: 'Credential Types',
  credentials: 'Credentials',
  projects: 'Projects',
  inventories: 'Inventories',
  hosts: 'Hosts',
  groups: 'Groups',
  job_templates: 'Job Templates',
  workflow_job_templates: 'Workflow Job Templates',
  schedules: 'Schedules',
};

const displayOrder = [
  'organizations', 'teams', 'users', 'credential_types', 'credentials',
  'projects', 'inventories', 'hosts', 'groups',
  'job_templates', 'workflow_job_templates', 'schedules',
];

interface Props {
  preview: MigrationPreviewData;
}

export function MigrationPreview({ preview }: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [defaultExclusions, setDefaultExclusions] = useState<DefaultExclusions | null>(null);
  const [exclusionsExpanded, setExclusionsExpanded] = useState(false);

  useEffect(() => {
    api.getExclusions().then(data => setDefaultExclusions(data as DefaultExclusions)).catch(() => {});
  }, []);

  let createCount = 0;
  let skipCount = 0;
  for (const summary of Object.values(preview.resource_summaries || {})) {
    createCount += summary.create;
    skipCount += summary.skip_exists;
  }

  const toggleExpanded = (type: string) => {
    setExpanded(prev => ({ ...prev, [type]: !prev[type] }));
  };

  const orderedTypes = displayOrder.filter(t => preview.resources[t]?.length > 0);

  return (
    <div>
      <Alert
        variant="info"
        isInline
        title="Preview is an approximation. Counts may differ from actual migration results due to transform-time filtering, dependency resolution, and resources that already exist on the target."
        style={{ marginBottom: 12 }}
      />
      {preview.warnings?.map((w, i) => (
        <Alert key={i} variant="warning" isInline title={w} style={{ marginBottom: 8 }} />
      ))}

      <div style={{ margin: '16px 0', fontSize: '1.1em' }}>
        <strong>{createCount}</strong> to create, <strong>{skipCount}</strong> to skip (already exist)
      </div>

      {defaultExclusions && (
        <ExpandableSection
          toggleText="Default Exclusions (always filtered during export)"
          isExpanded={exclusionsExpanded}
          onToggle={() => setExclusionsExpanded(!exclusionsExpanded)}
          style={{ marginBottom: 16 }}
        >
          <div style={{ fontSize: '0.9em', padding: '8px 16px', background: '#f0f0f0', borderRadius: 4 }}>
            {Object.entries(defaultExclusions.migration).map(([type, names]) => (
              <div key={type} style={{ marginBottom: 4 }}>
                <strong>{resourceTypeLabels[type] || type}:</strong>{' '}
                {names.map((n, i) => (
                  <Label key={i} isCompact color="grey" style={{ marginRight: 4 }}>{n}</Label>
                ))}
              </div>
            ))}
          </div>
        </ExpandableSection>
      )}

      {orderedTypes.map(type => {
        const items = preview.resources[type];
        const summary = preview.resource_summaries?.[type];
        const creates = summary?.create ?? items.filter(i => i.action === 'create').length;
        const skips = summary?.skip_exists ?? (items.length - creates);
        const total = summary?.total ?? items.length;
        const label = resourceTypeLabels[type] || type;

        let hostInfo = '';
        if (type === 'inventories' && preview.host_counts) {
          const totalHosts = Object.values(preview.host_counts).reduce((a, b) => a + b, 0);
          const totalGroups = preview.group_counts ? Object.values(preview.group_counts).reduce((a, b) => a + b, 0) : 0;
          hostInfo = ` — ${totalHosts} hosts, ${totalGroups} groups total`;
        }

        return (
          <ExpandableSection
            key={type}
            toggleText={`${label} (${total}) — ${creates} create, ${skips} skip${hostInfo}`}
            isExpanded={expanded[type] || false}
            onToggle={() => toggleExpanded(type)}
          >
            {summary?.truncated && (
              <Alert
                variant="info"
                isInline
                title={`Showing the first ${summary.displayed} of ${summary.total} ${label.toLowerCase()} in preview.`}
                style={{ marginBottom: 8 }}
              />
            )}
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9em' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #d2d2d2', textAlign: 'left' }}>
                  <th style={{ padding: '4px 8px' }}>Name</th>
                  <th style={{ padding: '4px 8px' }}>Action</th>
                  <th style={{ padding: '4px 8px' }}>Source ID</th>
                  {type === 'inventories' && preview.host_counts && (
                    <th style={{ padding: '4px 8px' }}>Hosts / Groups</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {items.map((item, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #eee' }}>
                    <td style={{ padding: '4px 8px' }}>{item.name}</td>
                    <td style={{ padding: '4px 8px' }}>
                      <Label
                        color={item.action === 'create' ? 'green' : 'grey'}
                        isCompact
                      >
                        {item.action === 'create' ? 'Create' : 'Skip (exists)'}
                      </Label>
                    </td>
                    <td style={{ padding: '4px 8px' }}>{item.source_id}</td>
                    {type === 'inventories' && preview.host_counts && (
                      <td style={{ padding: '4px 8px' }}>
                        {preview.host_counts[item.name] ?? 0} / {preview.group_counts?.[item.name] ?? 0}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </ExpandableSection>
        );
      })}
    </div>
  );
}
