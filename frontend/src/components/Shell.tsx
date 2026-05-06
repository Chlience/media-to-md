import type { ReactNode } from 'react';

type RouteKey = 'workbench' | 'admin';

type AppShellProps = {
  activeRoute: RouteKey;
  children: ReactNode;
};

function navigate(route: RouteKey) {
  window.location.hash = route === 'admin' ? '#/admin' : '#/';
}

export function AppShell({ activeRoute, children }: AppShellProps) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="mark" aria-hidden="true">
          <img src="/favicon.svg" alt="" />
        </div>
        <div className="topbar-title">Media-to-MD</div>
        <div className="topbar-spacer" />
        <div className="topbar-meta">GitHub: media-to-md · 音视频/PDF → Markdown</div>
      </header>

      <nav className="subnav" aria-label="Screens">
        <div className="subnav-inner">
          <button
            className={activeRoute === 'workbench' ? 'tab active' : 'tab'}
            type="button"
            onClick={() => navigate('workbench')}
          >
            本地转换工作台 <span className="route">/</span>
          </button>
          <button
            className={activeRoute === 'admin' ? 'tab active' : 'tab'}
            type="button"
            onClick={() => navigate('admin')}
          >
            任务管理页 <span className="route">/#/admin</span>
          </button>
        </div>
      </nav>

      <main className="container">{children}</main>
    </div>
  );
}

type PageHeaderProps = {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
};

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <div className="page-head">
      <div>
        {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
        <h1>{title}</h1>
        <p className="deck">{description}</p>
      </div>
      {actions ? <div className="btn-row">{actions}</div> : null}
    </div>
  );
}
