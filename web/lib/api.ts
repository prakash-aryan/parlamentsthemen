import type { Lang, Level } from "./i18n";

export interface TopicAnswer {
  score?: number;
  probability: number | null;
  threshold?: number;
  decision: "yes" | "no";
  confidence: "high" | "low";
  second_opinion_probability?: number | null;
  corrected?: boolean;
  original_decision?: "yes" | "no";
}

export type OutcomeKey = "accepted" | "rejected" | "answered" | "pending" | "withdrawn" | "closed" | "unknown";
export const OUTCOME_ORDER: OutcomeKey[] = ["accepted", "rejected", "answered", "pending", "withdrawn", "closed", "unknown"];

export interface Hit {
  openparldata_id: number;
  similarity: number;
  body_key?: string | null;
  body_name?: string | null;
  level?: string | null;
  number?: string | null;
  affair_type?: string | null;
  year?: number | null;
  lang?: string | null;
  title?: string | null;
  title_de?: string | null;
  title_fr?: string | null;
  title_it?: string | null;
  outcome?: OutcomeKey | null;
  title_only?: boolean | null;
  keyword_match?: boolean;
  score?: number;
  topic_answer?: TopicAnswer;
}

export type SearchMode = "query" | "topic" | "query_topic";

export interface SearchResponse {
  query: string | null;
  did_you_mean?: string | null;
  topic: string | null;
  mode: SearchMode;
  checked: number;
  stored?: boolean;
  level: string | null;
  body: string | null;
  year_from: number | null;
  year_to: number | null;
  results: Hit[];
}

export interface SearchParams {
  q?: string;
  topic?: string;
  body?: string;
  level?: Level;
  yearFrom?: string;
  yearTo?: string;
  limit?: number;
}

export interface TopicScope {
  level: "country" | "canton";
  body: string;
}

export type Scheme = "adhoc" | "aps" | "curia_vista" | "sg";

export interface Topic {
  id: string;
  name: string;
  names: Partial<Record<Lang, string>>;
  card_hash: string;
  calibrated: boolean;
  stored: boolean;
  scheme: Scheme;
  parent: string | null;
  scope: TopicScope | null;
}

export interface Detail {
  openparldata_id: number;
  title?: string | null;
  body_key?: string | null;
  body_name?: string | null;
  excerpt?: string;
  text_source?: string;
  url_openparldata: string;
  url_external?: string | null;
  type?: string | null;
  state?: string | null;
  begin_date?: string | null;
  number?: string | null;
  outcome?: OutcomeKey | null;
}

export interface SimilarAffair {
  openparldata_id: number;
  similarity: number;
  title?: string | null;
  title_de?: string | null;
  title_fr?: string | null;
  title_it?: string | null;
  body_key?: string | null;
  body_name?: string | null;
}

export interface LiveTopic extends TopicAnswer {
  topic: string;
  name: string;
  names: Partial<Record<Lang, string>>;
}

export interface Evidence extends TopicAnswer {
  evidence_quote?: string | null;
  evidence_source?: string | null;
  reason?: string | null;
}

export interface OverviewBody {
  body_key: string | null;
  body_name: string | null;
  level: string | null;
  total: number;
  outcomes: Record<OutcomeKey, number>;
}

export interface Overview {
  basis: "topic" | "query" | "query_topic" | "similar";
  pool: number | null;
  query: string | null;
  topic: string | null;
  total: number;
  parliaments: number;
  outcomes: Record<OutcomeKey, number>;
  by_body: OverviewBody[];
  outcome_names: Record<OutcomeKey, Record<Lang, string>>;
}

export interface Body {
  body_key: string;
  body_name: string | null;
  level: string;
  affairs: number;
}

export interface FlagResponse {
  stored: boolean;
}

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, init);
  const data: unknown = await r.json();
  if (!r.ok) {
    const detail = typeof data === "object" && data !== null && "detail" in data ? String((data as { detail: unknown }).detail) : r.statusText;
    throw new Error(detail);
  }
  return data as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function params(p: SearchParams, extra: Record<string, string> = {}) {
  const qs = new URLSearchParams(extra);
  if (p.q) qs.set("q", p.q);
  if (p.topic) qs.set("topic", p.topic);
  if (p.body) qs.set("body", p.body);
  if (p.level) qs.set("level", p.level);
  if (p.yearFrom) qs.set("year_from", p.yearFrom);
  if (p.yearTo) qs.set("year_to", p.yearTo);
  return qs;
}

export interface ReviewItem {
  openparldata_id: number;
  topic: string;
  note?: string | null;
  flagged_at: string;
  decision?: "yes" | "no" | null;
  probability?: number | null;
  stored: boolean;
  title?: string | null;
  title_de?: string | null;
  title_fr?: string | null;
  title_it?: string | null;
  body_key?: string | null;
  body_name?: string | null;
  level?: string | null;
  year?: number | null;
  lang?: string | null;
}

export interface CorrectionResponse {
  affair_id: number;
  topic: string;
  decision: "yes" | "no";
  original_decision: "yes" | "no";
  corrected: boolean;
}

const reviewHeaders = (token: string) => ({ "Content-Type": "application/json", "X-Review-Token": token });

export const api = {
  topics: () => request<Topic[]>("/topics"),
  bodies: () => request<Body[]>("/bodies"),
  search: (p: SearchParams) => request<SearchResponse>(`/search?${params(p, { limit: String(p.limit ?? 20) })}`),
  overview: (p: SearchParams) => request<Overview>(`/overview?${params(p)}`),
  detail: (id: number, lang: Lang) => request<Detail>(`/affairs/${id}/detail?lang=${lang}`),
  similar: (id: number, limit = 5) => request<SimilarAffair[]>(`/affairs/${id}/similar?limit=${limit}`),
  liveTopics: (id: number) => request<LiveTopic[]>(`/affairs/${id}/topics/live`),
  classify: (topic: string, affairId: number, lang: string) => post<Evidence>("/classify", { topic, affair_id: affairId, lang }),
  flag: (affairId: number, topic: string) => post<FlagResponse>("/flags", { affair_id: affairId, topic }),
  reviewStatus: () => request<{ available: boolean }>("/review"),
  reviewQueue: (token: string) => request<ReviewItem[]>("/review/queue?limit=50", { headers: reviewHeaders(token) }),
  correct: (token: string, body: { affair_id: number; topic: string; decision: "yes" | "no"; reason?: string; reviewer: string }) =>
    request<CorrectionResponse>("/review/corrections", { method: "POST", headers: reviewHeaders(token), body: JSON.stringify(body) }),
};
