import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Cell,
} from "recharts";
import { getQualityChecks, getSources } from "@/api/client";
import Card from "@/components/Card";
import ConfidenceBar from "@/components/ConfidenceBar";
import SourceBadge from "@/components/SourceBadge";
import type { SourceInfo } from "@/api/types";

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function barColor(value: number): string {
  if (value >= 0.85) return "#10b981";
  if (value >= 0.7) return "#e6b62c";
  return "#f43f5e";
}

export default function SwampDashboard() {
  const sources = useQuery({ queryKey: ["sources"], queryFn: getSources });
  const quality = useQuery({ queryKey: ["quality"], queryFn: getQualityChecks });

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-swamp-900">
          Welcome to the swamp.
        </h1>
        <p className="text-swamp-600 mt-2 max-w-2xl">
          Seven systems. Zero agreement. Diacritics dropped in transit, phone
          numbers stored as dates, the same customer typed five different ways.
          Below: the raw truth, before we make it shiny.
        </p>
      </div>

      {sources.isLoading && <Card><p className="text-swamp-600">Profiling sources...</p></Card>}
      {sources.isError && (
        <Card title="Failed to load sources">
          <p className="text-rose-600 text-sm">{(sources.error as Error).message}</p>
        </Card>
      )}
      {sources.data && sources.data.length === 0 && (
        <Card title="Nothing ingested yet">
          <p className="text-swamp-600 text-sm">No sources yet. Run the pipeline.</p>
        </Card>
      )}

      {sources.data && sources.data.length > 0 && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {sources.data.map((s) => (
              <SourceCard key={s.name} src={s} />
            ))}
          </div>

          <Card
            title="Quality score across sources"
            subtitle="Side-by-side completeness × freshness × anomaly penalty. Hover for the breakdown."
          >
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={sources.data.map((s) => ({
                    name: s.name.replace("acq_", ""),
                    full: s.name,
                    score: s.quality_score,
                    rows: s.row_count,
                    anomalies: s.anomaly_count,
                  }))}
                  margin={{ top: 8, right: 8, left: -16, bottom: 8 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#dee9e3" />
                  <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#406253" }} />
                  <YAxis domain={[0, 1]} tick={{ fontSize: 12, fill: "#406253" }} />
                  <Tooltip
                    cursor={{ fill: "rgba(85, 123, 105, 0.08)" }}
                    contentStyle={{
                      borderRadius: 12,
                      border: "1px solid #dee9e3",
                      fontSize: 12,
                    }}
                    formatter={(value: number | string, name: string) => {
                      if (name === "score")
                        return [Number(value).toFixed(2), "quality score"];
                      return [value, name];
                    }}
                    labelFormatter={(label, payload) =>
                      payload?.[0]?.payload?.full ?? label
                    }
                  />
                  <Bar dataKey="score" radius={[6, 6, 0, 0]}>
                    {sources.data.map((s) => (
                      <Cell key={s.name} fill={barColor(s.quality_score)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </>
      )}

      {quality.data && quality.data.length > 0 && (
        <Card title="Latest quality run" subtitle="Block-level checks gate writes into curated.">
          <ul className="divide-y divide-swamp-100">
            {quality.data.map((q) => (
              <li key={q.name} className="py-3 flex items-center justify-between gap-4">
                <div>
                  <div className="text-sm font-medium text-swamp-900 font-mono">{q.name}</div>
                  <div className="text-xs text-swamp-600 mt-0.5">{q.message}</div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${
                    q.level === "BLOCK" ? "bg-rose-100 text-rose-800" :
                    q.level === "ALERT" ? "bg-gold-100 text-gold-800" :
                    "bg-swamp-100 text-swamp-800"
                  }`}>
                    {q.level}
                  </span>
                  <span className={`text-xs font-medium ${
                    q.status === "pass" ? "text-emerald-700" : "text-rose-700"
                  }`}>
                    {q.status}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function SourceCard({ src }: { src: SourceInfo }) {
  return (
    <div className="rounded-2xl border border-swamp-200/70 bg-white shadow-card p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <SourceBadge source={src.name} />
        <span className="text-xs text-swamp-500">
          {src.anomaly_count} {src.anomaly_count === 1 ? "anomaly" : "anomalies"}
        </span>
      </div>
      <div>
        <div className="text-3xl font-semibold tabular-nums text-swamp-900">
          {src.row_count.toLocaleString()}
        </div>
        <div className="text-xs text-swamp-600 -mt-0.5">rows ingested</div>
      </div>
      <ConfidenceBar value={src.quality_score} />
      {src.notes && (
        <p className="text-xs text-swamp-700 leading-relaxed border-l-2 border-swamp-200 pl-2">
          {src.notes}
        </p>
      )}
      <div className="text-[11px] text-swamp-500 mt-auto">
        Last ingest · {formatTs(src.last_ingested_at)}
      </div>
    </div>
  );
}
