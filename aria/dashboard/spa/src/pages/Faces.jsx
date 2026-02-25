import { useState, useEffect } from 'preact/hooks';

export default function Faces() {
  const [stats, setStats] = useState({ queue_depth: 0, known_people: 0 });
  const [queue, setQueue] = useState([]);
  const [people, setPeople] = useState([]);
  const [labelInput, setLabelInput] = useState({});
  const [bootstrapRunning, setBootstrapRunning] = useState(false);
  const [error, setError] = useState(null);

  async function fetchData() {
    try {
      const [statsRes, queueRes, peopleRes] = await Promise.all([
        fetch('/api/faces/stats'),
        fetch('/api/faces/queue?limit=20'),
        fetch('/api/faces/people'),
      ]);
      setStats(await statsRes.json());
      const queueData = await queueRes.json();
      setQueue(queueData.items || []);
      const peopleData = await peopleRes.json();
      setPeople(peopleData.people || []);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { fetchData(); }, []);

  async function handleLabel(queueId) {
    const name = labelInput[queueId]?.trim();
    if (!name) return;
    await fetch('/api/faces/label', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ queue_id: queueId, person_name: name }),
    });
    setLabelInput(prev => ({ ...prev, [queueId]: '' }));
    fetchData();
  }

  async function handleBootstrap() {
    setBootstrapRunning(true);
    await fetch('/api/faces/bootstrap', { method: 'POST' });
    setTimeout(() => { setBootstrapRunning(false); fetchData(); }, 3000);
  }

  async function handleDeploy() {
    await fetch('/api/faces/deploy', { method: 'POST' });
    alert('Deployed to Frigate — restart Frigate to reload face library.');
  }

  return (
    <div class="p-4 max-w-4xl mx-auto">
      <h1 class="text-2xl font-bold mb-4">Face Recognition</h1>

      {error && <div class="text-red-500 mb-4">{error}</div>}

      {/* Stats */}
      <div class="grid grid-cols-2 gap-4 mb-6">
        <div class="bg-gray-800 rounded p-4 text-center">
          <div class="text-3xl font-bold text-yellow-400">{stats.queue_depth}</div>
          <div class="text-sm text-gray-400">Pending review</div>
        </div>
        <div class="bg-gray-800 rounded p-4 text-center">
          <div class="text-3xl font-bold text-green-400">{stats.known_people}</div>
          <div class="text-sm text-gray-400">Known people</div>
        </div>
      </div>

      {/* Bootstrap */}
      <div class="bg-gray-800 rounded p-4 mb-6">
        <h2 class="text-lg font-semibold mb-2">Bootstrap from Frigate Clips</h2>
        <p class="text-sm text-gray-400 mb-3">
          Run once to extract and cluster faces from all existing snapshots.
          Then label each cluster below.
        </p>
        <div class="flex gap-2">
          <button
            onClick={handleBootstrap}
            disabled={bootstrapRunning}
            class="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-4 py-2 rounded text-sm"
          >
            {bootstrapRunning ? 'Running...' : 'Run Bootstrap'}
          </button>
          <button
            onClick={handleDeploy}
            class="bg-green-600 hover:bg-green-700 px-4 py-2 rounded text-sm"
          >
            Deploy to Frigate
          </button>
        </div>
      </div>

      {/* Review Queue */}
      {queue.length > 0 && (
        <div class="mb-6">
          <h2 class="text-lg font-semibold mb-3">Review Queue ({stats.queue_depth})</h2>
          <div class="space-y-3">
            {queue.map(item => (
              <div key={item.id} class="bg-gray-800 rounded p-3 flex gap-3 items-start">
                <img
                  src={`/api/events/${item.event_id}/snapshot.jpg`}
                  class="w-20 h-20 object-cover rounded"
                  onError={e => { e.target.style.display = 'none'; }}
                />
                <div class="flex-1">
                  <div class="text-xs text-gray-400 mb-1">Priority: {item.priority?.toFixed(2)}</div>
                  {item.top_candidates?.map(cand => (
                    <div key={cand.name} class="text-sm text-gray-300">
                      {cand.name}: {(cand.confidence * 100).toFixed(0)}%
                    </div>
                  ))}
                  <div class="flex gap-2 mt-2">
                    <input
                      type="text"
                      placeholder="Name or skip"
                      value={labelInput[item.id] || ''}
                      onInput={e => setLabelInput(prev => ({ ...prev, [item.id]: e.target.value }))}
                      class="bg-gray-700 px-2 py-1 rounded text-sm flex-1"
                    />
                    <button
                      onClick={() => handleLabel(item.id)}
                      class="bg-blue-600 hover:bg-blue-700 px-3 py-1 rounded text-sm"
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

      {/* People Roster */}
      {people.length > 0 && (
        <div>
          <h2 class="text-lg font-semibold mb-3">Known People</h2>
          <div class="grid grid-cols-2 gap-2">
            {people.map(person => (
              <div key={person.person_name} class="bg-gray-800 rounded p-3 flex justify-between">
                <span class="font-medium">{person.person_name}</span>
                <span class="text-gray-400 text-sm">{person.count} samples</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
