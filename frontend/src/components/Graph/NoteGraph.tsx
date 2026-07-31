import { useEffect, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { useNavigate } from "react-router-dom";
import { encodeNotePath, getGraph } from "../../api/client";
import { usePrefersDark } from "../../hooks/usePrefersDark";
import type { GraphResponse } from "../../types/note";

export function NoteGraph() {
  const [graph, setGraph] = useState<GraphResponse>({ nodes: [], edges: [] });
  const navigate = useNavigate();
  const prefersDark = usePrefersDark();

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
      backgroundColor={prefersDark ? "#17181c" : "#ffffff"}
      nodeLabel="title"
      nodeColor={(node) => (node.exists ? "#4c8bf5" : "#9aa0a6")}
      linkColor={() => (prefersDark ? "#4a4b54" : "#c7c7cf")}
      onNodeClick={(node) => {
        if (!node.exists) return;
        navigate(`/notes/${encodeNotePath(String(node.id))}`);
      }}
    />
  );
}
