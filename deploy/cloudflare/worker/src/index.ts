import { Container, getContainer } from "@cloudflare/containers";
import TOPICS from "./data/topics.json";
import BODIES from "./data/bodies.json";
import MISC from "./data/misc.json";

export class Embedder extends Container {
  defaultPort = 8080;
  sleepAfter = "10m";
}

interface Env {
  EMBEDDER: DurableObjectNamespace<Embedder>;
  DB: D1Database;
  ASSETS: Fetcher;
  ZILLIZ_TOKEN: string;
  ZILLIZ_URL: string;
  DAILY_EMBEDS: string;
  RL_API: RateLimit;
  RL_EMBED: RateLimit;
  AE: AnalyticsEngineDataset;
}

type Row = Record<string, unknown>;
type Topic = (typeof TOPICS)[number];

const OPD = "https://api.openparldata.ch/v1";
const PROMPT_VERSION = "h1";
const LEVEL = /^(country|canton|city|municipality)$/;
const BODY = /^[A-Za-z0-9]{1,8}$/;
const OVERVIEW_POOL = 100;
const WEAK_MATCH = 0.645;
const LEGACY = MISC.legacy as Record<string, string>;
const OUTCOMES = MISC.outcomes as Record<string, unknown>;
const TOPIC_BY_ID = new Map<string, Topic>(TOPICS.map((t) => [t.id, t]));
const AFFAIR_COLS = "a.id, a.body_key, a.body_name, a.level, a.number, a.affair_type, a.year, a.lang, a.title, a.outcome, a.title_only, a.title_de, a.title_fr, a.title_it, a.title_en";

class HttpError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

const json = (body: unknown, status = 200, cache = 0) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...(cache ? { "cache-control": `public, max-age=${cache}` } : {}) },
  });

const canonical = (t: string | null) => (t ? LEGACY[t] ?? t : t);

function names(code: string) {
  const t = TOPIC_BY_ID.get(canonical(code)!);
  if (t?.names) return t.names;
  return { de: code, fr: code, it: code, rm: code, en: code };
}

function intParam(u: URLSearchParams, k: string, def: number | null, lo?: number, hi?: number): number | null {
  const v = u.get(k);
  if (v === null || v === "") return def;
  const n = Number(v);
  if (!Number.isInteger(n)) throw new HttpError(422, `${k} must be an integer`);
  if ((lo !== undefined && n < lo) || (hi !== undefined && n > hi)) throw new HttpError(422, `${k} out of range`);
  return n;
}

function patParam(u: URLSearchParams, k: string, re: RegExp): string | null {
  const v = u.get(k);
  if (v === null || v === "") return null;
  if (!re.test(v)) throw new HttpError(422, `invalid ${k}`);
  return v;
}

function query(u: URLSearchParams): string | null {
  const q = (u.get("q") ?? "").trim().slice(0, 500).trim();
  if (!q) return null;
  if (q.length < 2) throw new HttpError(422, "q must have at least 2 characters");
  return q;
}

interface Filters { level: string | null; body: string | null; yearFrom: number | null; yearTo: number | null }

function common(u: URLSearchParams) {
  const q = query(u);
  let topic = canonical(u.get("topic") || null);
  let level = patParam(u, "level", LEVEL);
  let body = patParam(u, "body", BODY);
  let yearFrom = intParam(u, "year_from", null);
  let yearTo = intParam(u, "year_to", null);
  if (!q && !topic) throw new HttpError(422, "give q, topic or both");
  let entry: Topic | undefined;
  if (topic) {
    entry = TOPIC_BY_ID.get(topic);
    if (!entry) throw new HttpError(404, `unknown topic '${topic}'; see /topics`);
    if (entry.scope) {
      level = entry.scope.level ?? level;
      body = entry.scope.body ?? body;
    }
  }
  if (yearFrom && yearTo && yearFrom > yearTo) [yearFrom, yearTo] = [yearTo, yearFrom];
  return { q, topic, entry, f: { level, body, yearFrom, yearTo } as Filters };
}

function sqlFilters(f: Filters, alias: string): [string, unknown[]] {
  const w: string[] = [], p: unknown[] = [];
  if (f.level) { w.push(`${alias}.level = ?`); p.push(f.level); }
  if (f.body) { w.push(`${alias}.body_key = ?`); p.push(f.body); }
  if (f.yearFrom) { w.push(`${alias}.year >= ?`); p.push(f.yearFrom); }
  if (f.yearTo) { w.push(`${alias}.year <= ?`); p.push(f.yearTo); }
  return [w.map((s) => ` AND ${s}`).join(""), p];
}

