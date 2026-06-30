import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listCustomers } from "@/api/client";
import Card from "@/components/Card";
import ConfidenceBar from "@/components/ConfidenceBar";

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

export default function CustomerList() {
  const [q, setQ] = useState("");
  const debouncedQ = useDebounced(q, 250);
  const navigate = useNavigate();

  const query = useQuery({
    queryKey: ["customers", debouncedQ],
    queryFn: () => listCustomers(debouncedQ, 100, 0),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-swamp-900">
          Golden records
        </h1>
        <p className="text-swamp-600 mt-2 max-w-2xl">
          One row per real human. Click any name to see which sources contributed
          and how confident we are about each field.
        </p>
      </div>

      <Card>
        <div className="relative mb-4">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name, city, region..."
            className="w-full rounded-xl border border-swamp-200 bg-swamp-50/40 px-4 py-2.5 text-sm placeholder:text-swamp-400 focus:outline-none focus:ring-2 focus:ring-swamp-400 focus:bg-white"
          />
        </div>

        {query.isLoading && <p className="text-sm text-swamp-600">Loading...</p>}
        {query.isError && (
          <p className="text-sm text-rose-600">
            {(query.error as Error).message}
          </p>
        )}

        {query.data && query.data.length === 0 && (
          <div className="text-center py-12">
            <p className="text-swamp-600">
              No customers yet. {debouncedQ ? "Try a different search." : "Run the pipeline."}
            </p>
          </div>
        )}

        {query.data && query.data.length > 0 && (
          <div className="overflow-x-auto -mx-2">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-swamp-500 border-b border-swamp-200">
                  <th className="py-2 px-2 font-medium">Name</th>
                  <th className="py-2 px-2 font-medium">City</th>
                  <th className="py-2 px-2 font-medium">Region</th>
                  <th className="py-2 px-2 font-medium">Sources</th>
                  <th className="py-2 px-2 font-medium">Confidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-swamp-100">
                {query.data.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => navigate(`/customers/${c.id}`)}
                    className="hover:bg-swamp-50/70 cursor-pointer transition-colors"
                  >
                    <td className="py-3 px-2">
                      <div className="font-medium text-swamp-900">{c.full_name}</div>
                      <div className="text-[11px] text-swamp-500 font-mono">{c.id}</div>
                    </td>
                    <td className="py-3 px-2 text-swamp-700">{c.city ?? "—"}</td>
                    <td className="py-3 px-2 text-swamp-700">{c.region ?? "—"}</td>
                    <td className="py-3 px-2">
                      <span className="inline-flex items-center justify-center min-w-[1.75rem] h-6 px-2 rounded-full bg-swamp-100 text-swamp-800 text-xs font-medium">
                        {c.n_sources}
                      </span>
                    </td>
                    <td className="py-3 px-2">
                      <ConfidenceBar value={c.record_confidence} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
