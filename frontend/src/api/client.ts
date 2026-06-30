import type {
  CustomerDetail,
  CustomerSummary,
  LineageGraph,
  QualityCheck,
  ReviewPair,
  SourceInfo,
} from "./types";
import {
  MOCK_CUSTOMERS,
  MOCK_QUALITY,
  MOCK_REVIEW,
  MOCK_SOURCES,
  MOCK_SUMMARIES,
  mockLineage,
} from "./mock";

export const IS_MOCK = import.meta.env.VITE_MOCK === "1";

const reviewState: ReviewPair[] = [...MOCK_REVIEW];

async function http<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetch(input, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${body || input}`);
  }
  return (await res.json()) as T;
}

function delay<T>(value: T, ms = 120): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

export async function getSources(): Promise<SourceInfo[]> {
  if (IS_MOCK) return delay(MOCK_SOURCES);
  return http<SourceInfo[]>("/api/sources");
}

export async function listCustomers(
  q = "",
  limit = 50,
  offset = 0,
): Promise<CustomerSummary[]> {
  if (IS_MOCK) {
    const needle = q.trim().toLowerCase();
    const filtered = needle
      ? MOCK_SUMMARIES.filter(
          (c) =>
            c.full_name.toLowerCase().includes(needle) ||
            (c.city ?? "").toLowerCase().includes(needle) ||
            (c.region ?? "").toLowerCase().includes(needle),
        )
      : MOCK_SUMMARIES;
    return delay(filtered.slice(offset, offset + limit));
  }
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return http<CustomerSummary[]>(`/api/customers?${params.toString()}`);
}

export async function getCustomer(id: string): Promise<CustomerDetail> {
  if (IS_MOCK) {
    const found = MOCK_CUSTOMERS.find((c) => c.id === id);
    if (!found) throw new Error(`Customer ${id} not found`);
    return delay(found);
  }
  return http<CustomerDetail>(`/api/customers/${encodeURIComponent(id)}`);
}

export async function getLineage(id: string): Promise<LineageGraph> {
  if (IS_MOCK) return delay(mockLineage(id));
  return http<LineageGraph>(`/api/customers/${encodeURIComponent(id)}/lineage`);
}

export async function getReviewQueue(): Promise<ReviewPair[]> {
  if (IS_MOCK) return delay([...reviewState]);
  return http<ReviewPair[]>("/api/review-queue");
}

export async function postReview(
  id: string,
  decision: "merge" | "keep_separate",
  note?: string,
): Promise<{ ok: true; id: string; decision: string }> {
  if (IS_MOCK) {
    const idx = reviewState.findIndex((r) => r.id === id);
    if (idx >= 0) reviewState.splice(idx, 1);
    return delay({ ok: true as const, id, decision });
  }
  return http(`/api/review/${encodeURIComponent(id)}`, {
    method: "POST",
    body: JSON.stringify({ decision, note }),
  });
}

export async function getQualityChecks(): Promise<QualityCheck[]> {
  if (IS_MOCK) return delay(MOCK_QUALITY);
  return http<QualityCheck[]>("/api/quality/checks");
}
