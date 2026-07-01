import { useState, useMemo } from 'react';
import {
  SearchInput,
  Toolbar,
  ToolbarItem,
  ToolbarContent,
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';

interface Props {
  resources: Record<string, unknown>[];
}

export function ResourceTable({ resources }: Props) {
  const [filter, setFilter] = useState('');

  const columns = useMemo(() => {
    if (resources.length === 0) return [];
    const keys = Object.keys(resources[0]);
    const priority = ['id', 'name', 'username', 'description', 'type', 'status', 'organization', 'survey_enabled'];
    const sorted = priority.filter(k => keys.includes(k));
    const rest = keys.filter(k => !priority.includes(k) && typeof resources[0][k] !== 'object');
    return [...sorted, ...rest].slice(0, 8);
  }, [resources]);

  const filtered = useMemo(() => {
    if (!filter) return resources;
    const lower = filter.toLowerCase();
    return resources.filter(r => {
      const name = String(r['name'] || r['username'] || '').toLowerCase();
      return name.includes(lower);
    });
  }, [resources, filter]);

  return (
    <>
      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <SearchInput
              placeholder="Filter by name..."
              value={filter}
              onChange={(_e, v) => setFilter(v)}
              onClear={() => setFilter('')}
            />
          </ToolbarItem>
          <ToolbarItem align={{ default: 'alignRight' }}>
            {filtered.length} of {resources.length} items
          </ToolbarItem>
        </ToolbarContent>
      </Toolbar>
      <Table aria-label="Resources" variant="compact">
        <Thead>
          <Tr>
            {columns.map(col => (
              <Th key={col}>{col}</Th>
            ))}
          </Tr>
        </Thead>
        <Tbody>
          {filtered.map((res, i) => (
            <Tr key={i}>
              {columns.map(col => (
                <Td key={col}>{formatCell(res[col])}</Td>
              ))}
            </Tr>
          ))}
        </Tbody>
      </Table>
    </>
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
