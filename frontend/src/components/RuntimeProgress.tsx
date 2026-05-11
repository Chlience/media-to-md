import type { RuntimePhase } from '../types/api';

export function runtimePercentText(phase: RuntimePhase | null | undefined): string {
  if (phase?.stagePercent === null || phase?.stagePercent === undefined) return '进行中';
  return `阶段 ${phase.stagePercent.toFixed(1)}%`;
}

export function runtimePhaseSummary(phase: RuntimePhase | null | undefined): string {
  if (!phase) return '—';
  return `${phase.label} · ${runtimePercentText(phase)}`;
}

export function RuntimeProgressBar({ phase }: { phase: RuntimePhase | null | undefined }) {
  const value = phase?.stagePercent;
  if (value === null || value === undefined) {
    return <div className="runtime-progress-text">当前阶段未提供百分比，显示为进行中。</div>;
  }
  const width = `${Math.max(0, Math.min(value, 100))}%`;
  return (
    <div className="runtime-progress" aria-label={`当前阶段进度 ${value.toFixed(1)}%`}>
      <div className="runtime-progress-track">
        <div className="runtime-progress-fill" style={{ width }} />
      </div>
      <div className="runtime-progress-text">{runtimePercentText(phase)}</div>
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
