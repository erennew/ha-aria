import { useState } from 'preact/hooks';
import useCache from '../hooks/useCache.js';
import useComputed from '../hooks/useComputed.js';
import StatsGrid from '../components/StatsGrid.jsx';
import LoadingState from '../components/LoadingState.jsx';
import ErrorState from '../components/ErrorState.jsx';

function confidenceColor(conf) {
  if (conf === 'high') return 'bg-green-100 text-green-700';
  if (conf === 'medium') return 'bg-amber-100 text-amber-700';
  return 'bg-red-100 text-red-700';
}

function Section({ title, subtitle, children }) {
  return (
    <section class="space-y-3">
      <div>
        <h2 class="text-lg font-bold text-gray-900">{title}</h2>
        {subtitle && <p class="text-sm text-gray-500">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

function Callout({ children, color }) {
  const colors = {
    blue: 'bg-blue-50 border-blue-200 text-blue-800',
    amber: 'bg-amber-50 border-amber-200 text-amber-800',
    green: 'bg-green-50 border-green-200 text-green-800',
    gray: 'bg-gray-50 border-gray-200 text-gray-600',
  };
  return (
    <div class={`border rounded-lg p-3 text-sm ${colors[color || 'blue']}`}>
      {children}
    </div>
  );
}

function relativeTime(ts) {
  if (!ts) return '—';
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function durationSince(ts) {
  if (!ts) return '';
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const rmins = mins % 60;
  return rmins > 0 ? `${hrs}h ${rmins}m` : `${hrs}h`;
}

// ── Human-friendly event descriptions ────────────────────────────────

const DOMAIN_LABELS = {
  light: 'Lights',
  switch: 'Switches',
  binary_sensor: 'Sensors',
  lock: 'Locks',
  media_player: 'Media',
  cover: 'Covers',
  climate: 'Climate',
  vacuum: 'Vacuum',
  person: 'People',
  device_tracker: 'Trackers',
  fan: 'Fans',
  sensor: 'Power',
};

function describeEvent(evt) {
  const name = evt.friendly_name || evt.entity || '?';
  const domain = evt.domain || '';
  const dc = evt.device_class || '';
  const to = evt.to || '';
  const from = evt.from || '';

  // People
  if (domain === 'person' || domain === 'device_tracker') {
    if (to === 'home') return { text: `${name} arrived home`, icon: 'arrive' };
    if (from === 'home') return { text: `${name} left`, icon: 'depart' };
    return { text: `${name}: ${to}`, icon: 'person' };
  }

  // Locks
  if (domain === 'lock') {
    if (to === 'unlocked') return { text: `${name} unlocked`, icon: 'unlock' };
    if (to === 'locked') return { text: `${name} locked`, icon: 'lock' };
    return { text: `${name}: ${to}`, icon: 'lock' };
  }

  // Binary sensors by device class
  if (domain === 'binary_sensor') {
    if (dc === 'motion') {
      return to === 'on'
        ? { text: `Motion in ${name}`, icon: 'motion' }
        : { text: `${name} cleared`, icon: 'clear' };
    }
    if (dc === 'door') {
      return to === 'on'
        ? { text: `${name} opened`, icon: 'door' }
        : { text: `${name} closed`, icon: 'door' };
    }
    if (dc === 'window') {
      return to === 'on'
        ? { text: `${name} opened`, icon: 'window' }
        : { text: `${name} closed`, icon: 'window' };
    }
    if (dc === 'occupancy') {
      return to === 'on'
        ? { text: `${name} occupied`, icon: 'motion' }
        : { text: `${name} clear`, icon: 'clear' };
    }
    // Generic binary sensor
    return to === 'on'
      ? { text: `${name} active`, icon: 'sensor' }
      : { text: `${name} inactive`, icon: 'clear' };
  }

  // Lights
  if (domain === 'light') {
    return to === 'on'
      ? { text: `${name} on`, icon: 'light_on' }
      : { text: `${name} off`, icon: 'light_off' };
  }

  // Switches
  if (domain === 'switch') {
    return to === 'on'
      ? { text: `${name} on`, icon: 'switch' }
      : { text: `${name} off`, icon: 'switch' };
  }

  // Media
  if (domain === 'media_player') {
    if (to === 'playing') return { text: `${name} playing`, icon: 'media' };
    if (to === 'paused') return { text: `${name} paused`, icon: 'media' };
    if (to === 'idle' || to === 'off') return { text: `${name} stopped`, icon: 'media' };
    return { text: `${name}: ${to}`, icon: 'media' };
  }

  // Climate
  if (domain === 'climate') {
    return { text: `${name} set to ${to}`, icon: 'climate' };
  }

  // Cover
  if (domain === 'cover') {
    if (to === 'open') return { text: `${name} opened`, icon: 'cover' };
    if (to === 'closed') return { text: `${name} closed`, icon: 'cover' };
    return { text: `${name}: ${to}`, icon: 'cover' };
  }

  // Fallback
  return { text: `${name}: ${from} → ${to}`, icon: 'default' };
}

const EVENT_ICONS = {
  arrive: '🏠', depart: '👋', person: '👤',
  unlock: '🔓', lock: '🔒',
  motion: '🚶', clear: '·',
  door: '🚪', window: '🪟',
  light_on: '💡', light_off: '·',
  switch: '⚡', sensor: '📡',
  media: '🎵', climate: '🌡️', cover: '🪟',
  default: '·',
};

// ── Section 1: Learning Progress ─────────────────────────────────────

const PHASES = ['collecting', 'baselines', 'ml-training', 'ml-active'];
const PHASE_LABELS = ['Collecting', 'Baselines', 'ML Training', 'ML Active'];

function LearningProgress({ maturity }) {
  if (!maturity) return null;
  const idx = PHASES.indexOf(maturity.phase);
  const pct = Math.max(((idx + 1) / PHASES.length) * 100, 10);

  const whyText = idx < 2
    ? 'The system needs enough data to tell the difference between "normal Tuesday" and "something unusual." More days = better predictions.'
    : 'The system has enough data to predict your home\'s behavior and flag anomalies.';

  return (
    <Section title="Learning Progress">
      <div class="bg-white rounded-lg shadow-sm p-4 space-y-4">
        <div>
          <div class="flex justify-between text-xs text-gray-500 mb-1">
            {PHASE_LABELS.map((label, i) => (
              <span key={label} class={i <= idx ? 'font-bold text-blue-600' : ''}>{label}</span>
            ))}
          </div>
          <div class="h-3 rounded-full bg-gray-200">
            <div
              class="h-3 rounded-full bg-blue-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        <p class="text-sm text-gray-700">{maturity.description}</p>
        <p class="text-xs text-gray-400 italic">{whyText}</p>

        <div class="flex flex-wrap gap-3 text-sm">
          <span class="bg-gray-100 rounded px-2 py-1">{maturity.days_of_data} day{maturity.days_of_data !== 1 ? 's' : ''} of data</span>
          <span class="bg-gray-100 rounded px-2 py-1">{maturity.intraday_count} intraday snapshot{maturity.intraday_count !== 1 ? 's' : ''}</span>
          {maturity.first_date && (
            <span class="bg-gray-100 rounded px-2 py-1">Since {maturity.first_date}</span>
          )}
        </div>

        {maturity.next_milestone && maturity.phase !== 'ml-active' && (
          <p class="text-xs text-gray-500">Next: {maturity.next_milestone}</p>
        )}
      </div>
    </Section>
  );
}

// ── Section 2: Home Right Now ────────────────────────────────────────

function HomeRightNow({ intraday, baselines }) {
  if (!intraday || intraday.length === 0) return null;
  const latest = intraday[intraday.length - 1];

  // Compare to baseline if available
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long' });
  const baseline = baselines && baselines[today];

  function compareToBaseline(key, val) {
    if (val == null || !baseline || !baseline[key]) return null;
    const mean = baseline[key].mean;
    if (mean == null) return null;
    const diff = val - mean;
    const pct = mean > 0 ? Math.round((diff / mean) * 100) : 0;
    if (Math.abs(pct) < 10) return { text: 'typical', color: 'text-gray-400' };
    if (pct > 0) return { text: `+${pct}% vs ${today}`, color: 'text-amber-500' };
    return { text: `${pct}% vs ${today}`, color: 'text-blue-500' };
  }

  const items = [
    { label: 'Power (W)', value: latest.power_watts != null ? latest.power_watts : '—', note: compareToBaseline('power_watts', latest.power_watts) },
    { label: 'Lights On', value: latest.lights_on != null ? latest.lights_on : '—', note: compareToBaseline('lights_on', latest.lights_on) },
    { label: 'Devices Home', value: latest.devices_home != null ? latest.devices_home : '—' },
    { label: 'Unavailable', value: latest.unavailable != null ? latest.unavailable : '—', warning: (latest.unavailable || 0) > 100, note: (latest.unavailable || 0) > 100 ? { text: 'High — check devices', color: 'text-amber-600' } : null },
  ];

  const subtitle = baseline
    ? `Latest snapshot compared to your typical ${today}. Updated every 4 hours (more often when home is active).`
    : 'Latest snapshot of your home. Comparisons to baseline will appear after 7 days of data.';

  return (
    <Section title="Home Right Now" subtitle={subtitle}>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        {items.map((item, i) => (
          <div key={i} class={`bg-white rounded-lg shadow-sm p-4 ${item.warning ? 'border-2 border-amber-500' : ''}`}>
            <div class={`text-2xl font-bold ${item.warning ? 'text-amber-500' : 'text-blue-500'}`}>
              {item.value}
            </div>
            <div class="text-sm text-gray-500 mt-1">{item.label}</div>
            {item.note && (
              <div class={`text-xs mt-1 ${item.note.color}`}>{item.note.text}</div>
            )}
          </div>
        ))}
      </div>
    </Section>
  );
}

// ── Section 2.5: Activity Monitor ────────────────────────────────────

function ActivityTimeline({ windows }) {
  if (!windows || windows.length === 0) return null;

  const now = new Date();
  const sixHoursAgo = new Date(now - 6 * 60 * 60 * 1000).toISOString();
  const recent = windows.filter(w => w.window_start >= sixHoursAgo);

  if (recent.length === 0) return null;

  const maxCount = Math.max(...recent.map(w => w.event_count), 1);
  const totalEvents = recent.reduce((sum, w) => sum + w.event_count, 0);
  const occupiedWindows = recent.filter(w => w.occupancy).length;
  const pctOccupied = recent.length > 0 ? Math.round((occupiedWindows / recent.length) * 100) : 0;

  return (
    <div class="space-y-2">
      <div class="flex justify-between items-baseline">
        <div class="text-xs font-medium text-gray-600">Activity Timeline (6h)</div>
        <div class="text-xs text-gray-400">{totalEvents} events, home {pctOccupied}% of the time</div>
      </div>
      <div class="flex items-end gap-0.5 h-16">
        {recent.map((w, i) => {
          const height = Math.max((w.event_count / maxCount) * 100, 4);
          const color = w.occupancy ? '#7c3aed' : '#9ca3af';
          const time = w.window_start.slice(11, 16);
          return (
            <div
              key={i}
              class="flex-1 rounded-t transition-all"
              style={{ height: `${height}%`, backgroundColor: color, minWidth: '3px' }}
              title={`${time} — ${w.event_count} events${w.occupancy ? '' : ' (away)'}`}
            />
          );
        })}
      </div>
      <div class="flex justify-between text-[10px] text-gray-400">
        <span>{recent[0]?.window_start?.slice(11, 16)}</span>
        <div class="flex items-center gap-2">
          <span class="inline-block w-2 h-2 rounded-sm" style={{ backgroundColor: '#7c3aed' }} /> home
          <span class="inline-block w-2 h-2 rounded-sm" style={{ backgroundColor: '#9ca3af' }} /> away
        </div>
        {recent.length > 1 && <span>{recent[recent.length - 1]?.window_start?.slice(11, 16)}</span>}
      </div>
    </div>
  );
}

function ActivitySection({ activity }) {
  if (!activity) {
    return (
      <Section
        title="Activity Monitor"
        subtitle="Waiting for WebSocket to connect to Home Assistant..."
      >
        <Callout color="gray">Activity monitoring is starting up. State changes will appear here once the WebSocket connection is established.</Callout>
      </Section>
    );
  }

  const summary = activity.activity_summary;
  const log = activity.activity_log;

  if (!summary && !log) {
    return (
      <Section
        title="Activity Monitor"
        subtitle="Waiting for first events..."
      >
        <Callout color="gray">Activity monitoring is starting up. State changes will appear here once the WebSocket connection is established.</Callout>
      </Section>
    );
  }

  const occ = summary?.occupancy || {};
  const rate = summary?.activity_rate || {};
  const snap = summary?.snapshot_status || {};
  const domains = summary?.domains_active_1h || {};
  const recentEvents = summary?.recent_activity || [];
  const windows = log?.windows || [];

  // Build contextual subtitle
  const parts = [];
  if (occ.anyone_home) {
    const dur = durationSince(occ.since);
    parts.push(dur ? `${occ.people.join(' & ')} home for ${dur}` : `${occ.people.join(' & ')} home`);
  } else {
    parts.push('Nobody home');
  }
  if (rate.trend === 'increasing') parts.push('activity picking up');
  else if (rate.trend === 'decreasing') parts.push('quieting down');
  const eventsToday = log?.events_today;
  if (eventsToday != null) parts.push(`${eventsToday} events today`);
  const contextSubtitle = parts.join(' · ');

  // Determine snapshot status message
  let snapMsg = '';
  if (snap.today_count > 0) {
    snapMsg = `${snap.today_count} adaptive snapshot${snap.today_count !== 1 ? 's' : ''} captured today — the system saw enough activity to grab extra data points.`;
  } else if (occ.anyone_home) {
    snapMsg = 'Watching for sustained activity to trigger an adaptive snapshot (needs 5+ events with 30m cooldown).';
  } else {
    snapMsg = 'Adaptive snapshots only trigger when someone is home.';
  }

  return (
    <Section title="Activity Monitor" subtitle={contextSubtitle}>
      <div class="space-y-4">

        {/* Status bar */}
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          {/* Occupancy */}
          <div class={`bg-white rounded-lg shadow-sm p-4 ${occ.anyone_home ? 'border-l-4 border-green-400' : 'border-l-4 border-gray-200'}`}>
            <div class={`text-2xl font-bold ${occ.anyone_home ? 'text-green-600' : 'text-gray-400'}`}>
              {occ.anyone_home ? 'Home' : 'Away'}
            </div>
            <div class="text-sm text-gray-500 mt-1">Occupancy</div>
            {occ.anyone_home && occ.since && (
              <div class="text-xs text-gray-400 mt-1">for {durationSince(occ.since)}</div>
            )}
          </div>

          {/* Current window */}
          <div class="bg-white rounded-lg shadow-sm p-4">
            <div class="text-2xl font-bold text-blue-500">
              {rate.current != null ? rate.current : '—'}
            </div>
            <div class="text-sm text-gray-500 mt-1">Events (15m window)</div>
            {rate.avg_1h > 0 && (
              <div class={`text-xs mt-1 ${
                rate.trend === 'increasing' ? 'text-amber-500' :
                rate.trend === 'decreasing' ? 'text-blue-500' : 'text-gray-400'
              }`}>
                {rate.trend === 'increasing' ? 'Above' : rate.trend === 'decreasing' ? 'Below' : 'Near'} avg ({rate.avg_1h}/window)
              </div>
            )}
          </div>

          {/* Today total */}
          <div class="bg-white rounded-lg shadow-sm p-4">
            <div class="text-2xl font-bold text-blue-500">
              {eventsToday != null ? eventsToday : '—'}
            </div>
            <div class="text-sm text-gray-500 mt-1">Events Today</div>
          </div>

          {/* Snapshots */}
          <div class="bg-white rounded-lg shadow-sm p-4">
            <div class="text-2xl font-bold text-blue-500">
              {snap.today_count != null ? `${snap.today_count}/${snap.daily_cap}` : '—'}
            </div>
            <div class="text-sm text-gray-500 mt-1">Adaptive Snapshots</div>
            {snap.cooldown_remaining_s > 0 && (
              <div class="text-xs text-gray-400 mt-1">Next eligible in {Math.ceil(snap.cooldown_remaining_s / 60)}m</div>
            )}
          </div>
        </div>

        {/* Snapshot context */}
        <div class="text-xs text-gray-400 italic px-1">{snapMsg}</div>

        {/* Recent Activity + Domains side by side */}
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">

          {/* Recent Activity — 2/3 width */}
          <div class="md:col-span-2 bg-white rounded-lg shadow-sm p-4">
            <div class="text-xs font-bold text-gray-500 uppercase mb-2">What Just Happened</div>
            {recentEvents.length === 0 ? (
              <p class="text-sm text-gray-400">Waiting for state changes...</p>
            ) : (
              <div class="space-y-0.5 max-h-64 overflow-y-auto">
                {recentEvents.map((evt, i) => {
                  const desc = describeEvent(evt);
                  const icon = EVENT_ICONS[desc.icon] || '·';
                  const isSignificant = ['lock', 'person', 'device_tracker'].includes(evt.domain)
                    || (evt.domain === 'binary_sensor' && ['door', 'window'].includes(evt.device_class));
                  return (
                    <div key={i} class={`flex items-center gap-2 py-1 px-1 rounded ${isSignificant ? 'bg-amber-50' : ''}`}>
                      <span class="w-5 text-center text-sm flex-shrink-0">{icon}</span>
                      <span class={`flex-1 text-sm ${isSignificant ? 'font-medium text-gray-900' : 'text-gray-600'}`}>
                        {desc.text}
                      </span>
                      <span class="text-xs text-gray-400 flex-shrink-0">{evt.time}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Domain breakdown — 1/3 width */}
          <div class="bg-white rounded-lg shadow-sm p-4">
            <div class="text-xs font-bold text-gray-500 uppercase mb-2">Active Domains (1h)</div>
            {Object.keys(domains).length === 0 ? (
              <p class="text-sm text-gray-400">No activity yet.</p>
            ) : (
              <div class="space-y-2">
                {Object.entries(domains).map(([domain, count]) => {
                  const label = DOMAIN_LABELS[domain] || domain;
                  const maxDomain = Math.max(...Object.values(domains));
                  const pct = maxDomain > 0 ? (count / maxDomain) * 100 : 0;
                  return (
                    <div key={domain} class="space-y-0.5">
                      <div class="flex justify-between text-xs">
                        <span class="text-gray-600">{label}</span>
                        <span class="text-gray-400">{count}</span>
                      </div>
                      <div class="h-1.5 bg-gray-100 rounded-full">
                        <div class="h-1.5 bg-purple-400 rounded-full" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Timeline */}
        <div class="bg-white rounded-lg shadow-sm p-4">
          <ActivityTimeline windows={windows} />
          {windows.length === 0 && (
            <p class="text-sm text-gray-400">Timeline will appear after the first 15-minute window.</p>
          )}
        </div>

        {/* Snapshot Log */}
        {snap.log_today && snap.log_today.length > 0 && (
          <details class="bg-white rounded-lg shadow-sm">
            <summary class="px-4 py-3 cursor-pointer text-sm font-medium text-gray-700 hover:bg-gray-50">
              Snapshot Log — {snap.log_today.length} adaptive snapshot{snap.log_today.length !== 1 ? 's' : ''} today
            </summary>
            <div class="overflow-x-auto">
              <table class="w-full text-sm">
                <thead>
                  <tr class="border-b border-gray-100 text-left text-xs text-gray-500">
                    <th class="px-4 py-1">#</th>
                    <th class="px-4 py-1">Time</th>
                    <th class="px-4 py-1">Events</th>
                    <th class="px-4 py-1">People</th>
                    <th class="px-4 py-1">What Triggered It</th>
                  </tr>
                </thead>
                <tbody>
                  {snap.log_today.map((entry, i) => (
                    <tr key={i} class="border-b border-gray-50">
                      <td class="px-4 py-1.5 text-gray-400">{entry.number}</td>
                      <td class="px-4 py-1.5 text-gray-600">{entry.timestamp?.slice(11, 16)}</td>
                      <td class="px-4 py-1.5">{entry.buffered_events} buffered</td>
                      <td class="px-4 py-1.5 text-gray-600">{(entry.people || []).join(', ') || '—'}</td>
                      <td class="px-4 py-1.5">
                        <div class="flex flex-wrap gap-1">
                          {Object.entries(entry.domains || {}).slice(0, 4).map(([d, c]) => (
                            <span key={d} class="bg-gray-100 rounded px-1.5 py-0.5 text-xs">
                              {DOMAIN_LABELS[d] || d}: {c}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </div>
    </Section>
  );
}

// ── Section 3: Trends Over Time ──────────────────────────────────────

function BarChart({ data, dataKey, label, color }) {
  if (!data || data.length === 0) return null;
  const values = data.map(d => d[dataKey]).filter(v => v != null);
  const max = Math.max(...values, 1);

  return (
    <div class="space-y-1">
      <div class="text-xs font-medium text-gray-600">{label}</div>
      <div class="flex items-end gap-1 h-12">
        {data.map((d, i) => {
          const val = d[dataKey];
          if (val == null) return <div key={i} class="flex-1" />;
          const height = Math.max((val / max) * 100, 4);
          return (
            <div
              key={i}
              class="flex-1 rounded-t transition-all"
              style={{ height: `${height}%`, backgroundColor: color, minWidth: '4px' }}
              title={`${d.date || 'h' + d.hour}: ${val}`}
            />
          );
        })}
      </div>
      <div class="flex justify-between text-[10px] text-gray-400">
        <span>{data[0]?.date || ('h' + data[0]?.hour)}</span>
        {data.length > 1 && <span>{data[data.length - 1]?.date || ('h' + data[data.length - 1]?.hour)}</span>}
      </div>
    </div>
  );
}

function TrendsOverTime({ trendData, intradayTrend }) {
  const hasTrend = trendData && trendData.length > 0;
  const hasIntraday = intradayTrend && intradayTrend.length > 0;

  if (!hasTrend && !hasIntraday) {
    return (
      <Section
        title="Trends Over Time"
        subtitle="Spot when something changed — a new device, a routine shift, or a problem building."
      >
        <Callout>No trend data yet. Daily snapshots are collected each night at 11:30 PM.</Callout>
      </Section>
    );
  }

  // Detect notable changes in daily trend
  let trendNote = null;
  if (hasTrend && trendData.length >= 2) {
    const last = trendData[trendData.length - 1];
    const prev = trendData[trendData.length - 2];
    const changes = [];
    if (last.power_watts != null && prev.power_watts != null) {
      const d = last.power_watts - prev.power_watts;
      if (Math.abs(d) > 50) changes.push(`Power ${d > 0 ? 'up' : 'down'} ${Math.abs(Math.round(d))}W vs yesterday`);
    }
    if (last.unavailable != null && prev.unavailable != null) {
      const d = last.unavailable - prev.unavailable;
      if (d > 10) changes.push(`${d} more entities unavailable than yesterday — check your network`);
    }
    if (changes.length > 0) trendNote = changes.join('. ') + '.';
  }

  return (
    <Section
      title="Trends Over Time"
      subtitle="Spot when something changed — a new device, a routine shift, or a problem building. Each bar is one day."
    >
      {trendNote && <Callout color="amber">{trendNote}</Callout>}
      <div class="bg-white rounded-lg shadow-sm p-4 space-y-4">
        {hasTrend && (
          <div class="space-y-3">
            <div class="text-xs font-bold text-gray-500 uppercase">Daily</div>
            <BarChart data={trendData} dataKey="power_watts" label="Power (W) — total household draw" color="#3b82f6" />
            <BarChart data={trendData} dataKey="lights_on" label="Lights On — how many at snapshot time" color="#f59e0b" />
            <BarChart data={trendData} dataKey="unavailable" label="Unavailable — entities not responding (should be low)" color="#ef4444" />
          </div>
        )}
        {hasIntraday && (
          <div class="space-y-3">
            <div class="text-xs font-bold text-gray-500 uppercase">Today (Intraday)</div>
            <BarChart data={intradayTrend} dataKey="power_watts" label="Power (W)" color="#6366f1" />
            <BarChart data={intradayTrend} dataKey="unavailable" label="Unavailable" color="#f43f5e" />
          </div>
        )}
      </div>
    </Section>
  );
}

// ── Section 4: Predictions vs Actuals ────────────────────────────────

function PredictionsVsActuals({ predictions, intradayTrend }) {
  if (!predictions || !predictions.target_date) {
    return (
      <Section
        title="Predictions vs Actuals"
        subtitle="Once active, large deltas here mean something unusual is happening — worth investigating."
      >
        <Callout>Predictions need at least 7 days of data. The system is still learning what "normal" looks like for each day of the week.</Callout>
      </Section>
    );
  }

  const latest = intradayTrend && intradayTrend.length > 0 ? intradayTrend[intradayTrend.length - 1] : {};
  const metrics = ['power_watts', 'lights_on', 'devices_home', 'unavailable', 'useful_events'];

  // Find biggest delta for callout
  let biggestDelta = null;
  metrics.forEach(m => {
    const pred = predictions[m] || {};
    const actual = latest[m];
    if (actual != null && pred.predicted != null && pred.predicted > 0) {
      const pct = Math.abs((actual - pred.predicted) / pred.predicted * 100);
      if (pct > 30 && (!biggestDelta || pct > biggestDelta.pct)) {
        biggestDelta = { metric: m.replace(/_/g, ' '), pct: Math.round(pct), actual, predicted: pred.predicted };
      }
    }
  });

  return (
    <Section
      title="Predictions vs Actuals"
      subtitle="Large deltas mean something unusual is happening. Small deltas mean the system understands your patterns."
    >
      {biggestDelta && (
        <Callout color="amber">
          {biggestDelta.metric} is {biggestDelta.pct}% off prediction ({biggestDelta.actual} actual vs {biggestDelta.predicted} predicted). Worth a look?
        </Callout>
      )}
      <div class="bg-white rounded-lg shadow-sm overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
              <th class="px-4 py-2">Metric</th>
              <th class="px-4 py-2">Predicted</th>
              <th class="px-4 py-2">Actual</th>
              <th class="px-4 py-2">Delta</th>
              <th class="px-4 py-2">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map(m => {
              const pred = predictions[m] || {};
              const actual = latest[m];
              const delta = actual != null && pred.predicted != null
                ? Math.round((actual - pred.predicted) * 10) / 10
                : null;
              const bigDelta = delta != null && pred.predicted > 0 && Math.abs(delta / pred.predicted) > 0.3;
              return (
                <tr key={m} class={`border-b border-gray-100 ${bigDelta ? 'bg-amber-50' : ''}`}>
                  <td class="px-4 py-2 font-medium text-gray-700">{m.replace(/_/g, ' ')}</td>
                  <td class="px-4 py-2">{pred.predicted != null ? pred.predicted : '—'}</td>
                  <td class="px-4 py-2">{actual != null ? actual : '—'}</td>
                  <td class="px-4 py-2">{delta != null ? (delta >= 0 ? '+' : '') + delta : '—'}</td>
                  <td class="px-4 py-2">
                    <span class={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${confidenceColor(pred.confidence)}`}>
                      {pred.confidence || 'n/a'}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

// ── Section 5: Baselines ─────────────────────────────────────────────

const DAYS_ORDER = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

function Baselines({ baselines }) {
  if (!baselines || Object.keys(baselines).length === 0) {
    return (
      <Section
        title="Baselines"
        subtitle="This is what 'normal' looks like for each day. Deviations from these numbers trigger anomaly detection."
      >
        <Callout>No baselines yet. The first baseline is calculated after the first daily snapshot.</Callout>
      </Section>
    );
  }

  const today = new Date().toLocaleDateString('en-US', { weekday: 'long' });

  return (
    <Section
      title="Baselines"
      subtitle="This is 'normal' for each day of the week. The system flags deviations from these averages. More samples = tighter predictions."
    >
      <div class="bg-white rounded-lg shadow-sm overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
              <th class="px-4 py-2">Day</th>
              <th class="px-4 py-2">Samples</th>
              <th class="px-4 py-2">Power (W)</th>
              <th class="px-4 py-2">Lights</th>
              <th class="px-4 py-2">Devices</th>
              <th class="px-4 py-2">Unavail</th>
            </tr>
          </thead>
          <tbody>
            {DAYS_ORDER.map(day => {
              const b = baselines[day];
              const isToday = day === today;
              if (!b) {
                return (
                  <tr key={day} class="border-b border-gray-100 text-gray-300">
                    <td class="px-4 py-2">{day}{isToday ? ' (today)' : ''}</td>
                    <td class="px-4 py-2" colSpan="5">no data</td>
                  </tr>
                );
              }
              return (
                <tr key={day} class={`border-b border-gray-100 ${isToday ? 'bg-blue-50' : ''}`}>
                  <td class="px-4 py-2 font-medium text-gray-700">{day}{isToday ? ' (today)' : ''}</td>
                  <td class="px-4 py-2">{b.sample_count}</td>
                  <td class="px-4 py-2">{b.power_watts?.mean != null ? Math.round(b.power_watts.mean * 10) / 10 : '—'}</td>
                  <td class="px-4 py-2">{b.lights_on?.mean != null ? Math.round(b.lights_on.mean) : '—'}</td>
                  <td class="px-4 py-2">{b.devices_home?.mean != null ? Math.round(b.devices_home.mean) : '—'}</td>
                  <td class="px-4 py-2">{b.unavailable?.mean != null ? Math.round(b.unavailable.mean) : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

// ── Section 6: Daily Insight ─────────────────────────────────────────

function DailyInsight({ insight }) {
  if (!insight) {
    return (
      <Section
        title="Daily Insight"
        subtitle="An AI-generated analysis of your home's patterns. Generated each night at 11:30 PM from the day's data."
      >
        <Callout>No insight report yet. The first report is generated after the first full pipeline run.</Callout>
      </Section>
    );
  }

  const lines = (insight.report || '').split('\n');

  return (
    <Section
      title="Daily Insight"
      subtitle="AI analysis of what happened yesterday and what to watch for. Generated nightly from your full data set."
    >
      <div class="bg-white rounded-lg shadow-sm p-4">
        <span class="inline-block bg-gray-100 rounded px-2 py-0.5 text-xs text-gray-500 mb-3">{insight.date}</span>
        <div class="prose prose-sm max-w-none text-gray-700 space-y-2">
          {lines.map((line, i) => {
            if (line.startsWith('###')) return <h3 key={i} class="text-sm font-bold text-gray-900 mt-3">{line.replace(/^###\s*/, '')}</h3>;
            if (line.trim() === '') return null;
            return <p key={i} class="text-sm leading-relaxed">{line}</p>;
          })}
        </div>
      </div>
    </Section>
  );
}

// ── Section 7: Correlations ──────────────────────────────────────────

function Correlations({ correlations }) {
  const hasData = correlations && correlations.length > 0;

  return (
    <Section
      title="Correlations"
      subtitle={hasData
        ? 'Devices that change together. Strong correlations suggest automation opportunities or shared failure modes.'
        : 'Devices that tend to change together — useful for creating automations or finding shared failure points.'
      }
    >
      {!hasData ? (
        <Callout>No correlations yet. Needs enough data to detect statistically reliable relationships between devices.</Callout>
      ) : (
        <div class="bg-white rounded-lg shadow-sm overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-gray-200 text-left text-xs text-gray-500 uppercase">
                <th class="px-4 py-2">Entity A</th>
                <th class="px-4 py-2">Entity B</th>
                <th class="px-4 py-2">Strength</th>
                <th class="px-4 py-2">Direction</th>
              </tr>
            </thead>
            <tbody>
              {correlations.map((c, i) => (
                <tr key={i} class="border-b border-gray-100">
                  <td class="px-4 py-2 font-mono text-xs">{c.entity_a || c[0]}</td>
                  <td class="px-4 py-2 font-mono text-xs">{c.entity_b || c[1]}</td>
                  <td class="px-4 py-2">{c.strength || c[2]}</td>
                  <td class="px-4 py-2">{c.direction || c[3] || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

// ── Section 8: System Status ─────────────────────────────────────────

function SystemStatus({ runLog, mlModels, metaLearning }) {
  // Determine overall health
  const hasErrors = runLog && runLog.some(r => r.status === 'error');
  const lastRun = runLog && runLog.length > 0 ? runLog[0] : null;
  const healthNote = hasErrors
    ? 'Errors detected in recent runs — the pipeline may be missing data.'
    : lastRun
      ? `Last run ${relativeTime(lastRun.timestamp)}. Everything healthy.`
      : 'No runs recorded yet.';

  return (
    <Section
      title="System Status"
      subtitle={`If something is red here, the intelligence pipeline is broken and won't catch issues in your home. ${healthNote}`}
    >
      <div class="space-y-4">
        {/* Run Log */}
        <div class="bg-white rounded-lg shadow-sm overflow-x-auto">
          <div class="px-4 py-2 border-b border-gray-200 text-xs font-bold text-gray-500 uppercase">Run Log</div>
          {(!runLog || runLog.length === 0) ? (
            <div class="px-4 py-3 text-sm text-gray-400">No runs recorded yet.</div>
          ) : (
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-gray-100 text-left text-xs text-gray-500">
                  <th class="px-4 py-1">When</th>
                  <th class="px-4 py-1">Type</th>
                  <th class="px-4 py-1">Status</th>
                </tr>
              </thead>
              <tbody>
                {runLog.map((r, i) => (
                  <tr key={i} class="border-b border-gray-50">
                    <td class="px-4 py-1.5 text-gray-600" title={r.timestamp}>{relativeTime(r.timestamp)}</td>
                    <td class="px-4 py-1.5">
                      <span class="bg-gray-100 rounded px-1.5 py-0.5 text-xs">{r.type}</span>
                    </td>
                    <td class="px-4 py-1.5">
                      <span class={`inline-block w-2 h-2 rounded-full ${r.status === 'ok' ? 'bg-green-500' : 'bg-red-500'}`} />
                      {r.message && <span class="ml-1 text-xs text-red-600">{r.message}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* ML Models */}
        <div class="bg-white rounded-lg shadow-sm p-4">
          <div class="text-xs font-bold text-gray-500 uppercase mb-2">ML Models</div>
          {(!mlModels || mlModels.count === 0) ? (
            <p class="text-sm text-gray-400">ML models activate after 14 days of data. Until then, predictions use statistical baselines only.</p>
          ) : (
            <div class="space-y-2">
              <div class="flex gap-3 text-sm">
                <span class="bg-gray-100 rounded px-2 py-0.5">{mlModels.count} model{mlModels.count !== 1 ? 's' : ''}</span>
                {mlModels.last_trained && <span class="text-gray-500">Last trained: {relativeTime(mlModels.last_trained)}</span>}
              </div>
              {mlModels.scores && Object.keys(mlModels.scores).length > 0 && (
                <table class="w-full text-xs">
                  <thead>
                    <tr class="text-left text-gray-500"><th class="py-1">Model</th><th>R2</th><th>MAE</th></tr>
                  </thead>
                  <tbody>
                    {Object.entries(mlModels.scores).map(([name, s]) => (
                      <tr key={name}>
                        <td class="py-1 font-mono">{name}</td>
                        <td>{s.r2 != null ? s.r2.toFixed(3) : '—'}</td>
                        <td>{s.mae != null ? s.mae.toFixed(2) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>

        {/* Meta-Learning */}
        <div class="bg-white rounded-lg shadow-sm p-4">
          <div class="text-xs font-bold text-gray-500 uppercase mb-2">Meta-Learning</div>
          {(!metaLearning || metaLearning.applied_count === 0) ? (
            <p class="text-sm text-gray-400">Meta-learning reviews model performance weekly and auto-tunes feature selection. Activates after the first training cycle.</p>
          ) : (
            <div class="space-y-2">
              <div class="flex gap-3 text-sm">
                <span class="bg-gray-100 rounded px-2 py-0.5">{metaLearning.applied_count} suggestion{metaLearning.applied_count !== 1 ? 's' : ''} applied</span>
                {metaLearning.last_applied && <span class="text-gray-500">Last: {relativeTime(metaLearning.last_applied)}</span>}
              </div>
              {metaLearning.suggestions && metaLearning.suggestions.length > 0 && (
                <ul class="text-xs text-gray-600 space-y-1 list-disc ml-4">
                  {metaLearning.suggestions.map((s, i) => (
                    <li key={i}>{s.description || s.action || JSON.stringify(s)}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </Section>
  );
}

// ── Section 9: Configuration ─────────────────────────────────────────

function Configuration({ config }) {
  if (!config) return null;

  const featureGroups = {};
  if (config.feature_config) {
    for (const [key, val] of Object.entries(config.feature_config)) {
      const group = key.replace(/_features?$/, '').replace(/_/g, ' ');
      featureGroups[group] = val;
    }
  }

  return (
    <Section
      title="Configuration"
      subtitle="Current engine settings. Edit ~/ha-logs/intelligence/feature_config.json to change."
    >
      <details class="bg-white rounded-lg shadow-sm">
        <summary class="px-4 py-3 cursor-pointer text-sm font-medium text-gray-700 hover:bg-gray-50">
          Show configuration details
        </summary>
        <div class="px-4 pb-4 space-y-4">
          <div>
            <div class="text-xs font-bold text-gray-500 uppercase mb-1">ML Weight Schedule</div>
            <table class="text-xs w-full">
              <thead>
                <tr class="text-left text-gray-500"><th class="py-1">Days of Data</th><th>ML Weight</th></tr>
              </thead>
              <tbody>
                {config.ml_weight_schedule && Object.entries(config.ml_weight_schedule).map(([range, weight]) => (
                  <tr key={range}>
                    <td class="py-1">{range}</td>
                    <td>{(weight * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <div class="text-xs font-bold text-gray-500 uppercase mb-1">Anomaly Threshold</div>
            <p class="text-sm text-gray-700">{config.anomaly_threshold} standard deviations from baseline triggers an anomaly flag.</p>
          </div>

          <div>
            <div class="text-xs font-bold text-gray-500 uppercase mb-1">Feature Toggles</div>
            <div class="flex flex-wrap gap-2">
              {Object.entries(featureGroups).map(([name, enabled]) => (
                <span
                  key={name}
                  class={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                    enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'
                  }`}
                >
                  {name}: {enabled ? 'on' : 'off'}
                </span>
              ))}
            </div>
          </div>
        </div>
      </details>
    </Section>
  );
}

// ── Main Page ────────────────────────────────────────────────────────

export default function Intelligence() {
  const { data, loading, error, refetch } = useCache('intelligence');

  const intel = useComputed(() => {
    if (!data || !data.data) return null;
    return data.data;
  }, [data]);

  if (loading && !data) {
    return (
      <div class="space-y-6">
        <h1 class="text-2xl font-bold text-gray-900">Intelligence</h1>
        <LoadingState type="cards" />
      </div>
    );
  }

  if (error) {
    return (
      <div class="space-y-6">
        <h1 class="text-2xl font-bold text-gray-900">Intelligence</h1>
        <ErrorState error={error} onRetry={refetch} />
      </div>
    );
  }

  if (!intel) {
    return (
      <div class="space-y-6">
        <h1 class="text-2xl font-bold text-gray-900">Intelligence</h1>
        <Callout>Intelligence data is loading. The engine collects its first snapshot automatically via cron.</Callout>
      </div>
    );
  }

  return (
    <div class="space-y-8">
      <h1 class="text-2xl font-bold text-gray-900">Intelligence</h1>

      <LearningProgress maturity={intel.data_maturity} />
      <HomeRightNow intraday={intel.intraday_trend} baselines={intel.baselines} />
      <ActivitySection activity={intel.activity} />
      <TrendsOverTime trendData={intel.trend_data} intradayTrend={intel.intraday_trend} />
      <PredictionsVsActuals predictions={intel.predictions} intradayTrend={intel.intraday_trend} />
      <Baselines baselines={intel.baselines} />
      <DailyInsight insight={intel.daily_insight} />
      <Correlations correlations={intel.correlations} />
      <SystemStatus runLog={intel.run_log} mlModels={intel.ml_models} metaLearning={intel.meta_learning} />
      <Configuration config={intel.config} />
    </div>
  );
}