function zFilter(f: Filters, topic: string | null): string {
  const w: string[] = [];
  if (f.level) w.push(`level == "${f.level}"`);
  if (f.body) w.push(`body_key == "${f.body}"`);
  if (f.yearFrom) w.push(`year >= ${f.yearFrom}`);
  if (f.yearTo) w.push(`year <= ${f.yearTo} and year > 0`);
  if (topic) w.push(`array_contains(topics, "${topic.replace(/[^A-Za-z0-9_]/g, "")}")`);
  return w.join(" and ");
}

async function zilliz(env: Env, path: string, body: unknown): Promise<Row> {
  const r = await fetch(`${env.ZILLIZ_URL}/v2/vectordb/entities/${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.ZILLIZ_TOKEN}`, "content-type": "application/json" },
    body: JSON.stringify({ collectionName: "affairs", ...(body as object) }),
  });
  const d = (await r.json()) as Row;
  if (!r.ok || (d.code !== 0 && d.code !== undefined)) throw new HttpError(502, "vector search failed");
  return d;
}

async function vectorRank(env: Env, v: number[], limit: number, f: Filters, topic: string | null): Promise<[number, number][]> {
  const filter = zFilter(f, topic);
  const d = await zilliz(env, "search", {
    data: [v], annsField: "vector", limit, outputFields: ["id"], searchParams: { params: { level: 10 } }, ...(filter ? { filter } : {}),
  });
  return ((d.data as Row[]) ?? []).map((h) => [Number(h.id), Number(h.distance)]);
}

async function rows(env: Env, sql: string, params: unknown[]): Promise<Row[]> {
  return (await env.DB.prepare(sql).bind(...params).all()).results as Row[];
}

async function affairsById(env: Env, ids: number[]): Promise<Map<number, Row>> {
  const out = new Map<number, Row>();
  for (let i = 0; i < ids.length; i += 90) {
    const part = ids.slice(i, i + 90);
    for (const r of await rows(env, `SELECT ${AFFAIR_COLS} FROM affairs a WHERE a.id IN (${part.map(() => "?").join(",")})`, part)) out.set(Number(r.id), r);
  }
  return out;
}

async function answersById(env: Env, topic: string, ids: number[]): Promise<Map<number, Row>> {
  const out = new Map<number, Row>();
  for (let i = 0; i < ids.length; i += 90) {
    const part = ids.slice(i, i + 90);
    const rs = await rows(env, `SELECT id, probability, confidence, threshold, corrected, original_decision FROM yes WHERE topic = ? AND id IN (${part.map(() => "?").join(",")})`, [topic, ...part]);
    for (const r of rs) out.set(Number(r.id), r);
  }
  return out;
}

function answer(r: Row) {
  const out: Row = { probability: r.probability, decision: "yes", confidence: r.confidence, threshold: r.threshold, corrected: Boolean(r.corrected) };
  if (r.corrected) out.original_decision = r.original_decision;
  return out;
}

function hit(a: Row, similarity: number, ans?: Row) {
  const out: Row = {
    openparldata_id: Number(a.id), body_key: a.body_key, body_name: a.body_name, level: a.level, number: a.number, affair_type: a.affair_type,
    year: a.year, lang: a.lang, title: a.title, outcome: a.outcome, title_only: a.title_only === null ? null : Boolean(a.title_only),
  };
  for (const k of ["title_de", "title_fr", "title_it", "title_en"]) if (a[k]) out[k] = a[k];
  out.similarity = Math.round(similarity * 10000) / 10000;
  if (ans) out.topic_answer = answer(ans);
  return out;
}

async function embedUsage(env: Env): Promise<number> {
  const day = new Date().toISOString().slice(0, 10);
  const r = await env.DB.prepare("INSERT INTO usage (day, n) VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET n = n + 1 RETURNING n").bind(day).first<{ n: number }>();
  return r?.n ?? 0;
}

