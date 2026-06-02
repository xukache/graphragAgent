import { useEffect, useRef, useState, useMemo } from 'react';
import * as d3 from 'd3';
import { ChevronRight, ChevronLeft, Share2, X } from 'lucide-react';
import { KGData, KGNode, KGEdge } from '../types';
import { tokens, kgClassColor } from '../styles/tokens';

/**
 * 从完整图谱中抽取"用到的节点"的子图：
 * focusIds 指定的节点 + 它们的一跳邻居 + 这些节点之间的所有边。
 */
function buildSubgraph(data: KGData, focusIds: string[]): KGData {
  const focus = new Set(focusIds);
  const keep = new Set(focusIds);

  for (const e of data.edges) {
    const s = typeof e.source === 'string' ? e.source : (e.source as KGNode).id;
    const t = typeof e.target === 'string' ? e.target : (e.target as KGNode).id;
    if (focus.has(s)) keep.add(t);
    if (focus.has(t)) keep.add(s);
  }

  const nodes = data.nodes.filter((n) => keep.has(n.id));
  const edges = data.edges.filter((e) => {
    const s = typeof e.source === 'string' ? e.source : (e.source as KGNode).id;
    const t = typeof e.target === 'string' ? e.target : (e.target as KGNode).id;
    return keep.has(s) && keep.has(t);
  });
  return { nodes, edges };
}

interface TooltipState {
  node: KGNode;
  x: number;
  y: number;
}

interface KGPanelProps {
  data: KGData | null;
  highlightedIds?: string[];
  focusIds?: string[];
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export function KGPanel({ data, highlightedIds = [], focusIds = [], collapsed, onToggleCollapse }: KGPanelProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const [focusMode, setFocusMode] = useState(false);
  const simulationRef = useRef<d3.Simulation<KGNode, KGEdge> | null>(null);
  const nodeSelectionRef = useRef<d3.Selection<SVGGElement, KGNode, SVGGElement, unknown> | null>(null);

  useEffect(() => {
    if (focusIds.length > 0) setFocusMode(true);
  }, [focusIds.join(',')]);  // eslint-disable-line react-hooks/exhaustive-deps

  const displayData: KGData | null = useMemo(() => {
    if (!data) return null;
    if (focusMode && focusIds.length > 0) {
      return buildSubgraph(data, focusIds);
    }
    return data;
  }, [data, focusMode, focusIds.join(',')]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!displayData || !svgRef.current || !containerRef.current || collapsed) return;

    const container = containerRef.current;
    const width = container.clientWidth || 400;
    const height = container.clientHeight || 400;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const defs = svg.append('defs');
    defs
      .append('filter')
      .attr('id', 'glow')
      .append('feGaussianBlur')
      .attr('stdDeviation', '4')
      .attr('result', 'coloredBlur');
    const feMerge = svg.select('#glow').append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    const g = svg.append('g');

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    const nodes: KGNode[] = displayData.nodes.map((n) => ({ ...n }));
    const nodeMap = new Map(nodes.map((n) => [n.id, n]));

    const edges: KGEdge[] = displayData.edges
      .map((e) => ({
        ...e,
        source: typeof e.source === 'string' ? (nodeMap.get(e.source) ?? e.source) : e.source,
        target: typeof e.target === 'string' ? (nodeMap.get(e.target) ?? e.target) : e.target,
      }))
      .filter((e) => typeof e.source === 'object' && typeof e.target === 'object');

    const degreeMap = new Map<string, number>();
    edges.forEach((e) => {
      const src = (e.source as KGNode).id;
      const tgt = (e.target as KGNode).id;
      degreeMap.set(src, (degreeMap.get(src) ?? 0) + 1);
      degreeMap.set(tgt, (degreeMap.get(tgt) ?? 0) + 1);
    });

    const simulation = d3
      .forceSimulation<KGNode>(nodes)
      .force(
        'link',
        d3
          .forceLink<KGNode, KGEdge>(edges)
          .id((d) => d.id)
          .distance(100)
          .strength(0.5)
      )
      .force('charge', d3.forceManyBody().strength(-280))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide(32));

    simulationRef.current = simulation;

    const link = g
      .append('g')
      .selectAll('line')
      .data(edges)
      .join('line')
      .attr('stroke', tokens.borderStrong)
      .attr('stroke-width', 1)
      .attr('stroke-opacity', 0.6);

