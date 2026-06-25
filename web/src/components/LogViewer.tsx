import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import {
  Button,
  SearchInput,
  Label,
  Tooltip,
} from '@patternfly/react-core';
import AngleDoubleDownIcon from '@patternfly/react-icons/dist/esm/icons/angle-double-down-icon';
import AngleDoubleUpIcon from '@patternfly/react-icons/dist/esm/icons/angle-double-up-icon';
import PlayIcon from '@patternfly/react-icons/dist/esm/icons/play-icon';
import PauseIcon from '@patternfly/react-icons/dist/esm/icons/pause-icon';
import DownloadIcon from '@patternfly/react-icons/dist/esm/icons/download-icon';
import SearchIcon from '@patternfly/react-icons/dist/esm/icons/search-icon';
import { Ansi } from './Ansi';
import { createJobLogSocket, api } from '../api/client';
import type { Job } from '../types/resources';
import './LogViewer.css';

interface Props {
  jobId: string;
  externalLines?: string[];
  externalStatus?: string;
  onClose?: (status: string) => void;
  fullPage?: boolean;
}

const SECTION_HEADER_RE = /^(={3,}|—{3,}|-{3,}|#{1,3}\s|PLAY\b|TASK\b|RUNNING\b|Phase\b|Step\b|\[[\w\s]+\]$)/;

interface SectionState {
  [headerIndex: number]: boolean;
}

export function LogViewer({ jobId, externalLines, externalStatus, onClose, fullPage }: Props) {
  const [internalLines, setInternalLines] = useState<string[]>([]);
  const [internalStatus, setInternalStatus] = useState<string>('connecting');
  const [following, setFollowing] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [searchVisible, setSearchVisible] = useState(false);
  const [collapsed, setCollapsed] = useState<SectionState>({});
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevScrollTopRef = useRef(0);
  const prevScrollHeightRef = useRef(0);

  const lines = externalLines ?? internalLines;
  const status = externalStatus ?? internalStatus;

  useEffect(() => {
    if (externalLines !== undefined) return;

    setInternalLines([]);
    setInternalStatus('connecting');
    setCollapsed({});
    setFollowing(true);

    let closed = false;
    let wsReceivedData = false;

    const ws = createJobLogSocket(
      jobId,
      (line) => {
        wsReceivedData = true;
        setInternalLines(prev => [...prev, line]);
        setInternalStatus('streaming');
      },
      (reason) => {
        const finalStatus = reason || 'closed';
        setInternalStatus(finalStatus);
        onClose?.(finalStatus);

        if (!wsReceivedData && !closed) {
          loadFromRest();
        }
      }
    );

    async function loadFromRest() {
      try {
        const job = await api.getJob(jobId) as Job;
        if (job.output && job.output.length > 0) {
          setInternalLines(job.output);
          setInternalStatus(job.status);
        } else {
          setInternalStatus(job.status || 'empty');
        }
      } catch {
        setInternalStatus('error');
      }
    }

    return () => {
      closed = true;
      ws.close();
    };
  }, [jobId, externalLines]);

  useEffect(() => {
    if (following && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines, following]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;

    const { scrollTop, scrollHeight, clientHeight } = el;
    const atBottom = scrollHeight - scrollTop - clientHeight < 30;
    const contentGrew = scrollHeight > prevScrollHeightRef.current;
    const userScrolledUp = scrollTop < prevScrollTopRef.current && !contentGrew;

    if (userScrolledUp && following) {
      setFollowing(false);
    } else if (atBottom && !following) {
      setFollowing(true);
    }

    prevScrollTopRef.current = scrollTop;
    prevScrollHeightRef.current = scrollHeight;
  }, [following]);

  const isHeaderLine = useCallback((line: string) => {
    const stripped = line.replace(/\x1b\[[0-9;]*m/g, '').trim();
    return SECTION_HEADER_RE.test(stripped);
  }, []);

  const headerIndices = useMemo(() => {
    const indices: number[] = [];
    for (let i = 0; i < lines.length; i++) {
      if (isHeaderLine(lines[i])) indices.push(i);
    }
    return indices;
  }, [lines, isHeaderLine]);

  const toggleCollapse = useCallback((headerIdx: number) => {
    setCollapsed(prev => ({ ...prev, [headerIdx]: !prev[headerIdx] }));
  }, []);

  const collapseAll = useCallback(() => {
    const allCollapsed: SectionState = {};
    headerIndices.forEach(idx => { allCollapsed[idx] = true; });
    setCollapsed(allCollapsed);
  }, [headerIndices]);

  const expandAll = useCallback(() => {
    setCollapsed({});
  }, []);

  const visibleLines = useMemo(() => {
    const result: { line: string; index: number; isHeader: boolean }[] = [];
    let skipUntilNextHeader = false;

    for (let i = 0; i < lines.length; i++) {
      const isHeader = headerIndices.includes(i);

      if (isHeader) {
        skipUntilNextHeader = !!collapsed[i];
        result.push({ line: lines[i], index: i, isHeader: true });
        continue;
      }

      if (skipUntilNextHeader) continue;

      result.push({ line: lines[i], index: i, isHeader: false });
    }

    return result;
  }, [lines, headerIndices, collapsed]);

  const searchLower = searchText.toLowerCase();
  const matchesSearch = useCallback((line: string) => {
    if (!searchText) return false;
    const stripped = line.replace(/\x1b\[[0-9;]*m/g, '');
    return stripped.toLowerCase().includes(searchLower);
  }, [searchText, searchLower]);

  const searchMatchCount = useMemo(() => {
    if (!searchText) return 0;
    return lines.filter(l => matchesSearch(l)).length;
  }, [lines, searchText, matchesSearch]);

  const handleDownload = useCallback(() => {
    const stripped = lines.map(l => l.replace(/\x1b\[[0-9;]*m/g, '')).join('\n');
    const blob = new Blob([stripped], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `job-${jobId}-output.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }, [lines, jobId]);

  const scrollToTop = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
      setFollowing(false);
    }
  }, []);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      setFollowing(true);
    }
  }, []);

  const isRunning = status === 'streaming' || status === 'connecting';
  const anyCollapsed = Object.values(collapsed).some(Boolean);
  const collapsedCount = Object.values(collapsed).filter(Boolean).length;

  const statusColor = (() => {
    switch (status) {
      case 'streaming': case 'connecting': return 'blue';
      case 'completed': return 'green';
      case 'failed': case 'error': return 'red';
      case 'cancelled': return 'orange';
      default: return 'grey';
    }
  })();

  const statusLabel = (() => {
    switch (status) {
      case 'streaming': return 'Running';
      case 'connecting': return 'Connecting';
      case 'completed': return 'Completed';
      case 'failed': return 'Failed';
      case 'cancelled': return 'Cancelled';
      case 'error': return 'Error';
      case 'closed': return 'Closed';
      case 'empty': return 'No output';
      default: return status;
    }
  })();

  return (
    <div className="log-viewer">
      <div className="log-viewer__toolbar">
        <div className="log-viewer__toolbar-group">
          <Label color={statusColor} isCompact>{statusLabel}</Label>
          <span className="log-viewer__status">{lines.length} lines</span>
        </div>

        <div className="log-viewer__toolbar-group">
          {headerIndices.length > 0 && (
            <Tooltip content={anyCollapsed ? 'Expand all sections' : 'Collapse all sections'}>
              <Button variant="plain" size="sm" onClick={anyCollapsed ? expandAll : collapseAll} aria-label={anyCollapsed ? 'Expand all' : 'Collapse all'}>
                {anyCollapsed ? `Expand (${collapsedCount})` : 'Collapse all'}
              </Button>
            </Tooltip>
          )}
        </div>

        <div className="log-viewer__toolbar-spacer" />

        <div className="log-viewer__toolbar-group">
          {searchVisible && (
            <div className="log-viewer__search">
              <SearchInput
                placeholder="Search output..."
                value={searchText}
                onChange={(_e, val) => setSearchText(val)}
                onClear={() => setSearchText('')}
                resultsCount={searchText ? `${searchMatchCount} matches` : undefined}
              />
            </div>
          )}
          <Tooltip content="Search">
            <Button
              variant={searchVisible ? 'secondary' : 'plain'}
              size="sm"
              onClick={() => { setSearchVisible(!searchVisible); if (searchVisible) setSearchText(''); }}
              aria-label="Toggle search"
            >
              <SearchIcon />
            </Button>
          </Tooltip>
        </div>

        <div className="log-viewer__toolbar-group">
          <Tooltip content="Scroll to top">
            <Button variant="plain" size="sm" onClick={scrollToTop} aria-label="Scroll to top"><AngleDoubleUpIcon /></Button>
          </Tooltip>
          <Tooltip content="Scroll to bottom">
            <Button variant="plain" size="sm" onClick={scrollToBottom} aria-label="Scroll to bottom"><AngleDoubleDownIcon /></Button>
          </Tooltip>
          {isRunning && (
            <Tooltip content={following ? 'Pause following' : 'Follow output'}>
              <Button
                variant={following ? 'secondary' : 'plain'}
                size="sm"
                onClick={() => { setFollowing(!following); if (!following && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }}
                aria-label={following ? 'Pause follow' : 'Follow'}
              >
                {following ? <PauseIcon /> : <PlayIcon />}
              </Button>
            </Tooltip>
          )}
          <Tooltip content="Download output">
            <Button variant="plain" size="sm" onClick={handleDownload} isDisabled={lines.length === 0} aria-label="Download"><DownloadIcon /></Button>
          </Tooltip>
        </div>
      </div>

      <div ref={scrollRef} className={`log-viewer__content${fullPage ? ' log-viewer__content--fullpage' : ''}`} onScroll={handleScroll}>
        {lines.length === 0 ? (
          <div className="log-viewer__empty">
            {isRunning ? 'Waiting for output...' : 'No output available.'}
          </div>
        ) : (
          <div className="log-viewer__table">
            {visibleLines.map(({ line, index, isHeader }) => {
              const isCollapsed = isHeader && collapsed[index];
              const isMatch = searchText && matchesSearch(line);
              const rowClasses = [
                'log-viewer__row',
                isHeader ? 'log-viewer__row--header' : '',
                isMatch ? 'log-viewer__row--search-match' : '',
              ].filter(Boolean).join(' ');

              return (
                <div key={index}>
                  <div className={rowClasses} onClick={isHeader ? () => toggleCollapse(index) : undefined}>
                    <div className="log-viewer__gutter">
                      <div className="log-viewer__collapse-toggle">
                        {isHeader ? (isCollapsed ? '▶' : '▼') : ''}
                      </div>
                      <div className="log-viewer__line-number">{index + 1}</div>
                    </div>
                    <div className="log-viewer__line-content"><Ansi input={line} /></div>
                  </div>
                  {isHeader && isCollapsed && (
                    <div className="log-viewer__ellipsis" onClick={() => toggleCollapse(index)}>
                      ··· collapsed ···
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
