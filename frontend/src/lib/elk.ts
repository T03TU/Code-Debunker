import ELK from "elkjs/lib/elk.bundled.js";
import type { UMLDiagram } from "@/types/api";

const elk = new ELK();

export async function layoutDiagram(diagram: UMLDiagram): Promise<UMLDiagram> {
  if (!diagram.nodes.length) return diagram;

  const elkGraph = {
    id: "root",
    layoutOptions: {
      ...diagram.elk_options,
      "elk.algorithm": "layered",
      "elk.direction": "DOWN",
      "elk.layered.spacing.nodeNodeBetweenLayers": "80",
      "elk.spacing.nodeNode": "40",
      "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
    },
    children: diagram.nodes.map((n) => ({
      id: n.id,
      width: 236,
      height: 145,
    })),
    edges: diagram.edges.map((e) => ({
      id: e.id,
      sources: [e.source],
      targets: [e.target],
    })),
  };

  try {
    const result = await elk.layout(elkGraph);
    const posMap = new Map(
      result.children?.map((c) => [c.id, { x: c.x ?? 0, y: c.y ?? 0 }]) ?? [],
    );

    return {
      ...diagram,
      nodes: diagram.nodes.map((n) => ({
        ...n,
        position: posMap.get(n.id) ?? { x: 0, y: 0 },
      })),
    };
  } catch {
    // Fallback: simple vertical layout
    return {
      ...diagram,
      nodes: diagram.nodes.map((n, i) => ({
        ...n,
        position: { x: (i % 4) * 200, y: Math.floor(i / 4) * 120 },
      })),
    };
  }
}
