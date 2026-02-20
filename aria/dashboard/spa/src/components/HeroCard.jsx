import { useEffect, useRef } from 'preact/hooks';
import TimeChart from './TimeChart.jsx';

// Freshness thresholds (seconds): 5min cooling, 30min frozen, 60min stale
const FRESHNESS_THRESHOLDS = { cooling: 300, frozen: 1800, stale: 3600 };

function computeFreshness(timestamp) {
  if (!timestamp) return null;
  const age = (Date.now() - new Date(timestamp).getTime()) / 1000;
  if (age > FRESHNESS_THRESHOLDS.stale) return 'stale';
  if (age > FRESHNESS_THRESHOLDS.frozen) return 'frozen';
  if (age > FRESHNESS_THRESHOLDS.cooling) return 'cooling';
  return 'fresh';
}

export default function HeroCard({ value, label, unit, delta, warning, loading, sparkData, sparkColor, timestamp, href }) {
  const cursorClass = loading ? 'cursor-working' : 'cursor-active';
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current) return;
    function update() {
      const state = computeFreshness(timestamp);
      if (state) {
        ref.current.setAttribute('data-sh-state', state);
      } else {
        ref.current.removeAttribute('data-sh-state');
      }
    }
    update();
    const interval = setInterval(update, 30000);
    return () => clearInterval(interval);
  }, [timestamp]);

  const cardContent = (
    <div
      ref={ref}
      class={`t-frame ${cursorClass}`}
      data-label={label}
      style={warning ? 'border-left: 3px solid var(--status-warning);' : ''}
    >
      <div class="flex items-baseline gap-2" style="justify-content: space-between;">
        <div class="flex items-baseline gap-2">
          <span
            class="data-mono"
            style={`font-size: var(--type-hero); font-weight: 600; color: ${warning ? 'var(--status-warning)' : 'var(--accent)'}; line-height: 1;`}
          >
            {value ?? '\u2014'}
          </span>
          {unit && (
            <span
              class="data-mono"
              style="font-size: var(--type-headline); color: var(--text-tertiary);"
            >
              {unit}
            </span>
          )}
        </div>
        {sparkData && sparkData.length > 1 && sparkData[0].length > 1 && (
          <div style="width: 80px; height: 32px; flex-shrink: 0;">
            <TimeChart
              data={sparkData}
              series={[{ label: label || 'trend', color: sparkColor || 'var(--accent)', width: 1.5 }]}
              compact
            />
          </div>
        )}
      </div>
      {delta && (
        <div
          style="font-size: var(--type-label); color: var(--text-secondary); margin-top: 8px; font-family: var(--font-mono);"
        >
          {delta}
        </div>
      )}
    </div>
  );

  if (href) {
    return <a href={href} class="clickable-data block" style="text-decoration: none; color: inherit;">{cardContent}</a>;
  }

  return cardContent;
}