    const linkLabel = g
      .append('g')
      .selectAll('text')
      .data(edges)
      .join('text')
      .text((d) => d.predicate)
      .attr('font-size', 8)
      .attr('fill', tokens.text3)
      .attr('text-anchor', 'middle')
      .style('pointer-events', 'none')
      .style('opacity', 0);

    const node = g
      .append('g')
      .selectAll<SVGGElement, KGNode>('g')
      .data(nodes)
      .join('g')
      .style('cursor', 'pointer')
      .call(
        d3
          .drag<SVGGElement, KGNode>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    node
      .append('circle')
      .attr('r', (d) => 5 + (degreeMap.get(d.id) ?? 0) * 2.5)
      .attr('fill', (d) => kgClassColor(d.entityClass))
      .attr('fill-opacity', 0.9)
      .attr('stroke', (d) => kgClassColor(d.entityClass))
      .attr('stroke-width', 1.5)
      .attr('stroke-opacity', 0.3);

    node
      .append('text')
      .text((d) => d.label)
      .attr('font-size', 10)
      .attr('fill', tokens.text)
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => (8 + (degreeMap.get(d.id) ?? 0) * 2) + 12)
      .style('pointer-events', 'none');

    node.on('click', (event, d) => {
      event.stopPropagation();
      const panelRect = container.getBoundingClientRect();
      const relX = event.clientX - panelRect.left;
      const relY = event.clientY - panelRect.top;
      setTooltip({ node: d, x: relX, y: relY });
    });

    node.on('mouseenter', function (_, d) {
      d3.select(this).select('circle').attr('filter', 'url(#glow)').attr('stroke-opacity', 0.8);
      linkLabel.style('opacity', (e) => {
        const s = e.source as KGNode;
        const t = e.target as KGNode;
        return s.id === d.id || t.id === d.id ? 1 : 0;
      });
    });

    node.on('mouseleave', function (_, d) {
      const isHighlighted = highlightedIds.includes(d.id);
      d3.select(this)
        .select('circle')
        .attr('filter', isHighlighted ? 'url(#glow)' : null)
        .attr('stroke-opacity', 0.3);
      linkLabel.style('opacity', 0);
    });

