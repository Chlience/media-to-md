import type { ReactNode } from 'react';
import type { Artifact, JobStatusValue } from '../types/api';

type BoxProps = {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
  dense?: boolean;
  children: ReactNode;
};

export function Box({ title, subtitle, actions, className, dense, children }: BoxProps) {
  return (
    <section className={["box", className].filter(Boolean).join(' ')}>
      <div className="box-head">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p className="small">{subtitle}</p> : null}
        </div>
        {actions}
      </div>
      <div className={dense ? 'box-body dense' : 'box-body'}>{children}</div>
    </section>
  );
}

export function StatusPill({ status }: { status: JobStatusValue | 'idle' | 'valid' | string }) {
  const normalized = String(status).toLowerCase();
  const label = normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : normalized;
  let visual = normalized;
  if (normalized === 'succeeded' || normalized === 'valid') visual = 'open';
  if (normalized === 'cancelled' || normalized === 'idle') visual = 'queued';
  return <span className={`status-pill status-${visual}`}>{label}</span>;
}

export function MetaList({
  items,
}: {
  items: Array<{ label: string; value: ReactNode; mono?: boolean }>;
}) {
  return (
    <div className="meta-list">
      {items.map((item) => (
        <div className="meta-item" key={item.label}>
          <div className="meta-k">{item.label}</div>
          <div className={item.mono ? 'meta-v mono' : 'meta-v'}>{item.value}</div>
        </div>
      ))}
    </div>
  );
}

export function ArtifactList({
  artifacts,
  downloadUrl,
}: {
  artifacts: Artifact[];
  downloadUrl?: (artifact: Artifact) => string;
}) {
  if (artifacts.length === 0) {
    return <div className="callout">任务成功后会在这里显示下载链接。</div>;
  }

  return (
    <div className="artifact-list">
      {artifacts.map((artifact) => (
        <div className="artifact-row" key={artifact.name}>
          <div>
            <div className="file-name">{artifact.name}</div>
            <div className="small">
              {artifact.format || 'artifact'} · {formatBytes(artifact.sizeBytes)}
            </div>
          </div>
          <a className="btn" href={downloadUrl?.(artifact) ?? '#'} download>
            下载
          </a>
        </div>
      ))}
    </div>
  );
}

export function Timeline({ rows }: { rows: Array<{ time: string; text: ReactNode }> }) {
  if (rows.length === 0) return <div className="callout">暂无事件。</div>;
  return (
    <div className="timeline">
      {rows.map((row, index) => (
        <div className="timeline-row" key={`${row.time}-${index}`}>
          <div className="timeline-time">{row.time}</div>
          <div>{row.text}</div>
        </div>
      ))}
    </div>
  );
}

export function formatBytes(bytes?: number | null): string {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function formatDuration(seconds?: number | null): string {
  if (!seconds || seconds <= 0) return '—';
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((part) => String(part).padStart(2, '0')).join(':');
}

export function formatDate(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
}
