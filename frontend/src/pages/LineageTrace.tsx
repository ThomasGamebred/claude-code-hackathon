import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getLineage } from "@/api/client";
import Card from "@/components/Card";
import type { LineageGraph, LineageNode } from "@/api/types";

const KIND_STYLE: Record<LineageNode["kind"], string> = {
  master: "border-gold-300 bg-gold-50 text-gold-900",
  xref: "border-swamp-300 bg-swamp-50 text-swamp-900",
  conformed: "border-violet-300 bg-violet-50 text-violet-900",
  raw: "border-slate-300 bg-slate-50 text-slate-900",
};

const KIND_LABEL: Record<LineageNode["kind"], string> = {
  master: "MASTER",
  xref: "XREF",
  conformed: "CONFORMED",
  raw: "RAW",
};

function buildChildren(graph: LineageGraph): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const e of graph.edges) {
    const arr = map.get(e.from) ?? [];
    arr.push(e.to);
    map.set(e.from, arr);
  }
  return map;
}

export default function LineageTrace() {
  const { id = "" } = useParams();
  const [copied, setCopied] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["lineage", id],
    queryFn: () => getLineage(id),
    enabled: !!id,
  });

  function copy(nodeId: string) {
    navigator.clipboard?.writeText(nodeId).then(
      () => {
        setCopied(nodeId);
        setTimeout(() => setCopied((c) => (c === nodeId ? null : c)), 1200);
      },
      () => undefined,
    );
  }

  if (query.isLoading) return <p className="text-swamp-600">Tracing lineage...</p>;
  if (query.isError) {
    return (
      <Card title="Failed to load lineage">
        <p className="text-rose-600 text-sm">{(query.error as Error).message}</p>
      </Card>
    );
  }
  if (!query.data) return <p className="text-swamp-600">No lineage available.</p>;

  const graph = query.data;
  const children = buildChildren(graph);
  const rootId = graph.nodes.find((n) => n.kind === "master")?.id ?? graph.nodes[0]?.id;
  const nodesById = new Map(graph.nodes.map((n) => [n.id, n]));

  return (
    <div className="space-y-6">
      <Link to={`/customers/${id}`} className="text-sm text-swamp-600 hover:text-swamp-900 inline-flex items-center gap-1">
        ← Back to record
      </Link>

      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-swamp-900">
          Lineage trace
        </h1>
        <p className="text-swamp-600 mt-2 max-w-2xl">
          From the golden record back to the raw row in the source file. Every
          arrow is a transformation we can reproduce. Click any node to copy its identifier.
        </p>
      </div>

      <Card>
        {rootId && (
          <TreeNode
            id={rootId}
            nodesById={nodesById}
            children={children}
            onCopy={copy}
            copied={copied}
            depth={0}
          />
        )}
      </Card>
    </div>
  );
}

interface TreeProps {
  id: string;
  nodesById: Map<string, LineageNode>;
  children: Map<string, string[]>;
  onCopy: (id: string) => void;
  copied: string | null;
  depth: number;
}

function TreeNode({ id, nodesById, children, onCopy, copied, depth }: TreeProps) {
  const node = nodesById.get(id);
  if (!node) return null;
  const kids = children.get(id) ?? [];

  return (
    <div className={depth === 0 ? "" : "pl-6 border-l-2 border-dashed border-swamp-200 ml-3 mt-2"}>
      <button
        type="button"
        onClick={() => onCopy(node.id)}
        className={`group inline-flex flex-col items-start gap-1 rounded-xl border px-3 py-2 text-left hover:shadow-card transition-shadow ${KIND_STYLE[node.kind]}`}
        title="Click to copy identifier"
      >
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider opacity-70">
            {KIND_LABEL[node.kind]}
          </span>
          {copied === node.id && (
            <span className="text-[10px] font-medium text-emerald-700">copied</span>
          )}
        </div>
        <span className="font-mono text-xs">{node.label}</span>
        {node.meta && (
          <div className="text-[10px] opacity-70 font-mono">
            {Object.entries(node.meta).map(([k, v]) => (
              <div key={k}>
                {k}: {String(v)}
              </div>
            ))}
          </div>
        )}
      </button>

      {kids.length > 0 && (
        <div>
          {kids.map((kidId) => (
            <TreeNode
              key={kidId}
              id={kidId}
              nodesById={nodesById}
              children={children}
              onCopy={onCopy}
              copied={copied}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}
