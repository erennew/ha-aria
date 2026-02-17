import { useState, useEffect, useRef } from 'preact/hooks';
import useCache from '../hooks/useCache.js';
import useComputed from '../hooks/useComputed.js';
import { fetchJson } from '../api.js';
import LoadingState from '../components/LoadingState.jsx';
import ErrorState from '../components/ErrorState.jsx';
import AriaLogo from '../components/AriaLogo.jsx';
import HeroCard from '../components/HeroCard.jsx';
import PageBanner from '../components/PageBanner.jsx';
import PresenceCard from '../components/PresenceCard.jsx';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PHASES = ['collecting', 'baselines', 'ml-training', 'ml-active'];
const PHASE_LABELS = ['Collecting', 'Baselines', 'ML Training', 'ML Active'];
const PHASE_MILESTONES = [
  'Gathering daily snapshots',
  'Statistical baselines active',
  'Training ML models',
  'Full intelligence active',
];

// ---------------------------------------------------------------------------
// Bus Architecture Diagram
// ---------------------------------------------------------------------------

const FLOW_INTAKE = [
  { id: 'engine', label: 'Engine', metricKey: 'pipeline_day' },
  { id: 'discovery', label: 'Discovery', metricKey: 'entity_count' },
  { id: 'activity_monitor', label: 'Activity', metricKey: 'event_rate' },
  { id: 'presence', label: 'Presence', metricKey: 'presence_status' },
];

const FLOW_PROCESSING = [
  { id: 'intelligence', label: 'Intelligence', metricKey: 'day_count' },
  { id: 'ml_engine', label: 'ML Engine', metricKey: 'mean_r2' },
  { id: 'shadow_engine', label: 'Shadow', metricKey: 'accuracy' },
  { id: 'pattern_recognition', label: 'Patterns', metricKey: 'sequence_count' },
];

const FLOW_ENRICHMENT = [
  { id: 'orchestrator', label: 'Orchestrator', metricKey: 'pending_count' },
  { id: 'organic_discovery', label: 'Organic Disc.', metricKey: 'organic_count' },
  { id: 'data_quality', label: 'Curation', metricKey: 'included_count' },
  { id: 'activity_labeler', label: 'Labeler', metricKey: 'current_activity' },
];

function getNodeStatus(moduleStatuses, nodeId) {
  const status = moduleStatuses?.[nodeId];
  if (status === 'running') return 'healthy';
  if (status === 'failed') return 'blocked';
  if (status === 'starting') return 'waiting';
  return 'waiting';
}

function getNodeMetric(cacheData, node) {
  const caps = cacheData?.capabilities?.data || {};
  const pipeline = cacheData?.pipeline?.data || {};
  const shadow = cacheData?.shadow_accuracy?.data || {};
  const activity = cacheData?.activity_labels?.data || {};
  switch (node.id) {
    case 'engine': return pipeline?.intelligence_day ? `Day ${pipeline.intelligence_day}` : '\u2014';
    case 'discovery': {
      const count = Object.values(caps).filter((entry) => entry && typeof entry === 'object' && entry.entities).reduce((sum, entry) => sum + (entry.entities?.length || 0), 0);
      return count ? `${count} entities` : '\u2014';
    }
    case 'activity_monitor': return pipeline?.events_per_minute ? `${pipeline.events_per_minute.toFixed(1)} ev/m` : '\u2014';
    case 'presence': return '\u2014';
    case 'intelligence': return pipeline?.intelligence_day ? `Day ${pipeline.intelligence_day}` : '\u2014';
    case 'ml_engine': {
      const mlCaps = Object.values(caps).filter((entry) => entry?.ml_accuracy);
      if (mlCaps.length === 0) return '\u2014';
      const avgR2 = mlCaps.reduce((s, entry) => s + (entry.ml_accuracy.mean_r2 || 0), 0) / mlCaps.length;
      return `R\u00B2: ${avgR2.toFixed(2)}`;
    }
    case 'shadow_engine': return shadow?.overall_accuracy ? `${(shadow.overall_accuracy * 100).toFixed(0)}%` : '\u2014';
    case 'pattern_recognition': return '\u2014';
    case 'orchestrator': return '\u2014';
    case 'organic_discovery': {
      const organic = Object.values(caps).filter((entry) => entry?.source === 'organic').length;
      return organic ? `${organic} organic` : '\u2014';
    }
    case 'data_quality': return pipeline?.included_entities ? `${pipeline.included_entities} incl.` : '\u2014';
    case 'activity_labeler': {
      const curr = activity?.current_activity;
      return curr?.predicted || '\u2014';
    }
    default: return '\u2014';
  }
}

