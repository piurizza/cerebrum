import { useEffect, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { useNavigate } from "react-router-dom";
import { encodeNotePath, getGraph } from "../../api/client";
import type { GraphResponse } from "../../types/note";

export function NoteGraph() {
  const [graph, setGraph] = useState<GraphResponse>({ nodes: [], edges: [] });
  const navigate = useNavigate();

  useEffect(() => {
    getGraph().then(setGraph).catch(console.error);
  }, []);

  return (
    <ForceGraph2D
      graphData={{
        nodes: graph.nodes.map((node) => ({ id: node.path, ...node })),
        links: graph.edges.map((edge) => ({
          source: edge.source,
          target: edge.target,
        })),
      }}
      nodeLabel="title"
      nodeColor={(node) => (node.exists ? "#4c8bf5" : "#9aa0a6")}
      onNodeClick={(node) => {
        if (!node.exists) return;
        navigate(`/notes/${encodeNotePath(String(node.id))}`);
      }}
    />
  );
}
