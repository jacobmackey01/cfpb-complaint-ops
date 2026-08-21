import { Activity, Inbox, LayoutDashboard, ShieldCheck } from 'lucide-react';
import type { PropsWithChildren } from 'react';
import { NavLink } from 'react-router-dom';

const navItems = [
  { to: '/', label: 'Operations', icon: LayoutDashboard, end: true },
  { to: '/queue', label: 'Case queue', icon: Inbox, end: false },
  { to: '/model', label: 'Model monitor', icon: Activity, end: false },
] as const;

export const AppChrome = ({ children }: PropsWithChildren) => (
  <div className="app-shell">
    <a className="skip-link" href="#main-content">
      Skip to content
    </a>
    <aside className="sidebar" aria-label="Primary navigation">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          SD
        </span>
        <span>
          <strong>Signal Desk</strong>
          <small>Complaint operations</small>
        </span>
      </div>
      <nav className="nav-list">
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            className={({ isActive }) => `nav-link${isActive ? ' is-active' : ''}`}
            end={end}
            key={to}
            to={to}
          >
            <Icon aria-hidden="true" size={18} strokeWidth={1.8} />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="human-control">
        <ShieldCheck aria-hidden="true" size={19} />
        <span>
          <strong>Human decision required</strong>
          <small>AI suggestions never route or close a case on their own.</small>
        </span>
      </div>
    </aside>
    <div className="app-main">
      <header className="mobile-header">
        <div className="brand brand-mobile">
          <span className="brand-mark" aria-hidden="true">
            SD
          </span>
          <strong>Signal Desk</strong>
        </div>
        <nav aria-label="Primary navigation" className="mobile-nav">
          {navItems.map(({ to, label, end }) => (
            <NavLink
              aria-label={label}
              className={({ isActive }) => (isActive ? 'is-active' : '')}
              end={end}
              key={to}
              to={to}
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main id="main-content">{children}</main>
      <footer className="site-footer">
        <p>
          CFPB complaints are not a representative statistical sample. Raw company complaint counts
          must not be interpreted as comparative performance without market-share denominators.
        </p>
        <p>
          Narratives appear only when consumers consent to publication and after the CFPB takes steps
          to remove personal information.
        </p>
      </footer>
    </div>
  </div>
);
