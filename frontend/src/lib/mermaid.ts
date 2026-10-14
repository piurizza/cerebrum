import type { DOMPurify } from "dompurify";
import type { Mermaid } from "mermaid";

export type MermaidTheme = "light" | "dark";

interface Renderer {
  mermaid: Mermaid;
  purify: DOMPurify;
}

let rendererLoad: Promise<Renderer> | null = null;
let renderQueue: Promise<unknown> = Promise.resolve();
let renderCount = 0;

// Lazy: mermaid, its diagram chunks and the sanitizer are far larger than
// the rest of the app, and most notes never contain a diagram. A failed
// load (offline, a chunk missing after a deploy) is not cached, so the
// next render retries.
function loadRenderer(): Promise<Renderer> {
  rendererLoad ??= Promise.all([import("mermaid"), import("dompurify")]).then(
    ([mermaid, purify]) => ({ mermaid: mermaid.default, purify: purify.default }),
    (err: unknown) => {
      rendererLoad = null;
      throw err;
    },
  );
  return rendererLoad;
}

/** Strips anything executable from mermaid's output before it reaches the
 * DOM. Mermaid's own `securityLevel: "strict"` already sanitizes labels;
 * this is a second, independent barrier because note content is not
 * trusted: MCP clients and every account on the server can write notes. */
export function sanitizeSvg(purify: DOMPurify, svg: string): string {
  return purify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
}

/** Renders mermaid source to a sanitized SVG string. Rejects with mermaid's
 * parse error for invalid source. Renders run one at a time: `initialize()`
 * sets global config (the theme), so two concurrent renders with different
 * themes would race. */
export function renderMermaid(source: string, theme: MermaidTheme): Promise<string> {
  const run = async (): Promise<string> => {
    const { mermaid, purify } = await loadRenderer();
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: theme === "dark" ? "dark" : "default",
      // SVG <text> labels instead of HTML inside <foreignObject>, which
      // the SVG sanitizer profile above would strip.
      htmlLabels: false,
    });
    // parse() first: it throws on invalid source without touching the DOM,
    // whereas a failing render() can leave its scratch element behind.
    await mermaid.parse(source);
    renderCount += 1;
    const { svg } = await mermaid.render(`mermaid-diagram-${renderCount}`, source);
    return sanitizeSvg(purify, svg);
  };
  const result = renderQueue.then(run, run);
  renderQueue = result.catch(() => undefined);
  return result;
}