async function queryVector(env: Env, ctx: ExecutionContext, req: Request, q: string): Promise<number[]> {
  const key = `${PROMPT_VERSION}:${q.trim().toLowerCase().replace(/\s+/g, " ")}`;
  const hitRow = await env.DB.prepare("SELECT v FROM qcache WHERE k = ?").bind(key).first<{ v: string }>();
  if (hitRow) return JSON.parse(hitRow.v) as number[];
  const ip = req.headers.get("cf-connecting-ip") ?? "x";
  if (!(await env.RL_EMBED.limit({ key: ip })).success) throw new HttpError(429, "too many new searches, please wait a minute");
  if ((await embedUsage(env)) > Number(env.DAILY_EMBEDS)) throw new HttpError(429, "daily search limit reached, please try again tomorrow");
  const r = await getContainer(env.EMBEDDER, "main").fetch(new Request("http://c/", {
    method: "POST", body: JSON.stringify({ q: q.slice(0, 500) }), headers: { "content-type": "application/json" },
  }));
  if (!r.ok) throw new HttpError(503, "search model is starting, please retry in a few seconds");
  const v = ((await r.json()) as { vector: number[] }).vector;
  ctx.waitUntil(env.DB.prepare("INSERT OR REPLACE INTO qcache (k, v) VALUES (?, ?)").bind(key, JSON.stringify(v)).run());
  return v;
}

function keywordBoost(q: string, hits: Row[]): Row[] {
  const words = (q.toLowerCase().match(/[\p{L}\p{N}_]{3,}/gu) ?? []);
  for (const h of hits) {
    const title = String(h.title ?? "").toLowerCase();
    h.keyword_match = words.length > 0 && words.length <= 4 && words.every((w) => title.includes(w));
    h.score = (h.similarity as number) + (h.keyword_match ? 0.03 : 0);
  }
  return hits.sort((a, b) => (b.score as number) - (a.score as number));
}

const storedCount = (topic: string) => (STORED as Record<string, number>)[topic] ?? 0;
let STORED: Record<string, number> = {};

async function search(env: Env, ctx: ExecutionContext, req: Request, u: URLSearchParams) {
  const limit = intParam(u, "limit", 20, 1, 50)!;
  const onlyTopic = (u.get("only_topic") ?? "true") !== "false";
  const { q, topic, f } = common(u);
  const mode = q && topic ? "query_topic" : q ? "query" : "topic";
  const restrict = Boolean(topic) && (onlyTopic || !q);
  const stored = Boolean(topic);
  let hits: Row[];
  let checked = 0;
  let weak = false;
  if (mode === "topic") {
    const [w, p] = sqlFilters(f, "y");
    const rs = await rows(env, `SELECT ${AFFAIR_COLS}, y.probability, y.confidence, y.threshold, y.corrected, y.original_decision FROM yes y JOIN affairs a ON a.id = y.id WHERE y.topic = ?${w} ORDER BY y.year DESC, y.probability DESC LIMIT ?`, [topic, ...p, limit]);
    hits = rs.map((r) => hit(r, Number(r.probability), r));
    checked = storedCount(topic!);
  } else {
    const pool = Math.max(5 * limit, 100);
    const v = await queryVector(env, ctx, req, q!);
    const ranked = await vectorRank(env, v, pool, f, restrict ? topic : null);
    const ids = ranked.map(([id]) => id);
    const [aff, ans] = await Promise.all([affairsById(env, ids), topic ? answersById(env, topic, ids) : Promise.resolve(new Map<number, Row>())]);
    hits = ranked.filter(([id]) => aff.has(id)).map(([id, s]) => hit(aff.get(id)!, s, ans.get(id)));
    hits = keywordBoost(q!, hits);
    if (stored) checked = hits.length;
    weak = mode === "query" && ranked.length > 0 && ranked[0][1] < WEAK_MATCH;
  }
  return {
    query: q, did_you_mean: null, topic, mode, checked, stored, level: f.level, body: f.body, year_from: f.yearFrom, year_to: f.yearTo,
    weak_match: weak,
    results: hits.slice(0, limit),
  };
}

function summarise(rs: Row[]) {
  const byBody = new Map<string, Row & { outcomes: Record<string, number>; total: number }>();
  const totals: Record<string, number> = Object.fromEntries(Object.keys(OUTCOMES).map((k) => [k, 0]));
  for (const r of rs) {
    const o = (r.outcome as string) || "unknown";
    const n = Number(r.n);
    totals[o] = (totals[o] ?? 0) + n;
    const key = (r.body_key as string) || "?";
    let b = byBody.get(key);
    if (!b) {
      b = { body_key: r.body_key, body_name: r.body_name, level: r.level, total: 0, outcomes: Object.fromEntries(Object.keys(OUTCOMES).map((k) => [k, 0])) };
      byBody.set(key, b);
    }
    b.total += n;
    b.outcomes[o] = (b.outcomes[o] ?? 0) + n;
  }
  const bodies = [...byBody.values()].sort((a, b) => b.total - a.total || String(a.body_name ?? "").localeCompare(String(b.body_name ?? "")));
  return { total: Object.values(totals).reduce((a, b) => a + b, 0), parliaments: bodies.length, outcomes: totals, by_body: bodies };
}

