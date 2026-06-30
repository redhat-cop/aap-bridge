import { useState, useEffect, Component, type ReactNode } from 'react';
import { BrowserRouter, Routes, Route, NavLink, useLocation, Link } from 'react-router-dom';
import {
  Page,
  Masthead,
  MastheadMain,
  MastheadBrand,
  MastheadContent,
  MastheadToggle,
  PageToggleButton,
  Nav,
  NavItem,
  NavList,
  PageSidebar,
  PageSidebarBody,
  PageSection,
  Toolbar,
  ToolbarContent,
  ToolbarGroup,
  ToolbarItem,
  Alert,
  Button,
} from '@patternfly/react-core';
import { Dropdown, DropdownItem, KebabToggle } from '@patternfly/react-core/deprecated';
import BarsIcon from '@patternfly/react-icons/dist/esm/icons/bars-icon';
import QuestionCircleIcon from '@patternfly/react-icons/dist/esm/icons/question-circle-icon';
import SunIcon from '@patternfly/react-icons/dist/esm/icons/sun-icon';
import MoonIcon from '@patternfly/react-icons/dist/esm/icons/moon-icon';
import { Dashboard } from './pages/Dashboard';
import { Migrate } from './pages/Migrate';
import { Jobs } from './pages/Jobs';
import { JobDetail } from './pages/JobDetail';

class AppErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 48 }}>
          <Alert variant="danger" isInline title="Application Error">
            <p>Something went wrong. Please try refreshing the page.</p>
            <pre style={{ fontSize: '0.8em', whiteSpace: 'pre-wrap', marginTop: 12, maxHeight: 300, overflow: 'auto' }}>
              {this.state.error.message}
              {'\n\n'}
              {this.state.error.stack}
            </pre>
            <Button variant="primary" onClick={() => { this.setState({ error: null }); window.location.reload(); }} style={{ marginTop: 12 }}>
              Reload Page
            </Button>
          </Alert>
        </div>
      );
    }
    return this.props.children;
  }
}

function useTheme() {
  const [dark, setDark] = useState(() => {
    const stored = localStorage.getItem('theme');
    if (stored) return stored === 'dark';
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  const toggle = () => {
    const next = !dark;
    setDark(next);
    localStorage.setItem('theme', next ? 'dark' : 'light');
    document.documentElement.classList.toggle('pf-v5-theme-dark', next);
  };

  useEffect(() => {
    document.documentElement.classList.toggle('pf-v5-theme-dark', dark);
  }, [dark]);

  return { dark, toggle };
}

function AppNav() {
  const location = useLocation();
  const path = location.pathname;
  const isActive = (route: string) => path.startsWith(route);

  return (
    <Nav>
      <NavList>
        <NavItem isActive={isActive('/connections')}>
          <NavLink to="/connections">Connections</NavLink>
        </NavItem>
        <NavItem isActive={isActive('/migrate')}>
          <NavLink to="/migrate">Migrate</NavLink>
        </NavItem>
        <NavItem isActive={isActive('/jobs')}>
          <NavLink to="/jobs">Jobs</NavLink>
        </NavItem>
      </NavList>
    </Nav>
  );
}

export function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [helpOpen, setHelpOpen] = useState(false);
  const { dark, toggle: toggleTheme } = useTheme();

  const header = (
    <Masthead display={{ default: 'inline' }}>
      <MastheadToggle>
        <PageToggleButton
          variant="plain"
          aria-label="Global navigation"
          isSidebarOpen={sidebarOpen}
          onSidebarToggle={() => setSidebarOpen(prev => !prev)}
        >
          <BarsIcon />
        </PageToggleButton>
      </MastheadToggle>
      <MastheadMain>
        <MastheadBrand>
          <Link to="/connections" style={{ textDecoration: 'none', color: 'white', fontSize: '1.25rem', fontWeight: 600 }}>
            AAP Bridge
          </Link>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Toolbar inset={{ default: 'insetNone' }}>
          <ToolbarContent>
            <ToolbarGroup align={{ default: 'alignRight' }}>
              <ToolbarItem>
                <PageToggleButton
                  variant="plain"
                  aria-label="Toggle dark mode"
                  onClick={toggleTheme}
                  style={{ color: 'white' }}
                >
                  {dark ? <SunIcon /> : <MoonIcon />}
                </PageToggleButton>
              </ToolbarItem>
              <ToolbarItem>
                <Dropdown
                  isOpen={helpOpen}
                  onSelect={() => setHelpOpen(false)}
                  toggle={
                    <KebabToggle onToggle={(_e, open) => setHelpOpen(open)}>
                      <QuestionCircleIcon style={{ color: 'white' }} />
                    </KebabToggle>
                  }
                  isPlain
                  position="right"
                  dropdownItems={[
                    <DropdownItem key="docs" component="a" href="https://redhat-cop.github.io/aap-bridge/" target="_blank">
                      Documentation
                    </DropdownItem>,
                    <DropdownItem key="repo" component="a" href="https://github.com/redhat-cop/aap-bridge" target="_blank">
                      Source Code
                    </DropdownItem>,
                  ]}
                />
              </ToolbarItem>
            </ToolbarGroup>
          </ToolbarContent>
        </Toolbar>
      </MastheadContent>
    </Masthead>
  );

  const sidebar = (
    <PageSidebar isSidebarOpen={sidebarOpen}>
      <PageSidebarBody>
        <AppNav />
      </PageSidebarBody>
    </PageSidebar>
  );

  return (
    <BrowserRouter>
      <AppErrorBoundary>
        <Page header={header} sidebar={sidebar} isManagedSidebar={false}>
          <PageSection>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/connections" element={<Dashboard />} />
              <Route path="/migrate" element={<Migrate />} />
              <Route path="/jobs" element={<Jobs />} />
              <Route path="/jobs/:id" element={<JobDetail />} />
            </Routes>
          </PageSection>
        </Page>
      </AppErrorBoundary>
    </BrowserRouter>
  );
}