function ModuleNode({ x, y, status, label, metric, glowing, animateMetric }) {
  const colors = {
    healthy: 'var(--status-healthy)',
    waiting: 'var(--status-waiting)',
    blocked: 'var(--status-error)',
    review: 'var(--status-warning)',
  };
  const color = colors[status] || colors.waiting;

  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect width="180" height="55" rx="4" fill="var(--bg-surface)" stroke={glowing ? 'var(--accent)' : 'var(--border-primary)'} stroke-width={glowing ? '2' : '1'} />
      {glowing && (
        <rect width="180" height="55" rx="4" fill="none" stroke="var(--accent)" stroke-width="1" opacity="0.3">
          <animate attributeName="opacity" values="0.3;0.1;0.3" dur="2s" repeatCount="1" />
        </rect>
      )}
      <circle cx="16" cy="16" r="5" fill={color} filter="url(#led-glow)">
        {(status === 'healthy' || glowing) && <animate attributeName="opacity" values="1;0.6;1" dur={glowing ? '1s' : '3s'} repeatCount="indefinite" />}
      </circle>
      <text x="28" y="20" fill="var(--text-primary)" font-size="11" font-weight="600" font-family="var(--font-mono)">{label}</text>
      <text x="16" y="42" fill="var(--text-tertiary)" font-size="10" font-family="var(--font-mono)" class={animateMetric ? 't2-typewriter' : ''}>
        {metric}
      </text>
    </g>
  );
}


