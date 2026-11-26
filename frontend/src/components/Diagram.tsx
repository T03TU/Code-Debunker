import { memo, useEffect, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Node,
  type NodeProps,
  type Edge,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Braces, Box, Cable, CircleDot, Variable } from "lucide-react";
import { layoutDiagram } from "@/lib/elk";
import type { SourceSpan, UMLDiagram, UMLNodeData } from "@/types/api";

type FlowNode = Node<UMLNodeData & { [key: string]: unknown }, "umlNode">;
const icons = {
  callable: Braces,
  container: Box,
  dependency: Cable,
  external: CircleDot,
  variable: Variable,
};
const SymbolNode = memo(function SymbolNode({
  data,
  selected,
}: NodeProps<FlowNode>) {
  const Icon = icons[data.kind];
  const params = data.extra.params as
    Array<{ name: string; type: string | null }> | undefined;
  return (
    <div
      className={`symbol-node kind-${data.kind} ${selected ? "is-selected" : ""}`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="node-kind">
        <Icon size={13} />
        {data.kind === "external" ? "external reference" : data.kind}
      </div>
      <strong title={data.label}>{data.label}</strong>
      {params && (
        <div className="node-detail">
          ({params.map((p) => p.name).join(", ")})
          {data.extra.return_type ? `: ${data.extra.return_type}` : ""}
        </div>
      )}
      {data.span && (
        <div className="node-location">
          L{data.span.start_line}
          {data.span.end_line !== data.span.start_line
            ? `–${data.span.end_line}`
            : ""}
        </div>
      )}
      {typeof data.extra.test_status === "string" && (
        <span className={`node-badge status-${data.extra.test_status}`}>
          {data.extra.test_status}
        </span>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
});
const nodeTypes = { umlNode: SymbolNode };

interface Props {
  diagram: UMLDiagram;
  selectedId: string;
  testStatus?: { symbolId: string; status: string } | null;
  onSelect: (symbolId: string, span: SourceSpan | null) => void;
}
export default function Diagram({
  diagram,
  selectedId,
  testStatus,
  onSelect,
}: Props) {
  const [laidOut, setLaidOut] = useState<UMLDiagram | null>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const flow = useRef<ReactFlowInstance<FlowNode> | null>(null);
  useEffect(() => {
    let current = true;
    setLaidOut(null);
    layoutDiagram(diagram).then((result) => {
      if (current) setLaidOut(result);
    });
    return () => {
      current = false;
    };
  }, [diagram]);
  useEffect(() => {
    if (!canvas.current) return;
    const observer = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        void flow.current?.fitView({ padding: 0.2 });
      });
    });
    observer.observe(canvas.current);
    return () => observer.disconnect();
  }, [laidOut]);
  if (!laidOut) return <div className="empty-state">Arranging the graph…</div>;
  const nodes: FlowNode[] = laidOut.nodes.map((node) => ({
    ...node,
    selected: node.source_id === selectedId,
    data: {
      ...node.data,
      extra: {
        ...node.data.extra,
        ...(testStatus?.symbolId === node.source_id
          ? { test_status: testStatus.status }
          : {}),
      },
    },
  }));
  const edges: Edge[] = laidOut.edges.map((edge) => ({
    ...edge,
    data: { ...edge.data },
    label: edge.data.label,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: edge.data.kind === "data_flow" ? "#a78bfa" : "#657087",
    },
    style: { stroke: edge.data.kind === "data_flow" ? "#a78bfa" : "#657087" },
    labelStyle: { fill: "#c4cbd8", fontSize: 12 },
    labelBgStyle: { fill: "#141823" },
  }));
  return (
    <div ref={canvas} className="graph-canvas">
      <ReactFlow
        key={`${diagram.view}-${diagram.nodes.map((node) => node.id).join("|")}`}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        onInit={(instance) => {
          flow.current = instance;
        }}
        minZoom={0.2}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={false}
        onNodeClick={(_event, node) => {
          const original = laidOut.nodes.find((item) => item.id === node.id);
          if (original) onSelect(original.source_id, original.data.span);
        }}
        onEdgeClick={(_event, edge) => {
          const original = laidOut.edges.find((item) => item.id === edge.id);
          if (original) onSelect("", original.data.span);
        }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={22}
          size={1}
          color="#303645"
        />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
