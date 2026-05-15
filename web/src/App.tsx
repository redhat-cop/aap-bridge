import { useState } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
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
  Title,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
} from '@patternfly/react-core';
import BarsIcon from '@patternfly/react-icons/dist/esm/icons/bars-icon';
import { Dashboard } from './pages/Dashboard';
import { Operations } from './pages/Operations';
import { Migrate } from './pages/Migrate';
import { ObjectBrowser } from './pages/ObjectBrowser';
import { Jobs } from './pages/Jobs';

const ansibleLogo =
  'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMjggMTI4Ij48cGF0aCBmaWxsPSIjMUExOTE4IiBkPSJNMTI2IDY0YzAgMzQuMi0yNy44IDYyLTYyIDYyUzIgOTguMiAyIDY0IDI5LjggMiA2NCAyczYyIDI3LjggNjIgNjIiLz48cGF0aCBmaWxsPSIjRkZGIiBkPSJNNjUgMzkuOWwxNiAzOS42LTI0LjEtMTkuMUw2NSAzOS45em0yOC41IDQ4LjdMNjguOSAyOS4yYy0uNy0xLjctMi4xLTIuNi0zLjgtMi42LTEuNyAwLTMuMi45LTMuOSAyLjZMMzQgOTQuM2g5LjNMNTQgNjcuNWwzMiAyNS45YzEuMyAxIDIuMiAxLjUgMy40IDEuNSAyLjQgMCA0LjUtMS44IDQuNS00LjQuMS0uNS0uMS0xLjItLjQtMS45eiIvPjwvc3ZnPg==';

export function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const header = (
    <Masthead>
      <MastheadToggle>
        <PageToggleButton
          variant="plain"
          aria-label="Toggle sidebar"
          isSidebarOpen={sidebarOpen}
          onSidebarToggle={() => setSidebarOpen(prev => !prev)}
        >
          <BarsIcon />
        </PageToggleButton>
      </MastheadToggle>
      <MastheadMain>
        <MastheadBrand>
          <Title headingLevel="h3" style={{ color: 'white', margin: 0 }}>
            AAP Bridge
          </Title>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Toolbar isFullHeight>
          <ToolbarContent>
            <ToolbarItem align={{ default: 'alignRight' }}>
              <img src={ansibleLogo} alt="Ansible" style={{ height: '36px' }} />
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </MastheadContent>
    </Masthead>
  );

  const sidebar = (
    <PageSidebar isSidebarOpen={sidebarOpen}>
      <PageSidebarBody>
        <Nav>
          <NavList>
            <NavItem>
              <NavLink to="/" end style={({ isActive }) => ({ fontWeight: isActive ? 'bold' : 'normal' })}>
                Connections
              </NavLink>
            </NavItem>
            <NavItem>
              <NavLink to="/operations" style={({ isActive }) => ({ fontWeight: isActive ? 'bold' : 'normal' })}>
                Operations
              </NavLink>
            </NavItem>
            <NavItem>
              <NavLink to="/migrate" style={({ isActive }) => ({ fontWeight: isActive ? 'bold' : 'normal' })}>
                Migrate
              </NavLink>
            </NavItem>
            <NavItem>
              <NavLink to="/browse" style={({ isActive }) => ({ fontWeight: isActive ? 'bold' : 'normal' })}>
                Object Browser
              </NavLink>
            </NavItem>
            <NavItem>
              <NavLink to="/jobs" style={({ isActive }) => ({ fontWeight: isActive ? 'bold' : 'normal' })}>
                Jobs
              </NavLink>
            </NavItem>
          </NavList>
        </Nav>
      </PageSidebarBody>
    </PageSidebar>
  );

  return (
    <BrowserRouter>
      <Page header={header} sidebar={sidebar} isManagedSidebar={false}>
        <PageSection>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/operations" element={<Operations />} />
            <Route path="/migrate" element={<Migrate />} />
            <Route path="/browse" element={<ObjectBrowser />} />
            <Route path="/jobs" element={<Jobs />} />
          </Routes>
        </PageSection>
      </Page>
    </BrowserRouter>
  );
}
