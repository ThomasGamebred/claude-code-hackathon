const PALETTE: Record<string, string> = {
  acq_northwind: "bg-sky-100 text-sky-800 border-sky-200",
  acq_rheinland: "bg-rose-100 text-rose-800 border-rose-200",
  acq_sunset: "bg-orange-100 text-orange-800 border-orange-200",
  crm: "bg-swamp-100 text-swamp-800 border-swamp-200",
  ecommerce: "bg-violet-100 text-violet-800 border-violet-200",
  loyalty: "bg-gold-100 text-gold-800 border-gold-200",
  pos: "bg-teal-100 text-teal-800 border-teal-200",
};

const FALLBACK = "bg-slate-100 text-slate-700 border-slate-200";

export default function SourceBadge({ source }: { source: string }) {
  const cls = PALETTE[source] ?? FALLBACK;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium font-mono ${cls}`}
    >
      {source}
    </span>
  );
}
