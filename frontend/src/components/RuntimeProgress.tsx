import type { RuntimePhase } from '../types/api';

export function runtimePercentText(phase: RuntimePhase | null | undefined): string {
  if (phase?.stagePercent === null || phase?.stagePercent === undefined) return '进行中';
  return `当前阶段进度：${phase.stagePercent.toFixed(1)}%`;
}

export function runtimePhaseSummary(phase: RuntimePhase | null | undefined): string {
  if (!phase) return '—';
  return `${phase.label} · ${runtimePercentText(phase)}`;
}

export function RuntimeProgressBar({
  phase,
  showText = true,
}: {
  phase: RuntimePhase | null | undefined;
  showText?: boolean;
}) {
  const value = phase?.stagePercent;
  if (value === null || value === undefined) {
    return showText ? <div className="runtime-progress-text">进行中</div> : null;
  }
  const width = `${Math.max(0, Math.min(value, 100))}%`;
  return (
    <div className="runtime-progress" aria-label={`当前阶段进度 ${value.toFixed(1)}%`}>
      <div className="runtime-progress-track">
        <div className="runtime-progress-fill" style={{ width }} />
      </div>
      {showText ? <div className="runtime-progress-text">{runtimePercentText(phase)}</div> : null}
    </div>
  );
}

export function RuntimePhaseCompact({ phase }: { phase: RuntimePhase | null | undefined }) {
  if (!phase) return <span className="muted">—</span>;
  return (
    <div className="runtime-phase-compact">
      <strong>{phase.label}</strong>
      <span>{runtimePercentText(phase)}</span>
    </div>
  );
}
