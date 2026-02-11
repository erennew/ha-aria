import { useState, useEffect } from 'preact/hooks';
import useCache from '../hooks/useCache.js';
import useComputed from '../hooks/useComputed.js';
import { fetchJson } from '../api.js';
import StatsGrid from '../components/StatsGrid.jsx';
import DataTable from '../components/DataTable.jsx';
import LoadingState from '../components/LoadingState.jsx';
import ErrorState from '../components/ErrorState.jsx';

export default function Home() {
  const entities = useCache('entities');
  const devices = useCache('devices');
  const areas = useCache('areas');
  const capabilities = useCache('capabilities');

  // Direct API fetches for health and events
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [events, setEvents] = useState(null);
  const [eventsError, setEventsError] = useState(null);

  useEffect(() => {
    fetchJson('/health')
      .then((d) => { setHealth(d); setHealthError(null); })
      .catch((err) => setHealthError(err.message || String(err)));
  }, []);

  useEffect(() => {
    fetchJson('/api/events?limit=20')
      .then((d) => { setEvents(d); setEventsError(null); })
      .catch((err) => setEventsError(err.message || String(err)));
  }, []);

  const cacheLoading = entities.loading || devices.loading || areas.loading || capabilities.loading;
  const cacheError = entities.error || devices.error || areas.error || capabilities.error;

  // Stats
  const stats = useComputed(() => {
    if (!entities.data || !devices.data || !areas.data || !capabilities.data) return null;

    const entityCount = Object.keys(entities.data.data || {}).length;
    const deviceCount = Object.keys(devices.data.data || {}).length;
    const areaCount = Object.keys(areas.data.data || {}).length;
    const capCount = Object.keys(capabilities.data.data || {}).length;
    const moduleCount = health ? Object.keys(health.modules || {}).length : 0;

    return [
      { label: 'Entities', value: entityCount.toLocaleString() },
      { label: 'Devices', value: deviceCount.toLocaleString() },
      { label: 'Areas', value: areaCount.toLocaleString() },
      { label: 'Capabilities', value: capCount.toLocaleString() },
      { label: 'Modules', value: moduleCount },
    ];
  }, [entities.data, devices.data, areas.data, capabilities.data, health]);

  // Module list from health
  const modules = useComputed(() => {
    if (!health || !health.modules) return [];
    return Object.entries(health.modules).map(([name, info]) => ({
      name,
      registered: info.registered,
    }));
  }, [health]);

  // Events table data
  const eventRows = useComputed(() => {
    if (!events || !events.events) return [];
    return events.events.map((e) => ({
      id: e.id,
      time: e.timestamp ? new Date(e.timestamp).toLocaleString() : '\u2014',
      type: e.event_type || '\u2014',
      category: e.category || '\u2014',
      details: e.data ? JSON.stringify(e.data).slice(0, 120) : '\u2014',
    }));
  }, [events]);

  const eventColumns = [
    { key: 'time', label: 'Time', sortable: true },
    { key: 'type', label: 'Type', sortable: true },
    { key: 'category', label: 'Category', sortable: true },
    { key: 'details', label: 'Details', className: 'max-w-xs truncate' },
  ];

  if (cacheLoading && !entities.data) {
    return (
      <div class="space-y-6">
        <h1 class="text-2xl font-bold text-gray-900">Dashboard</h1>
        <LoadingState type="full" />
      </div>
    );
  }

  if (cacheError) {
    return (
      <div class="space-y-6">
        <h1 class="text-2xl font-bold text-gray-900">Dashboard</h1>
        <ErrorState error={cacheError} onRetry={() => { entities.refetch(); devices.refetch(); areas.refetch(); capabilities.refetch(); }} />
      </div>
    );
  }

  return (
    <div class="space-y-6">
      <h1 class="text-2xl font-bold text-gray-900">Dashboard</h1>

      {/* Stats */}
      {stats ? <StatsGrid items={stats} /> : <LoadingState type="stats" />}

      {/* Module Health */}
      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-4">Module Health</h2>
        {healthError ? (
          <ErrorState error={healthError} onRetry={() => fetchJson('/health').then((d) => { setHealth(d); setHealthError(null); }).catch((e) => setHealthError(e.message))} />
        ) : modules.length === 0 ? (
          <div class="bg-white rounded-lg shadow-sm p-4 text-sm text-gray-500">Loading module data...</div>
        ) : (
          <div class="bg-white rounded-lg shadow-sm p-4">
            <div class="flex flex-wrap gap-4">
              {modules.map((m) => (
                <div key={m.name} class="flex items-center gap-2">
                  <span class={`inline-block w-2.5 h-2.5 rounded-full ${m.registered ? 'bg-green-500' : 'bg-red-500'}`} />
                  <span class="text-sm text-gray-700">{m.name}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Cache Categories */}
      {health && health.cache && health.cache.categories && (
        <section>
          <h2 class="text-lg font-semibold text-gray-900 mb-4">Cache Categories</h2>
          <div class="bg-white rounded-lg shadow-sm p-4">
            <div class="flex flex-wrap gap-3">
              {health.cache.categories.map((cat) => {
                // Try to find last_updated from the loaded cache data
                const cacheMap = { entities, devices, areas, capabilities };
                const catData = cacheMap[cat];
                const lastUpdated = catData && catData.data ? catData.data.last_updated : null;

                return (
                  <div key={cat} class="flex items-center gap-2 bg-gray-50 rounded px-3 py-1.5">
                    <span class="text-sm font-medium text-gray-700">{cat}</span>
                    {lastUpdated && (
                      <span class="text-xs text-gray-400">
                        {new Date(lastUpdated).toLocaleTimeString()}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* Recent Events */}
      <section>
        <h2 class="text-lg font-semibold text-gray-900 mb-4">Recent Events</h2>
        {eventsError ? (
          <ErrorState error={eventsError} onRetry={() => fetchJson('/api/events?limit=20').then((d) => { setEvents(d); setEventsError(null); }).catch((e) => setEventsError(e.message))} />
        ) : !events ? (
          <LoadingState type="table" />
        ) : (
          <DataTable
            columns={eventColumns}
            data={eventRows}
            searchFields={['type', 'category', 'details']}
            pageSize={20}
            searchPlaceholder="Search events..."
          />
        )}
      </section>
    </div>
  );
}
