import { useMemo } from 'react';
import {
  Pagination,
  SearchInput,
  Toolbar,
  ToolbarItem,
  ToolbarContent,
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';

interface Props {
  resources: Record<string, unknown>[];
  totalCount: number;
  page: number;
  pageSize: number;
  search: string;
  onSearchChange: (value: string) => void;
  onPageChange: (page: number, pageSize: number) => void;
}

export function ResourceTable({
  resources,
  totalCount,
  page,
  pageSize,
  search,
  onSearchChange,
  onPageChange,
}: Props) {
  const columns = useMemo(() => {
    if (resources.length === 0) return [];
    const keys = Object.keys(resources[0]);
    const priority = ['id', 'name', 'username', 'description', 'type', 'status', 'organization', 'survey_enabled'];
    const sorted = priority.filter(k => keys.includes(k));
    const rest = keys.filter(k => !priority.includes(k) && typeof resources[0][k] !== 'object');
    return [...sorted, ...rest].slice(0, 8);
  }, [resources]);

  return (
    <>
      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <SearchInput
              placeholder="Filter by name..."
              value={search}
              onChange={(_e, v) => onSearchChange(v)}
              onClear={() => onSearchChange('')}
            />
          </ToolbarItem>
          <ToolbarItem align={{ default: 'alignRight' }}>
            <Pagination
              itemCount={totalCount}
              page={page}
              perPage={pageSize}
              variant="top"
              isCompact
              onSetPage={(_event, nextPage) => onPageChange(nextPage, pageSize)}
              onPerPageSelect={(_event, nextPageSize, nextPage) =>
                onPageChange(nextPage, nextPageSize)
              }
            />
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
          {resources.map((res, i) => (
            <Tr key={String(res.id ?? i)}>
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
