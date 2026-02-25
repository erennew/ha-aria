import { useState, useEffect } from 'preact/hooks';
import { postJson } from '../api.js';
import PageBanner from '../components/PageBanner.jsx';
import LoadingState from '../components/LoadingState.jsx';
import ErrorState from '../components/ErrorState.jsx';

function formatAgo(isoStr) {
  if (!isoStr) return 'Never';
  const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export default function Faces() {
  const [stats, setStats] = useState(null);
  const [queue, setQueue] = useState([]);
  const [people, setPeople] = useState([]);
  const [labelInput, setLabelInput] = useState({});
  const [bootstrapStatus, setBootstrapStatus] = useState({
    running: false, processed: 0, total: 0, startedAt: null, lastRan: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function fetchData() {
    try {
      const [statsRes, queueRes, peopleRes] = await Promise.all([
        fetch('/api/faces/stats'),
        fetch('/api/faces/queue?limit=20'),
        fetch('/api/faces/people'),
      ]);
      if (!statsRes.ok || !queueRes.ok || !peopleRes.ok) throw new Error('API error');
      const [s, q, p] = await Promise.all([statsRes.json(), queueRes.json(), peopleRes.json()]);
      setStats(s);
      setQueue(q.items || []);
      setPeople(p.people || []);
      setError(null);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }

  // Fetch initial data and bootstrap status on mount
  useEffect(() => {
    fetchData();
    fetch('/api/faces/bootstrap/status')
      .then(r => r.json())
      .then(s => setBootstrapStatus({
        running: s.running, processed: s.processed, total: s.total,
        startedAt: s.started_at, lastRan: s.last_ran,
      }))
      .catch(() => {});
  }, []);

  // Poll bootstrap status every 2s while running; refresh data on completion
  useEffect(() => {
    if (!bootstrapStatus.running) return;
    const id = setInterval(() => {
      fetch('/api/faces/bootstrap/status')
        .then(r => r.json())
        .then(s => {
          setBootstrapStatus({
            running: s.running, processed: s.processed, total: s.total,
            startedAt: s.started_at, lastRan: s.last_ran,
          });
          if (!s.running) fetchData();
        })
        .catch(() => {});
    }, 2000);
    return () => clearInterval(id);
  }, [bootstrapStatus.running]);

  async function handleLabel(queueId) {
    const name = labelInput[queueId]?.trim();
    if (!name) return;
    try {
      await postJson('/api/faces/label', { queue_id: queueId, person_name: name });
      setLabelInput(prev => ({ ...prev, [queueId]: '' }));
      fetchData();
    } catch (e) {
      setError(e);
    }
  }

  async function handleBootstrap() {
    try {
      await postJson('/api/faces/bootstrap', {});
      setBootstrapStatus(prev => ({ ...prev, running: true }));
    } catch (e) {
      setError(e);
    }
  }

  async function handleDeploy() {
    try {
      await postJson('/api/faces/deploy', {});
      alert('Deployed to Frigate — restart Frigate to reload face library.');
    } catch (e) {
      setError(e);
    }
  }

  const pct = bootstrapStatus.total > 0
    ? Math.round(bootstrapStatus.processed / bootstrapStatus.total * 100)
    : 0;

  if (loading) return <LoadingState type="stats" />;

  return (
    <div style="max-width: 56rem; margin: 0 auto;">
      <PageBanner page="FACES" subtitle="Face recognition — bootstrap clusters, label identities, deploy to Frigate." />

      {error && (
        <div style="margin-bottom: 1.5rem;">
          <ErrorState error={error} onRetry={fetchData} />
        </div>
      )}

      {/* Stats */}
      <div class="grid grid-cols-2 gap-4" style="margin-bottom: 1.5rem;">
        <div class="t-card" style="padding: 1rem; text-align: center;">
          <div style="font-size: 2rem; font-weight: 700; color: var(--status-active);">
            {stats?.queue_depth ?? 0}
          </div>
          <div style="font-size: var(--type-label); color: var(--text-secondary); margin-top: 0.25rem;">
            Pending review
          </div>
        </div>
        <div class="t-card" style="padding: 1rem; text-align: center;">
          <div style="font-size: 2rem; font-weight: 700; color: var(--status-healthy);">
            {stats?.known_people ?? 0}
          </div>
          <div style="font-size: var(--type-label); color: var(--text-secondary); margin-top: 0.25rem;">
            Known people
          </div>
        </div>
      </div>

      {/* Bootstrap panel */}
      <div class="t-frame" data-label="BOOTSTRAP" style="padding: 1rem; margin-bottom: 1.5rem;">
        <p style="font-size: var(--type-label); color: var(--text-secondary); margin-bottom: 0.75rem;">
          Run once to extract and cluster faces from all existing Frigate snapshots.
          Label each cluster below, then deploy to train Frigate's recogniser.
        </p>
        <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
          <button
            class="t-btn t-btn-primary"
            onClick={handleBootstrap}
            disabled={bootstrapStatus.running}
            style={`padding: 0.5rem 1rem; font-size: 0.875rem; opacity: ${bootstrapStatus.running ? 0.5 : 1};`}
          >
            {bootstrapStatus.running ? 'Running…' : 'Run Bootstrap'}
          </button>
          <button
            class="t-btn t-btn-secondary"
            onClick={handleDeploy}
            style="padding: 0.5rem 1rem; font-size: 0.875rem;"
          >
            Deploy to Frigate
          </button>
        </div>

        {/* Progress bar */}
        {bootstrapStatus.running && (
          <div style="margin-top: 0.75rem;">
            <div style="display: flex; justify-content: space-between; font-size: var(--type-label); color: var(--text-secondary); margin-bottom: 0.25rem;">
              <span>Processing images…</span>
              <span>{bootstrapStatus.processed} / {bootstrapStatus.total}</span>
            </div>
            <div style="background: var(--bg-inset); border-radius: 2px; overflow: hidden; height: 4px;">
              <div style={`background: var(--accent); width: ${pct}%; height: 100%; transition: width 0.5s ease;`} />
            </div>
          </div>
        )}

        {/* Last ran */}
        {!bootstrapStatus.running && bootstrapStatus.lastRan && (
          <div style="margin-top: 0.5rem; font-size: var(--type-label); color: var(--text-secondary);">
            Last ran: {formatAgo(bootstrapStatus.lastRan)}
          </div>
        )}
      </div>

      {/* Review queue */}
      {queue.length > 0 && (
        <div style="margin-bottom: 1.5rem;">
          <div class="t-section-header" style="margin-bottom: 0.75rem;">
            Review Queue ({stats?.queue_depth ?? queue.length})
          </div>
          <div style="display: flex; flex-direction: column; gap: 0.75rem;">
            {queue.map(item => (
              <div key={item.id} class="t-card" style="padding: 0.75rem; display: flex; gap: 0.75rem; align-items: flex-start;">
                <img
                  src={`/api/events/${item.event_id}/snapshot.jpg`}
                  style="width: 5rem; height: 5rem; object-fit: cover; border-radius: var(--radius); flex-shrink: 0; background: var(--bg-inset);"
                  onError={e => { e.target.style.display = 'none'; }}
                />
                <div style="flex: 1; min-width: 0;">
                  <div style="font-size: var(--type-label); color: var(--text-secondary); margin-bottom: 0.25rem;">
                    Uncertainty: {item.priority?.toFixed(2)}
                  </div>
                  {item.top_candidates?.map(cand => (
                    <div key={cand.person_name} style="font-size: 0.875rem; color: var(--text-secondary);">
                      {cand.person_name}
                      <span style="color: var(--accent); margin-left: 0.5rem; font-weight: 600;">
                        {(cand.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                  <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                    <input
                      class="t-input"
                      type="text"
                      placeholder="Name or skip"
                      value={labelInput[item.id] || ''}
                      onInput={e => setLabelInput(prev => ({ ...prev, [item.id]: e.target.value }))}
                      style="flex: 1; font-size: 0.875rem; padding: 0.25rem 0.5rem;"
                    />
                    <button
                      class="t-btn t-btn-primary"
                      onClick={() => handleLabel(item.id)}
                      style="padding: 0.25rem 0.75rem; font-size: 0.875rem;"
                    >
                      Label
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* People roster */}
      {people.length > 0 && (
        <div>
          <div class="t-section-header" style="margin-bottom: 0.75rem;">
            Known People
          </div>
          <div class="grid grid-cols-2 gap-2">
            {people.map(person => (
              <div key={person.person_name} class="t-card" style="padding: 0.75rem; display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 500; color: var(--text-primary);">{person.person_name}</span>
                <span style="font-size: var(--type-label); color: var(--text-secondary);">{person.count} samples</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && queue.length === 0 && people.length === 0 && (
        <div class="t-card" style="padding: 2rem; text-align: center; color: var(--text-secondary);">
          No face data yet. Run bootstrap to get started.
        </div>
      )}
    </div>
  );
}
