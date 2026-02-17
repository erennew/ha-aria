import { useState, useRef, useEffect, useMemo } from 'preact/hooks';
import { computeLayout, computeTraceback } from '../lib/sankeyLayout.js';
import { ALL_NODES, LINKS, NODE_DETAIL, getNodeMetric, ACTION_CONDITIONS } from '../lib/pipelineGraph.js';

// --- Color mapping ---
const FLOW_COLORS = {
  data: 'var(--accent)',
  cache: 'var(--status-healthy)',
  feedback: 'var(--status-warning)',
};

const STATUS_COLORS = {
  healthy: 'var(--status-healthy)',
  warning: 'var(--status-warning)',
  blocked: 'var(--status-error)',
  waiting: 'var(--status-waiting)',
};

function getModuleStatus(moduleStatuses, nodeId) {
  const s = moduleStatuses?.[nodeId];
  if (s === 'running') return 'healthy';
  if (s === 'failed') return 'blocked';
  if (s === 'starting') return 'waiting';
  return 'waiting';
}

function getGroupHealth(moduleStatuses, childIds) {
  const statuses = childIds.map((id) => getModuleStatus(moduleStatuses, id));
  if (statuses.includes('blocked')) return 'blocked';
  if (statuses.includes('warning')) return 'warning';
  if (statuses.some((s) => s === 'healthy')) return 'healthy';
  return 'waiting';
}

// --- SVG Primitives ---

function SankeyNode({ node, status, metric, onClick, highlighted, dimmed }) {
  const color = STATUS_COLORS[status] || STATUS_COLORS.waiting;
  const opacity = dimmed ? 0.12 : 1;

  return (
    <g
      transform={`translate(${node.x}, ${node.y})`}
      onClick={() => onClick && onClick(node)}
      style={`cursor: ${onClick ? 'pointer' : 'default'}; opacity: ${opacity}; transition: opacity 0.3s;`}
    >
      <rect
        width={node.w}
        height={node.h}
        rx="4"
        fill="var(--bg-surface)"
        stroke={highlighted ? 'var(--accent)' : 'var(--border-primary)'}
        stroke-width={highlighted ? '2' : '1'}
      />
      {/* LED */}
      <circle cx="14" cy="14" r="4" fill={color}>
        {status === 'healthy' && (
          <animate attributeName="opacity" values="1;0.6;1" dur="3s" repeatCount="indefinite" />
        )}
      </circle>
      {/* Label */}
      <text x="26" y="18" fill="var(--text-primary)" font-size="11" font-weight="600" font-family="var(--font-mono)">
        {node.label}
      </text>
      {/* Metric */}
      <text x="14" y={node.h - 10} fill="var(--text-tertiary)" font-size="10" font-family="var(--font-mono)">
        {metric}
      </text>
    </g>
  );
}

function SankeyFlow({ link, dimmed, highlighted }) {
  const color = FLOW_COLORS[link.type] || 'var(--border-primary)';
  const opacity = dimmed ? 0.05 : (0.3 + Math.min(0.4, link.value * 0.04));
  const strokeW = highlighted ? 2 : 0;
  const dashArray = link.type === 'feedback' ? '4 3' : 'none';

  return (
    <g style="transition: opacity 0.3s;">
      <path
        d={link.path}
        fill={color}
        opacity={opacity}
        stroke={highlighted ? color : 'none'}
        stroke-width={strokeW}
        stroke-dasharray={dashArray}
      />
    </g>
  );
}

function BusBar({ busBar }) {
  return (
    <g>
      <rect
        x={busBar.x + 10}
        y={busBar.y}
        width={busBar.width - 20}
        height={busBar.height}
        rx="4"
        fill="var(--bg-terminal)"
        stroke="var(--status-healthy)"
        stroke-width="1.5"
      />
      <text
        x={busBar.x + busBar.width / 2}
        y={busBar.y + 18}
        text-anchor="middle"
        fill="var(--status-healthy)"
        font-size="10"
        font-weight="700"
        font-family="var(--font-mono)"
      >
        {'HUB CACHE \u00B7 hub.db \u00B7 15 categories'}
      </text>
    </g>
  );
}

function ActionStrip({ cacheData }) {
  const action = useMemo(() => {
    for (const cond of ACTION_CONDITIONS) {
      if (cond.test(cacheData)) {
        const text = typeof cond.text === 'function' ? cond.text(cacheData) : cond.text;
        return { text, href: cond.href };
      }
    }
    return null;
  }, [cacheData]);

  if (!action) return null;

  return (
    <div class="t-frame mt-4" data-label="next action">
      {action.href ? (
        <a href={action.href} class="text-sm font-medium" style="color: var(--accent); font-family: var(--font-mono); text-decoration: none;">
          {action.text}
        </a>
      ) : (
        <span class="text-sm" style="color: var(--text-tertiary); font-family: var(--font-mono);">
          {action.text}
        </span>
      )}
    </div>
  );
}

