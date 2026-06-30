import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getCustomer } from "@/api/client";
import Card from "@/components/Card";
import ConfidenceBar from "@/components/ConfidenceBar";
import SourceBadge from "@/components/SourceBadge";

export default function GoldenRecord() {
  const { id = "" } = useParams();
  const query = useQuery({
    queryKey: ["customer", id],
    queryFn: () => getCustomer(id),
    enabled: !!id,
  });

  if (query.isLoading) {
    return <p className="text-swamp-600">Loading customer...</p>;
  }
  if (query.isError) {
    return (
      <Card title="Failed to load customer">
        <p className="text-rose-600 text-sm">{(query.error as Error).message}</p>
        <Link to="/customers" className="text-sm text-swamp-700 underline mt-2 inline-block">
          ← Back to customers
        </Link>
      </Card>
    );
  }
  if (!query.data) {
    return <p className="text-swamp-600">No customer found.</p>;
  }

  const c = query.data;

  return (
    <div className="space-y-6">
      <Link to="/customers" className="text-sm text-swamp-600 hover:text-swamp-900 inline-flex items-center gap-1">
        ← Back to customers
      </Link>

      <section className="rounded-2xl border border-gold-200 bg-gradient-to-br from-white via-gold-50/30 to-white shadow-card p-6">
        <div className="flex items-start justify-between gap-6 flex-wrap">
          <div>
            <div className="text-[11px] uppercase tracking-[0.2em] text-gold-700 font-semibold">
              Golden record
            </div>
            <h1 className="text-3xl font-semibold tracking-tight text-swamp-900 mt-1">
              {c.full_name}
            </h1>
            <div className="text-sm text-swamp-600 mt-1 font-mono">{c.id}</div>
            <div className="flex items-center gap-4 mt-4 text-sm">
              <Field label="City" value={c.city} />
              <Field label="Region" value={c.region} />
              <Field label="Birth year" value={c.birth_year} />
              <Field label="Sources" value={c.n_sources} />
            </div>
          </div>
          <div className="min-w-[16rem]">
            <div className="text-[11px] uppercase tracking-wider text-swamp-500 font-medium mb-1">
              Record confidence
            </div>
            <ConfidenceBar value={c.record_confidence} />
          </div>
        </div>
      </section>

      <Card
        title="Field-level provenance"
        subtitle="Each field reports the winning source and how confident the survivorship rules were."
      >
        <ul className="divide-y divide-swamp-100">
          {c.fields.map((f) => (
            <li key={f.field} className="py-3 grid grid-cols-12 gap-3 items-center">
              <div className="col-span-3 text-xs uppercase tracking-wider text-swamp-500 font-medium">
                {f.field}
              </div>
              <div className="col-span-4 text-sm text-swamp-900 font-medium break-all">
                {f.value ?? <span className="text-swamp-400 italic">null</span>}
              </div>
              <div className="col-span-2">
                <SourceBadge source={f.source} />
              </div>
              <div className="col-span-3">
                <ConfidenceBar value={f.confidence} size="sm" />
              </div>
              {f.rationale && (
                <div className="col-span-12 text-xs text-swamp-600 pl-1 border-l-2 border-swamp-200 ml-1 -mt-1">
                  {f.rationale}
                </div>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <Card
        title="Contributions"
        subtitle="The raw rows that built this golden record."
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {c.contributions.map((ctr) => (
            <div
              key={`${ctr.source}-${ctr.source_id}`}
              className="rounded-xl border border-swamp-200 bg-swamp-50/30 p-3 flex flex-col gap-2"
            >
              <div className="flex items-center justify-between">
                <SourceBadge source={ctr.source} />
                <span className="font-mono text-[11px] text-swamp-500">
                  {ctr.source_id} · row {ctr.source_row}
                </span>
              </div>
              <dl className="text-xs space-y-1">
                {Object.entries(ctr.fields).map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <dt className="text-swamp-500 uppercase tracking-wider text-[10px] min-w-[4rem]">{k}</dt>
                    <dd className="text-swamp-900 break-all">{v ?? "—"}</dd>
                  </div>
                ))}
              </dl>
              {ctr.field_quality_flags.length > 0 && (
                <div className="flex flex-wrap gap-1 pt-1 border-t border-swamp-200">
                  {ctr.field_quality_flags.map((flag) => (
                    <span
                      key={flag}
                      className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-gold-100 text-gold-800"
                    >
                      {flag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>

      <div className="flex justify-end">
        <Link
          to={`/lineage/${c.id}`}
          className="text-sm font-medium text-swamp-700 hover:text-swamp-900 inline-flex items-center gap-1"
        >
          View lineage →
        </Link>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-swamp-500">{label}</div>
      <div className="text-sm font-medium text-swamp-900">{value ?? "—"}</div>
    </div>
  );
}