function BusArchitecture({ moduleStatuses, cacheData }) {
  const nodeX = [30, 235, 440, 645];
  const nodeW = 180;

  // --- Activity Labeler pulse animation (kept from original) ---
  const prevActivityRef = useRef(null);
  const [labelerGlowing, setLabelerGlowing] = useState(false);
  const [labelerAnimateMetric, setLabelerAnimateMetric] = useState(false);
  const glowTimerRef = useRef(null);

  const currentActivity = cacheData?.activity_labels?.data?.current_activity?.predicted || null;

  useEffect(() => {
    if (prevActivityRef.current !== null && currentActivity !== prevActivityRef.current && currentActivity !== null) {
      setLabelerGlowing(true);
      setLabelerAnimateMetric(true);
      clearTimeout(glowTimerRef.current);
      glowTimerRef.current = setTimeout(() => {
        setLabelerGlowing(false);
        setLabelerAnimateMetric(false);
      }, 2000);
    }
    prevActivityRef.current = currentActivity;
    return () => clearTimeout(glowTimerRef.current);
  }, [currentActivity]);

  function renderRow(nodes, yOffset) {
    return nodes.map((node, idx) => {
      const isLabeler = node.id === 'activity_labeler';
      return (
        <ModuleNode
          key={node.id}
          x={nodeX[idx]}
          y={yOffset}
          status={node.id === 'engine' ? 'healthy' : getNodeStatus(moduleStatuses, node.id)}
          label={node.label}
          metric={getNodeMetric(cacheData, node)}
          glowing={isLabeler && labelerGlowing}
          animateMetric={isLabeler && labelerAnimateMetric}
        />
      );
    });
  }

  // Arrow helper — small downward arrow
  function Arrow({ x, y, label }) {
    return (
      <g>
        <line x1={x} y1={y} x2={x} y2={y + 18} stroke="var(--border-primary)" stroke-width="1" />
        <polygon points={`${x - 3},${y + 14} ${x + 3},${y + 14} ${x},${y + 18}`} fill="var(--border-primary)" />
        {label && <text x={x + 6} y={y + 12} fill="var(--text-tertiary)" font-size="7" font-family="var(--font-mono)">{label}</text>}
      </g>
    );
  }

  // Banner bar helper
  function Banner({ y, label, sublabel, color }) {
    return (
      <g>
        <rect x="20" y={y} width="820" height="28" rx="4" fill="var(--bg-inset)" stroke={color || 'var(--accent)'} stroke-width="1.5" />
        <text x="430" y={y + 13} text-anchor="middle" fill={color || 'var(--accent)'} font-size="11" font-weight="700" font-family="var(--font-mono)">{label}</text>
        {sublabel && <text x="430" y={y + 24} text-anchor="middle" fill="var(--text-tertiary)" font-size="8" font-family="var(--font-mono)">{sublabel}</text>}
      </g>
    );
  }

  // Center x for each node column
  const cx = nodeX.map((x) => x + nodeW / 2);

  // Vertical tracer path down center
  const tracerPath = 'M430,28 L430,80 L430,250 L430,325 L430,405 L430,475 L430,530';

  return (
    <section class="t-terminal-bg rounded-lg p-4 overflow-x-auto">
      <svg viewBox="0 0 860 560" class="w-full" style="min-width: 700px; max-width: 100%;">
        <defs>
          <filter id="led-glow">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="tracer-glow">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Layer 1: HOME ASSISTANT banner */}
        <Banner y={0} label="HOME ASSISTANT" sublabel="REST API \u00B7 WebSocket \u00B7 MQTT" />

        {/* Connection labels from HA to intake */}
        <Arrow x={cx[0]} y={28} label="scheduled" />
        <Arrow x={cx[1]} y={28} label="on startup" />
        <Arrow x={cx[2]} y={28} label="real-time" />
        <Arrow x={cx[3]} y={28} label="mqtt" />

        {/* Layer 2: INTAKE row */}
        <text x="430" y={58} text-anchor="middle" fill="var(--text-tertiary)" font-size="9" font-weight="700" font-family="var(--font-mono)" letter-spacing="2">INTAKE</text>
        {renderRow(FLOW_INTAKE, 62)}

        {/* Engine Pipeline detail box */}
        <g transform="translate(30, 125)">
          <rect width="800" height="42" rx="4" fill="none" stroke="var(--border-primary)" stroke-width="1" stroke-dasharray="4 2" />
          <text x="12" y="14" fill="var(--text-tertiary)" font-size="8" font-weight="600" font-family="var(--font-mono)">ENGINE PIPELINE</text>
          <text x="12" y="32" fill="var(--text-tertiary)" font-size="8" font-family="var(--font-mono)">
            {'snapshots \u2192 baselines \u2192 ML training \u2192 predictions \u2192 correlations \u2192 anomalies'}
          </text>
        </g>

        {/* Arrows from intake to Hub Cache */}
        {cx.map((x, i) => <Arrow key={`a1-${i}`} x={x} y={170} label={['JSON files', 'entities', 'events', 'occupancy'][i]} />)}

        {/* Layer 3: HUB CACHE banner */}
        <Banner y={192} label="HUB CACHE" sublabel="SQLite \u00B7 15 categories" color="var(--status-healthy)" />

        {/* Arrows from cache to processing */}
        {cx.map((x, i) => <Arrow key={`a2-${i}`} x={x} y={220} />)}

        {/* Layer 4: PROCESSING row */}
        <text x="430" y={248} text-anchor="middle" fill="var(--text-tertiary)" font-size="9" font-weight="700" font-family="var(--font-mono)" letter-spacing="2">PROCESSING</text>
        {renderRow(FLOW_PROCESSING, 255)}

        {/* Layer 5: ENRICHMENT row */}
        <text x="430" y={328} text-anchor="middle" fill="var(--text-tertiary)" font-size="9" font-weight="700" font-family="var(--font-mono)" letter-spacing="2">ENRICHMENT</text>
        {renderRow(FLOW_ENRICHMENT, 335)}

        {/* Arrows to YOU */}
        <Arrow x={430} y={395} />

        {/* Layer 6: YOU banner */}
        <g transform="translate(200, 418)">
          <rect x="0" y="0" width="460" height="35" rx="4" fill="var(--bg-inset)" stroke="var(--accent)" stroke-width="2" />
          <text x="230" y="22" text-anchor="middle" fill="var(--accent)" font-size="12" font-weight="bold" font-family="var(--font-mono)">
            {'YOU:  Label \u00B7 Curate \u00B7 Review \u00B7 Advance'}
          </text>
        </g>

        {/* Arrow to Dashboard */}
        <Arrow x={430} y={453} />

        {/* Layer 7: DASHBOARD banner */}
        <Banner y={475} label="DASHBOARD" sublabel="13 pages \u00B7 WebSocket push" />

        {/* Flowing dot tracer along center vertical */}
        <circle r="3" fill="var(--accent)" opacity="0.7" filter="url(#tracer-glow)">
          <animateMotion dur="8s" repeatCount="indefinite" path={tracerPath} />
        </circle>
        <circle r="5" fill="var(--accent)" opacity="0.2" filter="url(#tracer-glow)">
          <animateMotion dur="8s" repeatCount="indefinite" path={tracerPath} begin="0.4s" />
        </circle>
      </svg>
    </section>
  );
}

