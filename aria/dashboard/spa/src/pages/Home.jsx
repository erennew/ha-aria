import { useState, useEffect } from 'preact/hooks';
import useCache from '../hooks/useCache.js';
import useComputed from '../hooks/useComputed.js';
import { fetchJson } from '../api.js';
import LoadingState from '../components/LoadingState.jsx';
import ErrorState from '../components/ErrorState.jsx';
import AriaLogo from '../components/AriaLogo.jsx';
import HeroCard from '../components/HeroCard.jsx';
import PageBanner from '../components/PageBanner.jsx';
import PresenceCard from '../components/PresenceCard.jsx';
import PipelineSankey from '../components/PipelineSankey.jsx';

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

      <PipelineSankey
        moduleStatuses={health?.modules || {}}
        cacheData={cacheData}
      />
    </div>
  );
}