// --- Detail Panel (hover) ---

function DetailPanel({ nodeId, svgWidth, y }) {
  if (!nodeId || !NODE_DETAIL[nodeId]) return null;
  const d = NODE_DETAIL[nodeId];
  return (
    <g>
      <rect x="20" y={y} width={svgWidth - 40} height="56" rx="4" fill="var(--bg-surface)" stroke="var(--accent)" stroke-width="1" opacity="0.95" />
      <text x="32" y={y + 14} fill="var(--accent)" font-size="10" font-weight="700" font-family="var(--font-mono)">
        {nodeId.replace(/_/g, ' ').toUpperCase()}
      </text>
      <text x="32" y={y + 28} fill="var(--text-tertiary)" font-size="8" font-family="var(--font-mono)">
        {`\u25B6 ${d.protocol}  \u2502  reads: ${d.reads}`}
      </text>
      <text x="32" y={y + 42} fill="var(--text-tertiary)" font-size="8" font-family="var(--font-mono)">
        {`\u25BC writes: ${d.writes}`}
      </text>
    </g>
  );
}

// --- Main Component ---

export default function PipelineSankey({ moduleStatuses, cacheData }) {
  const containerRef = useRef(null);
  const [width, setWidth] = useState(860);
  const [expandedColumn, setExpandedColumn] = useState(-1);
  const [hoveredNode, setHoveredNode] = useState(null);
  const [traceTarget, setTraceTarget] = useState(null);

  // Responsive width
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width;
      if (w && w > 0) setWidth(w);
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Compute layout
  const layout = useMemo(
    () => computeLayout({ nodes: ALL_NODES, links: LINKS, width, expandedColumn }),
    [width, expandedColumn]
  );

  // Compute trace-back highlight set
  const traceSet = useMemo(
    () => (traceTarget ? computeTraceback(traceTarget, LINKS, NODE_DETAIL) : null),
    [traceTarget]
  );

  function handleNodeClick(node) {
    if (node.isGroup) {
      setExpandedColumn((prev) => (prev === node.column ? -1 : node.column));
      setTraceTarget(null);
    } else if (node.column === 4) {
      // Output node — toggle trace-back
      setTraceTarget((prev) => (prev === node.id ? null : node.id));
    }
  }

  function isNodeDimmed(node) {
    if (!traceSet) return false;
    if (node.isGroup) return !node.childIds?.some((id) => traceSet.has(id));
    return !traceSet.has(node.id);
  }

  function isLinkDimmed(link) {
    if (!traceSet) return false;
    return !traceSet.has(link.source) || !traceSet.has(link.target);
  }

  const svgHeight = layout.svgHeight + (hoveredNode ? 66 : 0);

  return (
    <section ref={containerRef} class="t-terminal-bg rounded-lg p-4 overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${svgHeight}`}
        class="w-full"
        style="min-width: 600px; max-width: 100%; transition: height 0.2s ease;"
      >
        <defs>
          <filter id="led-glow-sankey">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        {/* Flows (behind nodes) */}
        {layout.links.map((link) => (
          <SankeyFlow
            key={`${link.source}-${link.target}`}
            link={link}
            dimmed={isLinkDimmed(link)}
            highlighted={traceSet && !isLinkDimmed(link)}
          />
        ))}

        {/* Bus Bar */}
        <BusBar busBar={layout.busBar} />

        {/* Nodes */}
        {layout.nodes.map((node) => {
          const status = node.isGroup
            ? getGroupHealth(moduleStatuses, node.childIds || [])
            : (node.column === 0 ? 'healthy' : getModuleStatus(moduleStatuses, node.id));
          const metric = node.isGroup
            ? `${node.children?.length || 0} modules`
            : getNodeMetric(cacheData, node.id);

          return (
            <SankeyNode
              key={node.id}
              node={node}
              status={status}
              metric={metric}
              onClick={handleNodeClick}
              highlighted={traceSet && traceSet.has(node.id)}
              dimmed={isNodeDimmed(node)}
            />
          );
        })}

        {/* Detail panel on hover */}
        {hoveredNode && (
          <DetailPanel nodeId={hoveredNode} svgWidth={width} y={layout.svgHeight - 10} />
        )}
      </svg>

      {/* Color legend */}
      <div class="flex gap-4 mt-2 text-xs" style="color: var(--text-tertiary); font-family: var(--font-mono);">
        <span><span style="color: var(--accent);">{'\u25CF'}</span> data flow</span>
        <span><span style="color: var(--status-healthy);">{'\u25CF'}</span> cache read/write</span>
        <span><span style="color: var(--status-warning);">{'\u25CF'}</span> feedback loop</span>
        <span style="opacity: 0.6;">click column to expand · click output to trace</span>
      </div>

      {/* Action strip */}
      <ActionStrip cacheData={cacheData} />
    </section>
  );
}