// ---------------------------------------------------------------------------
// JourneyProgress
// ---------------------------------------------------------------------------

function JourneyProgress({ maturity, shadowStage }) {
  const phase = maturity ? maturity.phase || 'collecting' : 'collecting';
  const activeIdx = PHASES.indexOf(phase);

  return (
    <section class="t-frame" data-label="system maturity">
      <div class="flex items-center gap-1 mb-2">
        {PHASES.map((p, i) => {
          let bg = 'var(--bg-inset)';
          if (i < activeIdx) bg = 'var(--status-healthy)';
          else if (i === activeIdx) bg = 'var(--accent)';
          return <div key={p} class="h-2 flex-1" style={`border-radius: var(--radius); background: ${bg};`} />;
        })}
      </div>
      <div class="flex justify-between text-xs">
        {PHASES.map((p, i) => {
          let color = 'var(--text-tertiary)';
          let weight = 'normal';
          if (i < activeIdx) color = 'var(--status-healthy)';
          else if (i === activeIdx) { color = 'var(--accent)'; weight = '500'; }
          return <span key={p} style={`color: ${color}; font-weight: ${weight};`}>{PHASE_LABELS[i]}</span>;
        })}
      </div>
      <p class="text-xs mt-2" style="color: var(--text-tertiary)">
        {activeIdx >= 0 && activeIdx < PHASE_MILESTONES.length ? PHASE_MILESTONES[activeIdx] : ''}
        {shadowStage ? ` \u2014 Pipeline: ${shadowStage}` : ''}
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// RightNowStrip
// ---------------------------------------------------------------------------

function RightNowStrip({ activity, intraday }) {
  // activity = useCache result; activity.data = {category, data: {occupancy, websocket, ...}}
  const inner = activity && activity.data ? (activity.data.data || null) : null;
  const ws = inner ? (inner.websocket || null) : null;
  const actRate = inner ? (inner.activity_rate || null) : null;
  const evRate = actRate ? actRate.current : null;
  const occ = inner ? (inner.occupancy || null) : null;

  // intraday_trend is a list of hourly snapshots — use the latest
  const latest = Array.isArray(intraday) && intraday.length > 0 ? intraday[intraday.length - 1] : null;
  const lightsOn = latest ? (latest.lights_on ?? null) : null;
  const powerW = latest ? (latest.power_watts ?? null) : null;

  return (
    <section class="t-frame" data-label="live metrics">
      <div class="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
        <div class="flex items-center gap-1.5">
          <span style="color: var(--text-tertiary)">Occupancy</span>
          <span class="font-medium" style="color: var(--text-primary)">{occ && occ.anyone_home ? 'Home' : occ ? 'Away' : '\u2014'}</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span style="color: var(--text-tertiary)">Events</span>
          <span class="data-mono font-medium" style="color: var(--text-primary)">{evRate != null ? `${evRate}/min` : '\u2014'}</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span style="color: var(--text-tertiary)">Lights</span>
          <span class="data-mono font-medium" style="color: var(--text-primary)">{lightsOn != null ? `${lightsOn} on` : '\u2014'}</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span style="color: var(--text-tertiary)">Power</span>
          <span class="data-mono font-medium" style="color: var(--text-primary)">{powerW != null ? `${Math.round(powerW)} W` : '\u2014'}</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="w-2 h-2 rounded-full" style={`background: ${ws && ws.connected ? 'var(--status-healthy)' : 'var(--status-error)'};`} />
          <span style="color: var(--text-tertiary)">WebSocket</span>
          <span class="font-medium" style="color: var(--text-primary)">{ws && ws.connected ? 'Connected' : ws === null ? '\u2014' : 'Disconnected'}</span>
        </div>
      </div>
    </section>
  );
}


// ---------------------------------------------------------------------------
// Home (default export)
// ---------------------------------------------------------------------------

export default function Home() {
  const intelligence = useCache('intelligence');
  const activity = useCache('activity_summary');
  const entities = useCache('entities');

  const [health, setHealth] = useState(null);
  const [shadow, setShadow] = useState(null);
  const [pipeline, setPipeline] = useState(null);
  const [curation, setCuration] = useState(null);
  const [fetchError, setFetchError] = useState(null);

  useEffect(() => {
    Promise.all([
      fetchJson('/health').catch(() => null),
      fetchJson('/api/shadow/accuracy').catch(() => null),
      fetchJson('/api/pipeline').catch(() => null),
      fetchJson('/api/curation/summary').catch(() => null),
      fetchJson('/api/activity/current').catch(() => null),
    ]).then(([hlth, s, p, c, act]) => {
      setHealth(hlth);
      setShadow(s);
      setPipeline(p);
      setCuration(c);
    }).catch((err) => setFetchError(err.message || String(err)));
  }, []);

  const loading = intelligence.loading || activity.loading || entities.loading;
  const cacheError = intelligence.error || activity.error || entities.error;

  const maturity = useComputed(() => {
    if (!intelligence.data || !intelligence.data.data) return null;
    return intelligence.data.data.data_maturity || null;
  }, [intelligence.data]);

  const intraday = useComputed(() => {
    if (!intelligence.data || !intelligence.data.data) return null;
    return intelligence.data.data.intraday_trend || null;
  }, [intelligence.data]);

  const shadowStage = useComputed(() => {
    return pipeline ? (pipeline.current_stage || null) : null;
  }, [pipeline]);

  const cacheData = useComputed(() => ({
    capabilities: entities.data,
    pipeline: { data: pipeline },
    shadow_accuracy: { data: shadow },
    activity_labels: activity.data,
  }), [entities.data, pipeline, shadow, activity.data]);

  if (loading && !intelligence.data) {
    return (
      <div class="space-y-6">
        <div class="t-frame" data-label="aria">
          <AriaLogo className="w-24 mb-1" color="var(--text-primary)" />
          <p class="text-sm" style="color: var(--text-tertiary); font-family: var(--font-mono);">
            Live system overview — data flow, module health, and your next steps.
          </p>
        </div>
        <LoadingState type="full" />
      </div>
    );
  }

  if (cacheError) {
    return (
      <div class="space-y-6">
        <div class="t-frame" data-label="aria">
          <AriaLogo className="w-24 mb-1" color="var(--text-primary)" />
          <p class="text-sm" style="color: var(--text-tertiary); font-family: var(--font-mono);">
            Live system overview — data flow, module health, and your next steps.
          </p>
        </div>
        <ErrorState
          error={cacheError}
          onRetry={() => { intelligence.refetch(); activity.refetch(); entities.refetch(); }}
        />
      </div>
    );
  }

  if (fetchError) {
    return (
      <div class="space-y-6">
        <PageBanner page="HOME" subtitle="Live system overview — data flow, module health, and your next steps." />
        <ErrorState error={fetchError} />
      </div>
    );
  }

  return (
    <div class="space-y-6 animate-page-enter">
      <PageBanner page="HOME" subtitle="Live system overview — data flow, module health, and your next steps." />

      <HeroCard
        value={pipeline ? pipeline.current_stage : 'starting'}
        label="pipeline stage"
        delta={maturity ? `Day ${maturity.days_of_data} \u00b7 ${maturity.phase}` : null}
      />

      <JourneyProgress maturity={maturity} shadowStage={shadowStage} />

      <RightNowStrip activity={activity} intraday={intraday} />

      <PresenceCard />

      <BusArchitecture
        moduleStatuses={health?.modules || {}}
        cacheData={cacheData}
      />
    </div>
  );
}
