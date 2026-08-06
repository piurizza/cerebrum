import { useEffect, useMemo, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { useNavigate } from "react-router-dom";
import { encodeNotePath, getGraph } from "../../api/client";
import { useTheme } from "../../context/ThemeContext";
import type { GraphResponse } from "../../types/note";

/** Resolves a CSS custom property (e.g. one of `index.css`'s `light-dark()`
 * tokens) to its actual rendered color. `getComputedStyle` on the custom
 * property itself would return the literal `light-dark(...)` text, not
 * the resolved value -- `light-dark()` only resolves when applied to a
 * real CSS property, so this applies it to a detached element's `color`
 * and reads that back instead. Needed because `react-force-graph-2d`
 * paints on a `<canvas>`, which can't read CSS variables directly. */
function resolveColorToken(varName: string): string {
  const probe = document.createElement("span");
  probe.style.color = `var(${varName})`;
  document.body.appendChild(probe);
  const resolved = getComputedStyle(probe).color;
  document.body.removeChild(probe);
  return resolved;
}

export function NoteGraph() {
  const [graph, setGraph] = useState<GraphResponse>({ nodes: [], edges: [] });
  const navigate = useNavigate();
  // Re-derives the graph's canvas colors from the app's actual CSS custom
  // properties (U5's redesigned palette) instead of a second, independent
  // set of hardcoded hex values -- otherwise this view would keep
  // rendering the pre-redesign palette after every other surface moved
  // on. `theme` (the active light/dark state -- manual override or OS
  // preference, see ThemeContext) is the signal to recompute:
  // `light-dark()` resolves differently once it changes.
  const { theme } = useTheme();
  // biome-ignore lint/correctness/useExhaustiveDependencies: theme drives re-resolution, not read inside the callback.
  const colors = useMemo(
    () => ({
      background: resolveColorToken("--bg"),
      link: resolveColorToken("--border"),
      node: resolveColorToken("--accent"),
      ghostNode: resolveColorToken("--text-faint"),
    }),
    [theme],
  );

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
      backgroundColor={colors.background}
      nodeLabel="title"
      nodeColor={(node) => (node.exists ? colors.node : colors.ghostNode)}
      linkColor={() => colors.link}
      onNodeClick={(node) => {
        if (!node.exists) return;
        navigate(`/notes/${encodeNotePath(String(node.id))}`);
      }}
    />
  );
}