    nodeSelectionRef.current = node;
    svg.on('click', () => setTooltip(null));

    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as KGNode).x ?? 0)
        .attr('y1', (d) => (d.source as KGNode).y ?? 0)
        .attr('x2', (d) => (d.target as KGNode).x ?? 0)
        .attr('y2', (d) => (d.target as KGNode).y ?? 0);

      linkLabel
        .attr('x', (d) => (((d.source as KGNode).x ?? 0) + ((d.target as KGNode).x ?? 0)) / 2)
        .attr('y', (d) => (((d.source as KGNode).y ?? 0) + ((d.target as KGNode).y ?? 0)) / 2);

      node.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    return () => {
      simulation.stop();
      nodeSelectionRef.current = null;
    };
  }, [displayData, collapsed]);

  // 面板 resize 时让 force layout 重居中并重活跃一次，避免节点被推到画布外
  useEffect(() => {
    const container = containerRef.current;
    if (!container || collapsed) return;
    const sim = simulationRef.current;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        const h = entry.contentRect.height;
        if (sim) {
          sim.force('center', d3.forceCenter(w / 2, h / 2));
          sim.alpha(0.3).restart();
        }
      }
    });
    ro.observe(container);
    return () => ro.disconnect();
  }, [collapsed, displayData]);

  // Highlight nodes
  useEffect(() => {
    const node = nodeSelectionRef.current;
    if (!node) return;
    node.each(function (d) {
      const isHighlighted = highlightedIds.includes(d.id);
      d3.select(this)
        .select('circle')
        .attr('filter', isHighlighted ? 'url(#glow)' : null)
        .attr('stroke-width', isHighlighted ? 2.5 : 1.5)
        .attr('stroke-opacity', isHighlighted ? 0.9 : 0.3)
        .style('transition', 'all 300ms cubic-bezier(0.25, 1, 0.5, 1)');
    });
  }, [highlightedIds]);

  const entityClasses = displayData ? [...new Set(displayData.nodes.map((n) => n.entityClass))] : [];

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        background: tokens.surface,
        borderLeft: `1px solid ${tokens.border}`,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        minWidth: 0,
      }}
    >
      {/* Collapse toggle */}
      <button
        onClick={onToggleCollapse}
        style={{
          position: 'absolute',
          left: -12,
          top: '50%',
          transform: 'translateY(-50%)',
          width: 20,
          height: 44,
          background: tokens.surface2,
          border: `1px solid ${tokens.border}`,
          borderRadius: '6px 0 0 6px',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: tokens.text2,
          zIndex: 10,
          boxShadow: `0 1px 3px ${tokens.shadow}`,
        }}
      >
        {collapsed ? <ChevronLeft size={12} /> : <ChevronRight size={12} />}
      </button>

      {/* Header */}
      <div
        style={{
          padding: '10px 14px',
          borderBottom: `1px solid ${tokens.border}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Share2 size={13} color={tokens.text2} />
          <span
            style={{
              color: tokens.text2,
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
            }}
          >
            知识图谱
          </span>
          {focusMode && focusIds.length > 0 && (
            <span
              style={{
                background: tokens.primarySoft,
                color: tokens.primary,
                fontSize: 9,
                fontWeight: 600,
                padding: '1px 6px',
                borderRadius: 4,
                letterSpacing: '0.02em',
              }}
            >
              本次回答
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {data && focusIds.length > 0 && (
            <button
              onClick={() => setFocusMode((v) => !v)}
              style={{
                background: 'none',
                border: `1px solid ${tokens.border}`,
                borderRadius: 4,
                color: focusMode ? tokens.primary : tokens.text2,
                fontSize: 10,
                cursor: 'pointer',
                padding: '2px 7px',
                whiteSpace: 'nowrap',
              }}
            >
              {focusMode ? '显示全部' : '只看本次'}
            </button>
          )}
          {displayData && (
            <span style={{ color: tokens.text3, fontSize: 11, whiteSpace: 'nowrap' }}>
              {displayData.nodes.length} 节点 · {displayData.edges.length} 边
            </span>
          )}
        </div>
      </div>

      {/* Graph */}
      <div
        ref={containerRef}
        style={{
          flex: 1,
          position: 'relative',
          overflow: 'hidden',
          background: tokens.surface2,
        }}
      >
        {!data ? (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              color: tokens.text3,
              gap: 6,
              fontSize: 12,
            }}
          >
            <Share2 size={24} color={tokens.border} />
            <span>索引完成后展示图谱</span>
          </div>
        ) : (
          <svg
            ref={svgRef}
            width="100%"
            height="100%"
            style={{ display: 'block' }}
          />
        )}

        {/* Node tooltip */}
        {tooltip && (
          <div
            style={{
              position: 'absolute',
              left: Math.min(tooltip.x + 12, (containerRef.current?.clientWidth ?? 400) - 200),
              top: Math.max(tooltip.y - 10, 10),
              background: tokens.surface,
              border: `1px solid ${tokens.borderStrong}`,
              borderRadius: 8,
              padding: '10px 12px',
              fontSize: 11,
              color: tokens.text,
              maxWidth: 190,
              zIndex: 50,
              boxShadow: `0 6px 24px ${tokens.shadow}`,
            }}
          >
            <button
              onClick={() => setTooltip(null)}
              style={{
                position: 'absolute',
                right: 6,
                top: 6,
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: tokens.text3,
              }}
            >
              <X size={10} />
            </button>
            <div style={{ fontWeight: 600, marginBottom: 4, color: kgClassColor(tooltip.node.entityClass) }}>
              {tooltip.node.label}
            </div>
            <div
              style={{
                display: 'inline-block',
                background: tokens.surface2,
                padding: '1px 5px',
                borderRadius: 3,
                fontSize: 9,
                marginBottom: 6,
                color: tokens.text2,
                border: `1px solid ${tokens.border}`,
              }}
            >
              {tooltip.node.entityClass}
            </div>
            {Object.entries(tooltip.node.properties).map(([k, v]) => (
              <div key={k} style={{ display: 'flex', gap: 4, marginBottom: 2 }}>
                <span style={{ color: tokens.text3, minWidth: 40 }}>{k}</span>
                <span style={{ color: tokens.text }}>{v}</span>
              </div>
            ))}
            <div
              style={{
                marginTop: 6,
                fontSize: 9,
                color: tokens.text3,
                fontFamily: 'SF Mono, Cascadia Code, monospace',
              }}
            >
              {tooltip.node.id}
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      {entityClasses.length > 0 && (
        <div
          style={{
            padding: '8px 14px',
            borderTop: `1px solid ${tokens.border}`,
            flexShrink: 0,
            display: 'flex',
            flexWrap: 'wrap',
            gap: '4px 10px',
            background: tokens.surface,
          }}
        >
          {entityClasses.map((ec) => (
            <div key={ec} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: kgClassColor(ec),
                }}
              />
              <span style={{ color: tokens.text3, fontSize: 10 }}>{ec}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
