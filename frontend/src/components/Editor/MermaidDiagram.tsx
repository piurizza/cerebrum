import { useEffect, useState } from "react";
import { errorMessage } from "../../api/client";
import { useTheme } from "../../context/ThemeContext";
import { renderMermaid } from "../../lib/mermaid";

type RenderState =
  | { status: "pending" }
  | { status: "ok"; svg: string }
  | { status: "error"; message: string };

export function MermaidDiagram({ source }: { source: string }) {
  const { theme } = useTheme();
  const [state, setState] = useState<RenderState>({ status: "pending" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "pending" });
    renderMermaid(source, theme).then(
      (svg) => {
        if (!cancelled) setState({ status: "ok", svg });
      },
      (err: unknown) => {
        if (!cancelled) setState({ status: "error", message: errorMessage(err) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [source, theme]);

  if (state.status === "error") {
    // Keep the source visible: a typo in a diagram must not hide its content.
    return (
      <div className="markdown-preview__mermaid-error">
        <p className="error-text" role="alert">
          Diagram could not be rendered: {state.message}
        </p>
        <pre>
          <code>{source}</code>
        </pre>
      </div>
    );
  }

  if (state.status === "pending") {
    return null;
  }

  return (
    <div
      className="markdown-preview__mermaid"
      role="img"
      aria-label="Diagram"
      // biome-ignore lint/security/noDangerouslySetInnerHtml: sanitized by sanitizeSvg in lib/mermaid
      dangerouslySetInnerHTML={{ __html: state.svg }}
    />
  );
}
