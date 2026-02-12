import { useState, useEffect } from 'preact/hooks';
import { fetchJson } from '../api.js';
import LoadingState from '../components/LoadingState.jsx';
import ErrorState from '../components/ErrorState.jsx';

const STAGES = ['backtest', 'shadow', 'suggest', 'autonomous'];
const STAGE_LABELS = ['Backtest', 'Shadow', 'Suggest', 'Autonomous'];

function PipelineStage({ pipeline }) {
  const stage = pipeline?.current_stage || 'backtest';
  const idx = STAGES.indexOf(stage);
  const pct = Math.max(((idx + 1) / STAGES.length) * 100, 10);
  const enteredAt = pipeline?.stage_entered_at;

  return (
    <section class="space-y-3">
      <h2 class="text-lg font-bold text-gray-900">Pipeline Stage</h2>
      <div class="bg-white rounded-lg shadow-sm p-4 space-y-4">
        <div>
          <div class="flex justify-between text-xs text-gray-500 mb-1">
            {STAGE_LABELS.map((label, i) => (
              <span key={label} class={i <= idx ? 'font-bold text-blue-600' : ''}>{label}</span>
            ))}
          </div>
          <div class="h-3 rounded-full bg-gray-200">
            <div class="h-3 rounded-full bg-blue-500 transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>
        {enteredAt && (
          <p class="text-xs text-gray-400">
            In {stage} since {new Date(enteredAt).toLocaleDateString()}
          </p>
        )}
      </div>
    </section>
  );
}

export default function Shadow() {
  const [pipeline, setPipeline] = useState(null);
  const [accuracy, setAccuracy] = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [disagreements, setDisagreements] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function fetchAll() {
    setLoading(true);
    setError(null);
    try {
      const [p, a, pr, d] = await Promise.all([
        fetchJson('/api/pipeline'),
        fetchJson('/api/shadow/accuracy'),
        fetchJson('/api/shadow/predictions?limit=20'),
        fetchJson('/api/shadow/disagreements?limit=10'),
      ]);
      setPipeline(p);
      setAccuracy(a);
      setPredictions(pr);
      setDisagreements(d);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { fetchAll(); }, []);

  if (loading && !pipeline) {
    return (
      <div class="space-y-6">
        <div>
          <h1 class="text-2xl font-bold text-gray-900">Shadow Mode</h1>
          <p class="text-sm text-gray-500">Prediction accuracy, pipeline progress, and learning insights.</p>
        </div>
        <LoadingState type="full" />
      </div>
    );
  }

  if (error) {
    return (
      <div class="space-y-6">
        <div>
          <h1 class="text-2xl font-bold text-gray-900">Shadow Mode</h1>
          <p class="text-sm text-gray-500">Prediction accuracy, pipeline progress, and learning insights.</p>
        </div>
        <ErrorState error={error} onRetry={fetchAll} />
      </div>
    );
  }

  return (
    <div class="space-y-8">
      <div>
        <h1 class="text-2xl font-bold text-gray-900">Shadow Mode</h1>
        <p class="text-sm text-gray-500">Prediction accuracy, pipeline progress, and learning insights.</p>
      </div>

      <PipelineStage pipeline={pipeline} />
      {/* AccuracySummary, PredictionFeed, Disagreements — added in subsequent tasks */}
    </div>
  );
}
