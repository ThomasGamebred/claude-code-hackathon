import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getReviewQueue, postReview } from "@/api/client";
import Card from "@/components/Card";
import SourceBadge from "@/components/SourceBadge";
import type { ReviewPair, ReviewSide } from "@/api/types";

function scoreBadge(score: number): string {
  if (score >= 0.85) return "bg-emerald-100 text-emerald-800 border-emerald-200";
  if (score >= 0.75) return "bg-gold-100 text-gold-800 border-gold-200";
  return "bg-rose-100 text-rose-800 border-rose-200";
}

export default function StewardshipQueue() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["review"], queryFn: getReviewQueue });
  const [expanded, setExpanded] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "merge" | "keep_separate" }) =>
      postReview(id, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["review"] });
      queryClient.invalidateQueries({ queryKey: ["customers"] });
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-swamp-900">
          Stewardship queue
        </h1>
        <p className="text-swamp-600 mt-2 max-w-2xl">
          Pairs the matcher couldn't decide alone — scores between 0.70 and 0.89.
          Your call: same person, or two people?
        </p>
      </div>

      {query.isLoading && <Card><p className="text-swamp-600">Loading review pairs...</p></Card>}
      {query.isError && (
        <Card title="Failed to load review queue">
          <p className="text-rose-600 text-sm">{(query.error as Error).message}</p>
        </Card>
      )}

      {query.data && query.data.length === 0 && (
        <Card>
          <div className="text-center py-10">
            <div className="text-4xl mb-2">{"✨"}</div>
            <p className="text-swamp-700 font-medium">Queue is empty.</p>
            <p className="text-swamp-600 text-sm mt-1">
              Every borderline pair has been triaged. Nice.
            </p>
          </div>
        </Card>
      )}

      {query.data && query.data.length > 0 && (
        <div className="space-y-3">
          {query.data.map((pair) => (
            <ReviewRow
              key={pair.id}
              pair={pair}
              expanded={expanded === pair.id}
              onToggle={() => setExpanded(expanded === pair.id ? null : pair.id)}
              onDecide={(decision) => mutation.mutate({ id: pair.id, decision })}
              pending={mutation.isPending && mutation.variables?.id === pair.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface RowProps {
  pair: ReviewPair;
  expanded: boolean;
  onToggle: () => void;
  onDecide: (decision: "merge" | "keep_separate") => void;
  pending: boolean;
}

function ReviewRow({ pair, expanded, onToggle, onDecide, pending }: RowProps) {
  return (
    <div className="rounded-2xl border border-swamp-200/70 bg-white shadow-card overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-4 p-4 text-left hover:bg-swamp-50/60 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span
            className={`inline-flex items-center justify-center rounded-lg border font-mono text-sm px-2 py-1 tabular-nums ${scoreBadge(pair.score)}`}
          >
            {pair.score.toFixed(2)}
          </span>
          <div>
            <div className="text-sm font-medium text-swamp-900">
              {pair.left.name} <span className="text-swamp-400 mx-1">↔</span> {pair.right.name}
            </div>
            <div className="text-xs text-swamp-600 mt-0.5 flex items-center gap-2">
              <SourceBadge source={pair.left.source} />
              <span>vs</span>
              <SourceBadge source={pair.right.source} />
            </div>
          </div>
        </div>
        <span className="text-xs text-swamp-500">
          {expanded ? "Collapse ▲" : "Expand ▼"}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-swamp-100 p-4 space-y-4 bg-swamp-50/30">
          <p className="text-xs text-swamp-700 italic">{pair.reason}</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <SidePanel side={pair.left} />
            <SidePanel side={pair.right} />
          </div>
          <div className="flex flex-col sm:flex-row gap-3 pt-2">
            <button
              type="button"
              disabled={pending}
              onClick={() => onDecide("merge")}
              className="flex-1 inline-flex items-center justify-center px-4 py-2.5 rounded-xl bg-swamp-900 text-gold-200 font-medium text-sm hover:bg-swamp-800 disabled:opacity-50 transition-colors"
            >
              {pending ? "Saving..." : "Merge — same person"}
            </button>
            <button
              type="button"
              disabled={pending}
              onClick={() => onDecide("keep_separate")}
              className="flex-1 inline-flex items-center justify-center px-4 py-2.5 rounded-xl border border-swamp-300 bg-white text-swamp-900 font-medium text-sm hover:bg-swamp-50 disabled:opacity-50 transition-colors"
            >
              Keep separate
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const FIELDS: Array<keyof ReviewSide> = ["name", "email", "phone", "address", "dob"];

function SidePanel({ side }: { side: ReviewSide }) {
  return (
    <div className="rounded-xl border border-swamp-200 bg-white p-3">
      <div className="flex items-center justify-between mb-2">
        <SourceBadge source={side.source} />
        <span className="font-mono text-[11px] text-swamp-500">{side.source_id}</span>
      </div>
      <dl className="space-y-1.5 text-xs">
        {FIELDS.map((f) => (
          <div key={f} className="grid grid-cols-3 gap-2">
            <dt className="text-swamp-500 uppercase tracking-wider text-[10px] col-span-1">{f}</dt>
            <dd className="text-swamp-900 col-span-2 break-all">
              {(side[f] as string | null) ?? <span className="text-swamp-400 italic">—</span>}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