async function overview(env: Env, ctx: ExecutionContext, req: Request, u: URLSearchParams) {
  const { q, topic, f } = common(u);
  const stored = Boolean(topic);
  let rs: Row[], basis: string, pool: number | null;
  if (stored && !q) {
    const [w, p] = sqlFilters(f, "y");
    rs = await rows(env, `SELECT a.body_key, a.body_name, a.level, a.outcome, count(*) AS n FROM yes y JOIN affairs a ON a.id = y.id WHERE y.topic = ?${w} GROUP BY 1, 2, 3, 4`, [topic, ...p]);
    basis = "topic";
    pool = null;
  } else {
    const v = await queryVector(env, ctx, req, q!);
    const ranked = await vectorRank(env, v, OVERVIEW_POOL, f, stored ? topic : null);
    const aff = await affairsById(env, ranked.map(([id]) => id));
    const agg = new Map<string, Row>();
    for (const [id] of ranked) {
      const a = aff.get(id);
      if (!a) continue;
      const o = (a.outcome as string) || "unknown";
      const k = JSON.stringify([a.body_key, a.body_name, a.level, o]);
      const e = agg.get(k) ?? { body_key: a.body_key, body_name: a.body_name, level: a.level, outcome: o, n: 0 };
      e.n = Number(e.n) + 1;
      agg.set(k, e);
    }
    rs = [...agg.values()];
    basis = stored ? "query_topic" : "query";
    pool = OVERVIEW_POOL;
  }
  return { basis, pool, query: q, topic, level: f.level, body: f.body, year_from: f.yearFrom, year_to: f.yearTo, ...summarise(rs), outcome_names: OUTCOMES };
}

const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

function unescape(s: string | null): string | null {
  return s && s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e: string) =>
    e[0] === "#" ? String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : Number(e.slice(1))) : ENTITIES[e.toLowerCase()] ?? m);
}

function first(v: unknown, order: string[]): string | null {
  if (v && typeof v === "object") {
    for (const l of order) { const x = (v as Record<string, string>)[l]; if (x) return x; }
    return null;
  }
  return typeof v === "string" ? v : null;
}

async function detail(env: Env, id: number, u: URLSearchParams) {
  const lang = u.get("lang") ?? "de";
  if (!/^(de|fr|it|rm|en)$/.test(lang)) throw new HttpError(422, "invalid lang");
  const r = await env.DB.prepare(`SELECT ${AFFAIR_COLS}, a.state, a.url_external, a.excerpt, a.text_source FROM affairs a WHERE a.id = ?`).bind(id).first<Row>();
  const out: Row = { openparldata_id: id };
  if (r) {
    for (const [k, v] of Object.entries(r)) if (v !== null && k !== "id") out[k] = k === "title_only" ? Boolean(v) : v;
  }
  out.url_openparldata = `${OPD}/affairs/${id}`;
  try {
    const res = await fetch(`${OPD}/affairs/${id}`, { cf: { cacheTtl: 3600, cacheEverything: true } });
    if (res.ok) {
      let a = (await res.json()) as Row;
      a = (a.data as Row) ?? a;
      const order = [lang, "de", "fr", "it", "rm", "en"];
      out.type = unescape(first(a.type_harmonized, order) ?? first(a.type_name, order));
      out.state = unescape(first(a.state_name, order)) ?? out.state ?? null;
      out.begin_date = String(a.begin_date ?? "").slice(0, 10) || null;
      out.number = a.number ?? out.number ?? null;
      out.url_external = first(a.url_external, order) ?? out.url_external ?? null;
      if (!out.excerpt) out.title = unescape(first(a.title, order));
    }
  } catch {
    out.live_details = false;
  }
  return out;
}

