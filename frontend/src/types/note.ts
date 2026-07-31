export interface NoteMeta {
  path: string;
  title: string;
  tags: string[];
  created: string | null;
  updated: string | null;
}

export interface Note extends NoteMeta {
  content: string;
}

export interface GraphNode {
  path: string;
  title: string;
  exists: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