async function similar(env: Env, id: number, u: URLSearchParams) {
  const limit = intParam(u, "limit", 8, 1, 50)!;
  const d = await zilliz(env, "get", { id: [id], outputFields: ["vector"] });
  const v = ((d.data as Row[]) ?? [])[0]?.vector as number[] | undefined;
  if (!v) return [];
  const ranked = await vectorRank(env, v, limit + 1, { level: null, body: null, yearFrom: null, yearTo: null }, null);
  const aff = await affairsById(env, ranked.map(([i]) => i));
  return ranked.filter(([i]) => i !== id && aff.has(i)).slice(0, limit).map(([i, s]) => hit(aff.get(i)!, s));
}

async function liveTopics(env: Env, id: number) {
  const rs = await rows(env, "SELECT topic, probability, confidence, threshold, corrected, original_decision FROM yes WHERE id = ? ORDER BY probability DESC", [id]);
  return rs.map((r) => ({ topic: r.topic, name: names(r.topic as string).de, names: names(r.topic as string), ...answer(r) }));
}

async function api(req: Request, env: Env, ctx: ExecutionContext, path: string, u: URLSearchParams): Promise<Response> {
  const ip = req.headers.get("cf-connecting-ip") ?? "x";
  if (!(await env.RL_API.limit({ key: ip })).success) throw new HttpError(429, "too many requests, please wait a minute");
  if (path === "/warm" && req.method === "POST") {
    ctx.waitUntil(getContainer(env.EMBEDDER, "main").fetch(new Request("http://c/")).catch(() => undefined));
    return json({ ok: true });
  }
  if (req.method !== "GET") throw new HttpError(405, "method not allowed");
  if (path === "/topics") return json(TOPICS, 200, 3600);
  if (path === "/bodies") return json(BODIES, 200, 3600);
  if (path === "/speech") return json({ read_aloud: false, voice_search: false }, 200, 3600);
  if (path === "/review") return json({ available: false }, 200, 3600);
  if (path === "/health") return json({ status: "ok", live: false, database: true });
  if (path === "/search" || path === "/overview") {
    const cacheKey = new Request(`https://cache.internal/r4${path}?${[...u.entries()].sort().map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&")}`);
    const cached = await caches.default.match(cacheKey);
    if (cached) return cached;
    const body = path === "/search" ? await search(env, ctx, req, u) : await overview(env, ctx, req, u);
    const res = json(body, 200, 600);
    ctx.waitUntil(caches.default.put(cacheKey, res.clone()));
    return res;
  }
  const m = path.match(/^\/affairs\/(\d{1,9})\/(detail|similar|topics\/live)$/);
  if (m) {
    const id = Number(m[1]);
    if (m[2] === "detail") return json(await detail(env, id, u), 200, 600);
    if (m[2] === "similar") return json(await similar(env, id, u), 200, 3600);
    return json(await liveTopics(env, id), 200, 600);
  }
  throw new HttpError(404, "not found");
}

function track(env: Env, req: Request, url: URL, status: number, ms: number) {
  const path = url.pathname.slice(4);
  const kind = path === "/search" || path === "/overview" ? path.slice(1) : path.match(/^\/affairs\/\d+\/(detail|similar|topics\/live)$/)?.[1];
  if (!kind) return;
  const u = url.searchParams;
  const q = (u.get("q") ?? "").trim().toLowerCase().replace(/\s+/g, " ").slice(0, 120);
  const country = String((req as Request & { cf?: { country?: string } }).cf?.country ?? "");
  try {
    env.AE.writeDataPoint({
      indexes: [kind],
      blobs: [kind, q, u.get("topic") ?? "", u.get("level") ?? "", u.get("body") ?? "", u.get("lang") ?? "", String(status), country],
      doubles: [ms, status < 400 ? 1 : 0],
    });
  } catch {
    return;
  }
}

export default {
  async fetch(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(req.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(req);
    if (!Object.keys(STORED).length) {
      const r = await env.DB.prepare("SELECT v FROM meta WHERE k = 'stored'").first<{ v: string }>();
      STORED = r ? JSON.parse(r.v) : {};
    }
    const t0 = Date.now();
    let res: Response;
    try {
      res = await api(req, env, ctx, url.pathname.slice(4), url.searchParams);
    } catch (e) {
      if (e instanceof HttpError) res = json({ detail: e.detail }, e.status);
      else {
        console.error(e);
        res = json({ detail: "internal error" }, 500);
      }
    }
    track(env, req, url, res.status, Date.now() - t0);
    return res;
  },

  async scheduled(_c: ScheduledController, env: Env): Promise<void> {
    await zilliz(env, "query", { filter: "id > 0", limit: 1, outputFields: ["id"] });
  },
};
