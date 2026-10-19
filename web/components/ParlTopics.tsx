"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Hero from "./Hero";
import {
  api, OUTCOME_ORDER, type Body, type Detail, type Evidence, type Hit, type LiveTopic, type Overview, type SearchResponse,
  type ReviewItem, type SimilarAffair, type Topic, type TopicAnswer,
} from "@/lib/api";
import { I18N, LANGS, LEVELS, type Dict, type Lang, type Level, type NoteKey, type Verdict } from "@/lib/i18n";
import { excerpt, merge, sentence, speechSupport, useDictation, useSpeaker, type Segment, type SpeakPhase, type SpeechSupport } from "@/lib/speech";

interface Filters {
  q: string;
  topic: string;
  level: Level;
  yfrom: string;
  yto: string;
  body: string;
}

interface Notes {
  scope: NoteKey | null;
  years: boolean;
  reset: string | null;
}

type Load<T> = { status: "loading" } | { status: "failed" } | { status: "done"; data: T };
type FlagState = "sending" | "done" | "failed";
type Reviewer = { name: string; token: string };
const REVIEWER_KEY = "parltopics.reviewer";

type Result =
  | { status: "idle" | "empty" | "error"; prev?: SearchResponse }
  | { status: "loading"; topic: boolean; prev?: SearchResponse }
  | { status: "done"; data: SearchResponse };

const EMPTY: Filters = { q: "", topic: "", level: "", yfrom: "", yto: "", body: "" };
const LEVEL_ORDER = ["country", "canton", "city", "municipality"];

const verdictOf = (a?: TopicAnswer | null): Verdict | null =>
  !a ? null : a.decision === "yes" ? (a.confidence === "low" ? "likely" : "yes") : (a.confidence === "low" ? "unsure" : "no");

const STOP = new Set([
  "der", "die", "das", "den", "dem", "des", "und", "oder", "auf", "aus", "bei", "mit", "von", "vom", "zur", "zum", "fur", "uber", "unter",
  "nach", "vor", "ein", "eine", "einer", "eines", "einem", "einen", "nicht", "sich", "ist", "sind", "wie", "was", "wer", "les", "pour",
  "par", "sur", "dans", "avec", "sans", "est", "qui", "que", "une", "aux", "del", "della", "dei", "delle", "nel", "nella", "per", "con",
  "che", "una", "gli", "the", "and", "for", "with", "from", "ils", "las", "dal", "cun",
]);

const fold = (s: string) => {
  let out = "";
  for (let i = 0; i < s.length; i++) {
    const n = s[i].normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
    out += n.length ? n[0] : s[i];
  }
  return out;
};

function stemsOf(terms: (string | null | undefined)[]): string[] {
  const out = new Set<string>();
  for (const term of terms) {
    for (const t of fold(term ?? "").match(/[\p{L}\p{N}]+/gu) ?? []) {
      if (t.length < 3 || STOP.has(t)) continue;
      out.add(t.length < 4 ? t : t.slice(0, Math.max(4, Math.min(t.length - 2, 7))));
    }
  }
  return [...out].sort((a, b) => b.length - a.length);
}

function wordRanges(text: string, stems: string[]): [number, number][] {
  if (!stems.length || !text) return [];
  const alts = stems.map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  const re = new RegExp(`(?<![\\p{L}\\p{N}])(?:${alts})[\\p{L}\\p{N}]*`, "gu");
  return [...fold(text).matchAll(re)].map((m) => [m.index ?? 0, (m.index ?? 0) + m[0].length]);
}

function Marked({ text, from = 0, to = text.length, stems, quote }: { text: string; from?: number; to?: number; stems: string[]; quote?: [number, number] | null }) {
  const spans: [number, number, string][] = [];
  if (quote) spans.push([quote[0], quote[1], ""]);
  for (const [a, b] of wordRanges(text, stems)) {
    if (b <= from || a >= to || (quote && a < quote[1] && b > quote[0])) continue;
    spans.push([a, b, "kw"]);
  }
  spans.sort((x, y) => x[0] - y[0]);
  const out: ReactNode[] = [];
  let pos = from;
  for (const [a, b, cls] of spans) {
    const s = Math.max(a, pos), e = Math.min(b, to);
    if (e <= s) continue;
    if (s > pos) out.push(<Fragment key={`t${pos}`}>{text.slice(pos, s)}</Fragment>);
    out.push(<mark key={`m${s}`} className={cls || undefined}>{text.slice(s, e)}</mark>);
    pos = e;
  }
  if (pos < to) out.push(<Fragment key={`t${pos}`}>{text.slice(pos, to)}</Fragment>);
  return <>{out}</>;
}

function Highlight({ text, quote, stems }: { text: string; quote?: string | null; stems: string[] }) {
  const i = quote ? text.toLowerCase().indexOf(quote.toLowerCase()) : -1;
  if (!quote || i < 0) {
    const end = Math.min(text.length, 900);
    return <><Marked text={text} from={0} to={end} stems={stems} />{text.length > 900 ? " …" : ""}</>;
  }
  const from = Math.max(0, i - 220), to = Math.min(text.length, i + quote.length + 420);
  return <>{from > 0 ? "… " : ""}<Marked text={text} from={from} to={to} stems={stems} quote={[i, i + quote.length]} /> …</>;
}

type Titled = { title?: string | null; title_de?: string | null; title_fr?: string | null; title_it?: string | null };

function readUrl(): { f: Filters; lang: Lang | null } {
  if (typeof window === "undefined") return { f: EMPTY, lang: null };
  const u = new URLSearchParams(window.location.search);
  const level = (LEVELS as string[]).includes(u.get("level") ?? "") ? (u.get("level") as Level) : "";
  const lang = (LANGS as string[]).includes(u.get("lang") ?? "") ? (u.get("lang") as Lang) : null;
  return { f: { q: u.get("q") ?? "", topic: u.get("topic") ?? "", level, yfrom: u.get("from") ?? "", yto: u.get("to") ?? "", body: u.get("body") ?? "" }, lang };
}

function writeUrl(f: Filters, lang: Lang) {
  const u = new URLSearchParams();
  if (f.q) u.set("q", f.q);
  if (f.topic) u.set("topic", f.topic);
  if (f.level) u.set("level", f.level);
  if (f.body) u.set("body", f.body);
  if (f.yfrom) u.set("from", f.yfrom);
  if (f.yto) u.set("to", f.yto);
  if (lang !== "de") u.set("lang", lang);
  const qs = u.toString();
  window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
}

export default function ParlTopics() {
  const [lang, setLang] = useState<Lang>("de");
  const [exIdx, setExIdx] = useState(0);
  const L: Dict = I18N[lang];
  const [topics, setTopics] = useState<Topic[]>([]);
  const [bodies, setBodies] = useState<Body[]>([]);
  const [f, setF] = useState<Filters>(EMPTY);
  const [ov, setOv] = useState<Overview | null>(null);
  const [notes, setNotes] = useState<Notes>({ scope: null, years: false, reset: null });
  const [result, setResult] = useState<Result>({ status: "idle" });
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [details, setDetails] = useState<Record<string, Load<Detail>>>({});
  const [live, setLive] = useState<Record<number, Load<LiveTopic[]>>>({});
  const [evidence, setEvidence] = useState<Record<string, Load<Evidence>>>({});
  const [similarRows, setSimilarRows] = useState<Record<number, SimilarAffair[]>>({});
  const [flags, setFlags] = useState<Record<string, FlagState>>({});
  const [context, setContext] = useState<Set<number>>(new Set());
  const [moreFilters, setMoreFilters] = useState(false);
  const [seen, setSeen] = useState<Set<number>>(new Set());
  const [topicsReady, setTopicsReady] = useState(false);
  const [ovLoading, setOvLoading] = useState(false);
  const [allExamples, setAllExamples] = useState(false);
  const [support, setSupport] = useState<SpeechSupport | null>(null);
  const { state: speech, speak, stop: stopSpeech } = useSpeaker(support);
  const readNext = useRef(false);
  const [reviewer, setReviewer] = useState<Reviewer | null>(null);
  const [reviewAvail, setReviewAvail] = useState(false);
  const [reviewLogin, setReviewLogin] = useState(false);
  const [reviewBad, setReviewBad] = useState(false);
  const [queue, setQueue] = useState<ReviewItem[] | null>(null);
  const [corr, setCorr] = useState<Record<string, FlagState>>({});
  const seq = useRef(0);
  const requested = useRef<Set<string>>(new Set());
  const finderRef = useRef<HTMLElement>(null);
  const started = useRef(false);
  const yfromRef = useRef<HTMLInputElement>(null);
  const ytoRef = useRef<HTMLInputElement>(null);
  const onYearRef = useRef<(key: "yfrom" | "yto", value: string) => void>(() => {});

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = I18N[lang].title;
  }, [lang]);

  const topicName = useCallback((id: string, names?: Partial<Record<Lang, string>>) => {
    const m = names ? { names, name: id } : topics.find((t) => t.id === id);
    return m ? (m.names?.[lang] || m.name || id) : (I18N[lang].adhoc[id] ?? id);
  }, [lang, topics]);

  const bodyName = useCallback((key?: string | null, name?: string | null, level?: string | null) => {
    const base = (key && L.bodies[key]) || name || (key === "CHE" ? L.federal : key || "");
    const local = level === "city" || level === "municipality";
    return local && Object.values(L.bodies).includes(base) ? `${base} (${L.levels[level as keyof Dict["levels"]]})` : base;
  }, [L]);

  const asLang = useCallback((l?: string | null): Lang => (l && (LANGS as string[]).includes(l) ? l as Lang : lang), [lang]);
  const titleLang = useCallback((x: Titled & { lang?: string | null }): Lang =>
    ((lang === "de" && x.title_de) || (lang === "fr" && x.title_fr) || (lang === "it" && x.title_it)) ? lang : asLang(x.lang), [lang, asLang]);

  const titleFor = useCallback((x: Titled) =>
    (lang === "de" ? x.title_de : lang === "fr" ? x.title_fr : lang === "it" ? x.title_it : null) || x.title || "", [lang]);

  const scopeOf = useCallback((id: string) => topics.find((t) => t.id === id)?.scope ?? null, [topics]);
  const cardHash = useCallback((id: string) => topics.find((t) => t.id === id)?.card_hash ?? "", [topics]);

  const runSearch = useCallback(async (next: Filters) => {
    const q = next.q.trim().length >= 2 ? next.q.trim() : "";
    const clean = { ...next, q };
    setF(clean);
    setOpen(new Set());
    setSeen(new Set());
    setContext(new Set());
    stopSpeech();
    writeUrl(clean, document.documentElement.lang as Lang);
    if (!q && !next.topic) { setResult((r) => ({ status: "empty", prev: r.status === "done" ? r.data : undefined })); setOv(null); setOvLoading(false); return; }
    const id = ++seq.current;
    setResult((r) => ({ status: "loading", topic: Boolean(next.topic), prev: r.status === "done" ? r.data : r.status === "loading" ? r.prev : undefined }));
    const scopeBody = topics.find((t) => t.id === next.topic)?.scope?.body;
    const base = { q, topic: next.topic, level: next.level, yearFrom: next.yfrom, yearTo: next.yto };
    setOvLoading(true);
    api.overview({ ...base, body: scopeBody || next.body || undefined })
      .then((o) => { if (id === seq.current) { setOv(o); setOvLoading(false); } })
      .catch(() => { if (id === seq.current) { setOv(null); setOvLoading(false); } });
    try {
      const data = await api.search({ ...base, body: scopeBody || next.body || undefined });
      if (id === seq.current) setResult({ status: "done", data });
    } catch {
      if (id === seq.current) setResult({ status: "error" });
    }
  }, [topics, stopSpeech]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const fromUrl = readUrl();
    api.bodies().then(setBodies).catch(() => setBodies([]));
    speechSupport().then(setSupport);
    api.reviewStatus().then((r) => setReviewAvail(r.available)).catch(() => setReviewAvail(false));
    try {
      const saved = sessionStorage.getItem(REVIEWER_KEY);
      if (saved) setReviewer(JSON.parse(saved));
    } catch { /* storage unavailable */ }
    api.topics().then((ts) => setTopics(ts.filter((t) => (t.calibrated || t.stored) && !t.parent))).catch(() => setTopics([]))
      .finally(() => {
        setTopicsReady(true);
        if (fromUrl.lang) setLang(fromUrl.lang);
        const fromLink = Boolean(fromUrl.f.q || fromUrl.f.topic);
        const start = fromLink ? fromUrl.f : { ...EMPTY, q: I18N[fromUrl.lang ?? "de"].examples[0] };
        runSearch(start);
        if (!fromLink) { setExIdx(0); setF({ ...start, q: "" }); }
      });
  }, [runSearch]);

  useEffect(() => {
    if (started.current && (f.q || f.topic)) writeUrl(f, lang);
  }, [lang, f]);

  const searched = result.status === "done" || result.status === "loading";
  const rerun = (next: Filters) => { if (searched || next.q.trim() || next.topic) runSearch(next); else setF(next); };

  const onTopic = (topic: string) => {
    const sc = scopeOf(topic);
    const level = sc ? sc.level : f.level;
    setNotes((n) => ({ ...n, reset: null, scope: sc ? (sc.body === "SG" ? "n_sg" : "n_curia") : null }));
    rerun({ ...f, topic, level, body: sc ? "" : f.body });
  };

  const onLevel = (level: Level) => {
    if (scopeOf(f.topic)) return;
    const t = topics.find((x) => x.id === f.topic);
    const keep = !t || !t.scope || !level || t.scope.level === level;
    const b = bodies.find((x) => x.body_key === f.body);
    setNotes((n) => ({ ...n, reset: keep ? null : f.topic }));
    rerun({ ...f, level, topic: keep ? f.topic : "", body: b && level && b.level !== level ? "" : f.body });
  };

  const onBody = (body: string) => rerun({ ...f, body });

  const onYear = (key: "yfrom" | "yto", value: string) => {
    let next = { ...f, [key]: value };
    let swapped = false;
    if (next.yfrom && next.yto && Number(next.yfrom) > Number(next.yto)) { next = { ...next, yfrom: next.yto, yto: next.yfrom }; swapped = true; }
    setNotes((n) => ({ ...n, years: swapped }));
    rerun(next);
  };

  useEffect(() => {
    onYearRef.current = onYear;
  });

  useEffect(() => {
    const pairs: ["yfrom" | "yto", HTMLInputElement | null][] = [["yfrom", yfromRef.current], ["yto", ytoRef.current]];
    const handlers = pairs.map(([key, el]) => {
      const fn = (e: Event) => onYearRef.current(key, (e.target as HTMLInputElement).value);
      el?.addEventListener("change", fn);
      return () => el?.removeEventListener("change", fn);
    });
    return () => handlers.forEach((off) => off());
  }, []);

  const loadDetail = useCallback((id: number, l: Lang) => {
    const key = `d:${id}:${l}`;
    if (requested.current.has(key)) return;
    requested.current.add(key);
    setDetails((d) => ({ ...d, [`${id}:${l}`]: { status: "loading" } }));
    api.detail(id, l)
      .then((data) => setDetails((d) => ({ ...d, [`${id}:${l}`]: { status: "done", data } })))
      .catch(() => {
        requested.current.delete(key);
        setDetails((d) => ({ ...d, [`${id}:${l}`]: { status: "done", data: { openparldata_id: id, url_openparldata: `https://api.openparldata.ch/v1/affairs/${id}` } } }));
      });
  }, []);

  const loadLive = useCallback((id: number) => {
    const key = `t:${id}`;
    if (requested.current.has(key)) return;
    requested.current.add(key);
    setLive((s) => ({ ...s, [id]: { status: "loading" } }));
    api.liveTopics(id)
      .then((data) => setLive((s) => ({ ...s, [id]: { status: "done", data } })))
      .catch(() => { requested.current.delete(key); setLive((s) => ({ ...s, [id]: { status: "failed" } })); });
  }, []);

  const loadEvidence = useCallback((id: number, topic: string, force = false) => {
    const k = `${id}:${topic}:${cardHash(topic)}:${lang}`;
    if (!force && requested.current.has(`e:${k}`)) return;
    requested.current.add(`e:${k}`);
    setEvidence((s) => ({ ...s, [k]: { status: "loading" } }));
    api.classify(topic, id, lang)
      .then((data) => setEvidence((s) => ({ ...s, [k]: { status: "done", data } })))
      .catch(() => { requested.current.delete(`e:${k}`); setEvidence((s) => ({ ...s, [k]: { status: "failed" } })); });
  }, [cardHash, lang]);

  const toggle = (h: Hit, topic: string | null) => {
    const id = h.openparldata_id;
    const isOpen = open.has(id);
    if (isOpen && speech.key === `a:${id}`) stopSpeech();
    setOpen((o) => { const n = new Set(o); if (isOpen) n.delete(id); else n.add(id); return n; });
    if (isOpen) return;
    setSeen((s) => (s.has(id) ? s : new Set(s).add(id)));
    loadDetail(id, lang);
    loadLive(id);
    const v = verdictOf(h.topic_answer);
    if (topic && v && v !== "no") loadEvidence(id, topic);
  };

  useEffect(() => {
    open.forEach((id) => loadDetail(id, lang));
  }, [lang, open, loadDetail]);

  const similar = async (id: number) => {
    let rows: SimilarAffair[] = [];
    try { rows = await api.similar(id, 5); } catch { rows = []; }
    setSimilarRows((s) => ({ ...s, [id]: rows }));
  };

  const flag = async (id: number, topic: string) => {
    const key = `${id}:${topic}`;
    setFlags((s) => ({ ...s, [key]: "sending" }));
    try {
      const r = await api.flag(id, topic);
      setFlags((s) => ({ ...s, [key]: r.stored ? "done" : "failed" }));
    } catch {
      setFlags((s) => ({ ...s, [key]: "failed" }));
    }
  };

  useEffect(() => {
    if (!reviewer) { setQueue(null); return; }
    api.reviewQueue(reviewer.token).then(setQueue).catch(() => {
      setReviewer(null);
      try { sessionStorage.removeItem(REVIEWER_KEY); } catch { /* storage unavailable */ }
    });
  }, [reviewer]);

  const signIn = async (name: string, token: string) => {
    try {
      const q = await api.reviewQueue(token);
      const r = { name: name.trim(), token };
      try { sessionStorage.setItem(REVIEWER_KEY, JSON.stringify(r)); } catch { /* storage unavailable */ }
      setQueue(q);
      setReviewer(r);
      setReviewBad(false);
      setReviewLogin(false);
      scrollToFinder();
    } catch {
      setReviewBad(true);
    }
  };

  const signOut = () => {
    setReviewer(null);
    try { sessionStorage.removeItem(REVIEWER_KEY); } catch { /* storage unavailable */ }
  };

  const correct = async (id: number, topic: string, decision: "yes" | "no") => {
    if (!reviewer) return;
    const key = `${id}:${topic}`;
    setCorr((s) => ({ ...s, [key]: "sending" }));
    try {
      const r = await api.correct(reviewer.token, { affair_id: id, topic, decision, reviewer: reviewer.name });
      setCorr((s) => ({ ...s, [key]: "done" }));
      setLive((s) => {
        const cur = s[id];
        if (!cur || cur.status !== "done") return s;
        return { ...s, [id]: { status: "done", data: cur.data.map((t) => (t.topic === topic ? { ...t, decision, corrected: true, original_decision: r.original_decision } : t)) } };
      });
      setQueue((q) => (q ? q.filter((x) => !(x.openparldata_id === id && x.topic === topic)) : q));
    } catch {
      setCorr((s) => ({ ...s, [key]: "failed" }));
    }
  };

  const scrollToFinder = () => window.scrollTo({ top: (finderRef.current?.offsetTop ?? 0) - 16, behavior: "smooth" });

  const shownTopics = useMemo(() => {
    const applies = (t: Topic) => !t.scope || !f.level || t.scope.level === f.level;
    const byName = (a: Topic, b: Topic) => topicName(a.id).localeCompare(topicName(b.id));
    const aps = (a: Topic, b: Topic) => a.id.localeCompare(b.id, undefined, { numeric: true });
    const list = topics.filter(applies);
    return [
      { label: L.g_adhoc, items: list.filter((t) => t.scheme === "adhoc").sort(byName) },
      { label: L.g_aps, items: list.filter((t) => t.scheme === "aps").sort(aps) },
      { label: L.g_curia, items: list.filter((t) => t.scheme === "curia_vista").sort(byName) },
      { label: L.g_sg, items: list.filter((t) => t.scheme === "sg").sort(byName) },
    ].filter((g) => g.items.length);
  }, [topics, f.level, topicName, L]);

  const scope = scopeOf(f.topic);
  const shownBodies = useMemo(() => {
    const list = bodies.filter((b) => (!f.level || b.level === f.level) && (!scope || b.body_key === scope.body));
    return LEVEL_ORDER.map((lv) => ({
      level: lv, items: list.filter((b) => b.level === lv).sort((a, b) => bodyName(a.body_key, a.body_name, a.level).localeCompare(bodyName(b.body_key, b.body_name, b.level))),
    })).filter((g) => g.items.length);
  }, [bodies, f.level, scope, bodyName]);

  const noteText = [
    notes.reset ? L.n_reset.replace("{t}", topicName(notes.reset)) : "",
    scope ? L[scope.body === "SG" ? "n_sg" : "n_curia"] : "",
    notes.years ? L.n_years : "",
  ].filter(Boolean).join(" ");

  let count = "", note = "";
  let hits: Hit[] = [];
  let shown: SearchResponse | undefined;
  let updating = false;
  if (result.status === "done") shown = result.data;
  else if (result.status === "loading" && result.prev) { shown = result.prev; updating = true; }
  if (result.status === "empty") count = L.r_empty;
  else if (result.status === "error") count = L.failed;
  else if (result.status === "loading" && !result.prev) count = result.topic ? L.r_loading_topic : L.r_loading;
  else if (shown) {
    const d = shown;
    hits = d.results;
    const n = hits.length, t = d.topic ? topicName(d.topic) : "", q = d.query ?? "";
    if (!n) count = d.mode === "query" ? L.r_none : d.mode === "query_topic" ? L.r_none_qt.replace("{c}", String(d.checked)).replace("{q}", q).replace("{t}", t) : L.r_none_topic.replace("{t}", t);
    else if (d.mode === "topic") {
      const total = d.stored && ov?.basis === "topic" && ov.topic === d.topic ? ` · ${L.r_total.replace("{t}", ov.total.toLocaleString("de-CH"))}` : "";
      count = `${L.r_count_browse.replace("{n}", String(n)).replace("{t}", t)} · ${L.r_sorted_year}${total}`;
    } else if (d.mode === "query_topic") count = `${L.r_count_topic.replace("{n}", String(n)).replace("{q}", q).replace("{t}", t)} · ${L.r_sorted_rel}`;
    else count = `${L.r_count.replace("{n}", String(n)).replace("{q}", q)} · ${L.r_sorted_rel}`;
    if (d.mode === "topic" && n) note = d.stored ? L.r_note_stored : L.r_note_browse;
    if (d.mode === "query_topic") note = n ? L.r_note_qt.replace("{t}", t) : L.r_hint_qt;
  }
  const listLoading = (result.status === "loading" && !result.prev) || (result.status === "idle" && !topicsReady);
  const ovShown = ov && ov.total > 0 && shown ? ov : null;
  const ovPending = ovLoading || (result.status === "idle" && !topicsReady);
  const withOv = Boolean(ovShown) || (ovPending && result.status !== "empty" && result.status !== "error");
  const searchTopic = shown?.topic ?? null;
  const shownQuery = shown?.query ?? null;
  const shownDym = shown?.did_you_mean ?? null;
  const shownResults = shown?.results ?? null;
  const stems = useMemo(() => stemsOf([shownQuery, shownDym]), [shownQuery, shownDym]);
  const dymParts = L.dym.split("{q}");

  useEffect(() => {
    if (!searchTopic || !shownResults) return;
    for (const h of shownResults) {
      const v = verdictOf(h.topic_answer);
      if (open.has(h.openparldata_id) && v && v !== "no") loadEvidence(h.openparldata_id, searchTopic);
    }
  }, [lang, open, shownResults, searchTopic, loadEvidence]);

  const metaLine = (h: Hit) => [
    bodyName(h.body_key, h.body_name, h.level), h.level ? L.levels[h.level as keyof Dict["levels"]] ?? "" : "", h.year ? Math.round(h.year) : "",
    lang === "en" && h.affair_type && h.affair_type !== "unknown" ? h.affair_type : "", h.number ? `${L.no} ${h.number}` : "",
    h.lang && h.lang !== lang && h.lang in L.langnames ? L.original.replace("{l}", L.langnames[h.lang as keyof Dict["langnames"]]) : "",
  ].filter(Boolean).join(" · ");

  const resultSegments = (): Segment[] => merge([
    { text: sentence(count.replaceAll(" · ", ". ")), lang },
    ...hits.slice(0, 5).flatMap((h, i): Segment[] => [
      { text: `${i + 1}.`, lang },
      { text: sentence(titleFor(h) || ""), lang: titleLang(h) },
      { text: sentence([bodyName(h.body_key, h.body_name, h.level), h.year ? String(Math.round(h.year)) : ""].filter(Boolean).join(", ")), lang },
    ]),
  ]);

  const affairSegments = (h: Hit, d: Detail, ev?: Load<Evidence>): Segment[] => {
    const v = verdictOf(h.topic_answer);
    const done = ev?.status === "done" ? ev.data : null;
    const facts = ([[L.r_type, d.type], [L.r_state, d.state]] as [string, string | null | undefined][]).filter(([, x]) => x).map(([k, x]) => sentence(`${k}: ${x}`));
    return merge([
      { text: sentence(titleFor(h) || d.title || ""), lang: titleLang(h) },
      { text: [sentence([bodyName(h.body_key, h.body_name, h.level), h.year ? String(Math.round(h.year)) : ""].filter(Boolean).join(", ")), ...facts].join(" "), lang },
      searchTopic && v && v !== "no" && { text: sentence(`${topicName(searchTopic)}: ${L.verdict[v]}`), lang },
      done?.reason && { text: sentence(`${L.why}: ${done.reason}`), lang },
      (done?.evidence_quote || d.excerpt) && { text: excerpt(done?.evidence_quote || d.excerpt || ""), lang: asLang(h.lang) },
    ]);
  };

  useEffect(() => {
    if (!readNext.current || result.status === "loading" || result.status === "idle") return;
    readNext.current = false;
    if (result.status === "done") speak("results", resultSegments());
  });

  useEffect(() => { stopSpeech(); }, [lang, stopSpeech]);

  const dictation = useDictation((text) => {
    readNext.current = Boolean(support?.server || support?.browser);
    runSearch({ ...f, q: text });
  });
  const readable = Boolean(support?.server || support?.browser);
  const micText = dictation.phase === "listening" ? L.mic_listening : dictation.phase === "working" ? L.mic_working : dictation.phase === "failed" ? L.mic_failed : "";

  const examples = allExamples ? L.examples : L.examples.slice(0, 2);
  const known = new Set(topics.map((t) => t.id));

  useEffect(() => {
    if (f.q) return;
    const t = window.setInterval(() => setExIdx((i) => i + 1), 3500);
    return () => window.clearInterval(t);
  }, [f.q]);

  const query = f.q;
  const suggestion = (() => {
    if (!query) return L.examples[exIdx % L.examples.length];
    const hit = L.examples.find((x) => x.toLowerCase().startsWith(query.toLowerCase()) && x.length > query.length);
    return hit ? query + hit.slice(query.length) : "";
  })();
  const ghostRest = suggestion ? suggestion.slice(query.length) : "";

  return (
    <div className="page" translate="no">
      <div className="topbar"><span>OpenParlData · {bodies.length || 88} {L.parl}</span><span>{L.topright}</span></div>
      <Hero lang={lang} onLang={setLang} />

      <section className="finder" id="finder" ref={finderRef}>
        <span className="num">{L.s_num}</span>
        <h2>{L.s_h2}</h2>
        <div className="sbar-wrap">
        <form className="sbar" role="search" autoComplete="off" onSubmit={(e) => { e.preventDefault(); runSearch(f.q.trim() || f.topic ? f : { ...f, q: suggestion }); }}>
          <div className="qwrap">
            <div className="ghost" aria-hidden="true"><span className="typed">{f.q}</span><span className="rest">{ghostRest}</span></div>
            <input id="q" type="search" aria-label={L.s_go} placeholder="" value={f.q}
              onChange={(e) => setF({ ...f, q: e.target.value })}
              onKeyDown={(e) => {
                const atEnd = e.currentTarget.selectionStart === f.q.length;
                if (suggestion && ((e.key === "Tab" && !e.shiftKey) || (e.key === "ArrowRight" && atEnd))) {
                  e.preventDefault();
                  setF({ ...f, q: suggestion });
                }
              }} />
          </div>
          {support?.dictation && (
            <button type="button" className={`mic${dictation.phase === "listening" ? " on" : ""}`} aria-label={dictation.phase === "listening" ? L.mic_stop : L.mic}
              title={dictation.phase === "listening" ? L.mic_stop : L.mic} disabled={dictation.phase === "working"} aria-busy={dictation.phase === "working"}
              onClick={() => { stopSpeech(); if (dictation.phase === "listening") dictation.stop(); else dictation.start(); }}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" /></svg>
            </button>
          )}
          <button className="go" id="sgo" type="submit" disabled={result.status === "loading"}><span>{L.s_go}</span><span aria-hidden="true">→</span></button>
        </form>
        <div className={`dym-wrap${shownDym ? " show" : ""}`} aria-live="polite">
          <div className="clip">
            {shownDym && <p className="dym">{dymParts[0]}<button type="button" onClick={() => runSearch({ ...f, q: shownDym })}>{shownDym}</button>{dymParts[1] ?? ""}</p>}
          </div>
        </div>
        <p className="mic-status" role="status">{micText}</p>
        </div>
        <div className="examples">
          {examples.map((x) => <button key={x} type="button" onClick={() => runSearch({ ...f, q: x })}>{x}</button>)}
          {!allExamples && L.examples.length > 2 && <button type="button" className="more" onClick={() => setAllExamples(true)}>{L.ex_more} +</button>}
        </div>
        <div className="filters">
          <label className="field f-topic"><span>{L.f_topic}</span>
            <select id="topic" value={f.topic} onChange={(e) => onTopic(e.target.value)} disabled={!topicsReady} className={topicsReady ? undefined : "sk-select"} aria-busy={!topicsReady}>
              <option value="">{L.f_none}</option>
              {shownTopics.map((g) => (
                <optgroup key={g.label} label={g.label}>
                  {g.items.map((t) => <option key={t.id} value={t.id}>{topicName(t.id)}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          <button type="button" className="more-toggle" aria-expanded={moreFilters} onClick={() => setMoreFilters((v) => !v)}>
            {moreFilters ? L.f_less : L.f_more} {moreFilters ? "−" : "+"}
          </button>
          <div className={`more-filters${moreFilters ? " open" : ""}`}>
            <label className="field"><span>{L.f_level}</span>
              <select id="level" value={f.level} onChange={(e) => onLevel(e.target.value as Level)}>
                {LEVELS.map((l) => <option key={l || "all"} value={l} disabled={Boolean(scope) && l !== scope?.level}>{L.levels[l || "all"]}</option>)}
              </select>
            </label>
            <label className="field"><span>{L.f_body}</span>
              <select id="body" value={scope ? scope.body : f.body} disabled={Boolean(scope)} onChange={(e) => onBody(e.target.value)}>
                <option value="">{L.f_body_all}</option>
                {shownBodies.map((g) => (
                  <optgroup key={g.level} label={L.levels[g.level as keyof Dict["levels"]]}>
                    {g.items.map((b) => <option key={b.body_key} value={b.body_key}>{bodyName(b.body_key, b.body_name, b.level)}</option>)}
                  </optgroup>
                ))}
              </select>
            </label>
            <label className="field"><span>{L.f_from}</span>
              <input id="yfrom" ref={yfromRef} type="number" inputMode="numeric" min={1950} max={2026} placeholder={L.f_year} value={f.yfrom} onChange={(e) => setF({ ...f, yfrom: e.target.value })} />
            </label>
            <label className="field"><span>{L.f_to}</span>
              <input id="yto" ref={ytoRef} type="number" inputMode="numeric" min={1950} max={2026} placeholder={L.f_year} value={f.yto} onChange={(e) => setF({ ...f, yto: e.target.value })} />
            </label>
            <button type="button" className={`since${f.yfrom === "2024" && !f.yto ? " on" : ""}`} onClick={() => rerun({ ...f, yfrom: "2024", yto: "" })}>{L.since2024}</button>
          </div>
        </div>
        {noteText && <p className="fnote" id="fnote" aria-live="polite">{noteText}</p>}
        {reviewer && (
          <section className="review" aria-label={L.rv_queue}>
            <div className="review-head">
              <span className="num">{L.rv_active.replace("{n}", reviewer.name)}</span>
              <button type="button" className="inline" onClick={signOut}>{L.rv_exit}</button>
            </div>
            <p className="note">{L.rv_hint}</p>
            <h3>{L.rv_queue}{queue ? ` (${queue.length})` : ""}</h3>
            {!queue ? <PillSkeleton label={L.r_loading} /> : !queue.length ? <p className="note">{L.rv_none}</p> : (
              <ol className="rq">
                {queue.map((q) => {
                  const key = `${q.openparldata_id}:${q.topic}`, st = corr[key];
                  return (
                    <li key={key}>
                      <span className="rq-title">{titleFor(q) || `#${q.openparldata_id}`}</span>
                      <span className="rq-meta">{[bodyName(q.body_key, q.body_name, q.level), q.year ? String(Math.round(q.year)) : ""].filter(Boolean).join(" · ")}</span>
                      <span className="rq-topic">{topicName(q.topic)} · {q.decision ? L.rv_orig.replace("{d}", q.decision === "yes" ? L.rv_yesno_yes : L.rv_yesno_no) : L.rv_nostore}</span>
                      {(
                        <span className="rq-act">
                          <button type="button" className="rv yes" disabled={st === "sending"} onClick={() => correct(q.openparldata_id, q.topic, "yes")}>{L.rv_yes}</button>
                          <button type="button" className="rv no" disabled={st === "sending"} onClick={() => correct(q.openparldata_id, q.topic, "no")}>{L.rv_no}</button>
                          {st === "failed" && <span className="rv-failed" role="alert">{L.rv_failed}</span>}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
          </section>
        )}
        <p className="note">{L.r_hint}</p>
        <div className="rhead">
          <p className="rcount" id="rcount" aria-live="polite">{count}{updating && <span className="updating-label"> · {L.updating}</span>}</p>
          {readable && result.status === "done" && hits.length > 0 && (
            <ListenButton L={L} label={L.listen_results} phase={speech.key === "results" ? speech.phase : "idle"}
              onPlay={() => speak("results", resultSegments())} onStop={stopSpeech} />
          )}
        </div>
        {note && <p className="note" id="rnote">{note}</p>}
        <div className={`results${withOv ? " with-ov" : ""}`}>
          {withOv && (
            <aside className="ov-aside">
              {ovShown
                ? <OverviewBox L={L} lang={lang} ov={ovShown} body={f.body} bodyName={bodyName} onBody={onBody} updating={ovPending} />
                : <OverviewSkeleton label={L.ov_head} />}
            </aside>
          )}
          <ol className={`hits${updating ? " updating" : ""}`} id="hits" aria-busy={updating || listLoading}>
            {listLoading && <SkeletonRows />}
            {!listLoading && hits.map((h, i) => {
              const id = h.openparldata_id, isOpen = open.has(id), v = verdictOf(h.topic_answer);
              const det = details[`${id}:${lang}`];
              return (
                <li key={id} className={`hit appear${isOpen ? " open" : ""}`} style={{ animationDelay: `${Math.min(i, 10) * 25}ms` }}>
                  <button className="hit-head" type="button" aria-expanded={isOpen} onClick={() => toggle(h, searchTopic)}>
                    <span className="hit-title">{isOpen ? <Marked text={titleFor(h) || `#${id}`} stems={stems} /> : (titleFor(h) || `#${id}`)}</span>
                    <span className="hit-meta">{metaLine(h)}</span>
                    <span className="hit-side">
                      {searchTopic && v && <span className={`tag ${v}`}>{topicName(searchTopic)} · {L.verdict[v]}</span>}
                      {searchTopic && v && h.title_only && <span className="tag-note">{L.title_only_short}</span>}
                      {searchTopic && h.topic_answer?.corrected && <span className="tag-note reviewed">✓ {L.rv_reviewed}</span>}
                    </span>
                    <span className="chev" aria-hidden="true">{isOpen ? L.details_hide : L.details_show}<i className={isOpen ? "up" : ""} /></span>
                  </button>
                  {seen.has(id) && (
                    <div className={`reveal${isOpen ? " open" : ""}`} inert={!isOpen}>
                    <div className="clip">
                    <div className={`hit-body${det?.status === "done" ? " appear" : ""}`}>
                      {!det || det.status !== "done" ? <DetailSkeleton label={L.r_loading} /> : (
                        <AffairBody L={L} id={id} detail={det.data}
                          listen={readable ? <ListenButton L={L} label={L.listen} phase={speech.key === `a:${id}` ? speech.phase : "idle"}
                            onPlay={() => speak(`a:${id}`, affairSegments(h, det.data, searchTopic ? evidence[`${id}:${searchTopic}:${cardHash(searchTopic)}:${lang}`] : undefined))}
                            onStop={stopSpeech} /> : null} titleOnly={Boolean(h.title_only)} verdict={v} searchTopic={searchTopic} stems={stems} titleFor={titleFor}
                          live={live[id]} evidence={searchTopic ? evidence[`${id}:${searchTopic}:${cardHash(searchTopic)}:${lang}`] : undefined}
                          similar={similarRows[id]} flags={flags} known={known} topicName={topicName} bodyName={bodyName}
                          reviewing={Boolean(reviewer)} corr={corr} onCorrect={(t, d) => correct(id, t, d)}
                          contextOpen={context.has(id)} onContext={() => setContext((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; })}
                          onRetryEvidence={() => { if (searchTopic) loadEvidence(id, searchTopic, true); }}
                          onPick={(t) => { onTopic(t); scrollToFinder(); }} onFlag={flag} onSimilar={() => similar(id)}
                          onSimilarPick={(title) => { runSearch({ ...f, q: title }); scrollToFinder(); }} />
                      )}
                    </div>
                    </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      </section>

      <footer>
        <span>{L.footer}</span>
        {reviewAvail && !reviewer && (reviewLogin ? (
          <form className="rv-login" onSubmit={(e) => { e.preventDefault(); const fd = new FormData(e.currentTarget); signIn(String(fd.get("name") ?? ""), String(fd.get("code") ?? "")); }}>
            <span className="num">{L.rv_login}</span>
            <label>{L.rv_name}<input name="name" required maxLength={80} autoComplete="name" /></label>
            <label>{L.rv_code}<input name="code" type="password" required autoComplete="current-password" /></label>
            <button type="submit" className="rv yes">{L.rv_enter}</button>
            {reviewBad && <span className="rv-failed" role="alert">{L.rv_bad}</span>}
          </form>
        ) : <button type="button" className="inline rv-open" onClick={() => setReviewLogin(true)}>{L.rv_mode}</button>)}
      </footer>
    </div>
  );
}

const SK_TITLES: [number, number][] = [[88, 54], [72, 0], [94, 38], [66, 0], [81, 47]];

function SkeletonRows() {
  return (
    <>
      {SK_TITLES.map(([a, b], i) => (
        <li key={i} className="hit sk-row" aria-hidden="true">
          <span className="sk sk-title" style={{ width: `${a}%` }} />
          {b > 0 && <span className="sk sk-title" style={{ width: `${b}%` }} />}
          <span className="sk sk-meta" style={{ width: `${30 + (i * 7) % 18}%` }} />
          <span className="sk sk-link" />
        </li>
      ))}
    </>
  );
}

function DetailSkeleton({ label }: { label: string }) {
  return (
    <div className="sk-detail">
      <span className="sr-only">{label}</span>
      <div className="sk-chips" aria-hidden="true">
        {[132, 168, 140].map((w) => <span key={w} className="sk sk-chip" style={{ width: w }} />)}
      </div>
      <div className="sk-passage" aria-hidden="true">
        {[96, 91, 64].map((w) => <span key={w} className="sk sk-line" style={{ width: `${w}%` }} />)}
      </div>
      <span className="sk sk-line" style={{ width: "58%" }} aria-hidden="true" />
      <PillSkeleton />
    </div>
  );
}

function PillSkeleton({ label }: { label?: string }) {
  return (
    <>
      {label && <span className="sr-only">{label}</span>}
      <ul className="sk-pills" aria-hidden="true">
        {[176, 132, 204, 148].map((w) => <li key={w} className="sk sk-pill" style={{ width: w }} />)}
      </ul>
    </>
  );
}

function OverviewSkeleton({ label }: { label: string }) {
  return (
    <div className="overview sk-overview" aria-busy="true">
      <span className="num">{label}</span>
      <div className="sk-ov-line" aria-hidden="true">
        <span className="sk sk-line" style={{ width: "92%" }} />
        <span className="sk sk-line" style={{ width: "61%" }} />
      </div>
      <span className="sk sk-ov-toggle" aria-hidden="true" />
      <ol className="ov-bars sk-ov-bars" aria-hidden="true">
        {[100, 82, 71, 58, 44, 33].map((w, i) => (
          <li key={i}>
            <span className="sk sk-name" style={{ width: `${70 - (i * 9) % 30}%` }} />
            <span className="sk sk-bar" style={{ width: `${w}%` }} />
            <span className="sk sk-n" />
          </li>
        ))}
      </ol>
    </div>
  );
}

interface OverviewProps {
  L: Dict;
  lang: Lang;
  ov: Overview;
  updating?: boolean;
  body: string;
  bodyName: (key?: string | null, name?: string | null, level?: string | null) => string;
  onBody: (body: string) => void;
}

function OverviewBox({ L, lang, ov, body, bodyName, onBody, updating }: OverviewProps) {
  const [bars, setBars] = useState(false);
  const counts = OUTCOME_ORDER.filter((k) => ov.outcomes[k] > 0);
  const names = (k: (typeof OUTCOME_ORDER)[number]) => ov.outcome_names[k]?.[lang] ?? ov.outcome_names[k]?.de ?? k;
  const line = (ov.parliaments === 1 ? L.ov_line_one : L.ov_line).replace("{n}", ov.total.toLocaleString("de-CH")).replace("{p}", String(ov.parliaments));
  const pool = ov.pool ? (ov.basis === "similar" ? L.ov_pool_topic : L.ov_pool).replace("{k}", String(ov.pool)) : "";
  const top = ov.by_body.slice(0, 8);
  const max = Math.max(1, ...top.map((b) => b.total));
  const selected = ov.by_body.find((b) => b.body_key === body);
  return (
    <div className={`overview appear${bars ? " bars-open" : ""}${updating ? " updating" : ""}`} aria-live="polite" aria-busy={updating}>
      <span className="num">{L.ov_head}</span>
      <p className="ov-line">
        {pool && <span className="ov-pool">{pool}: </span>}
        <b>{line}</b>
        {counts.length > 0 && <span className="ov-rest">: {counts.map((k, i) => (
          <Fragment key={k}><span className="ov-count"><i className={`sw o-${k}`} aria-hidden="true" />{ov.outcomes[k]} {names(k)}{i < counts.length - 1 ? "," : ""}</span>{i < counts.length - 1 ? " " : ""}</Fragment>
        ))}</span>}
      </p>
      <button type="button" className="ov-toggle" aria-expanded={bars} onClick={() => setBars((v) => !v)}>{bars ? L.ov_hide : L.ov_show}</button>
      <ol className="ov-bars">
        {top.map((b) => {
          const key = b.body_key ?? "", name = bodyName(b.body_key, b.body_name, b.level), active = body === key;
          return (
            <li key={key}>
              <button type="button" aria-pressed={active} className={active ? "on" : ""} onClick={() => onBody(active ? "" : key)}>
                <span className="ov-name">{name}</span>
                <span className="ov-track" style={{ width: `${(100 * b.total) / max}%` }}>
                  {OUTCOME_ORDER.filter((k) => b.outcomes[k] > 0).map((k) => (
                    <span key={k} className={`seg o-${k}`} style={{ width: `${(100 * b.outcomes[k]) / b.total}%` }} title={`${b.outcomes[k]} ${names(k)}`} />
                  ))}
                </span>
                <span className="ov-n">{b.total}</span>
              </button>
            </li>
          );
        })}
      </ol>
      <div className="ov-foot">
        {body ? <button type="button" className="ov-clear" onClick={() => onBody("")}>{L.ov_only.replace("{b}", bodyName(body, selected?.body_name, selected?.level))} · {L.ov_all} ×</button>
          : <p className="note ov-hint">{L.ov_hint}</p>}
        {ov.outcomes.closed > 0 && <p className="note">{L.ov_closed}</p>}
      </div>
    </div>
  );
}

interface BodyProps {
  L: Dict;
  id: number;
  listen: ReactNode;
  detail: Detail;
  titleOnly: boolean;
  verdict: Verdict | null;
  searchTopic: string | null;
  stems: string[];
  titleFor: (x: Titled) => string;
  live?: Load<LiveTopic[]>;
  evidence?: Load<Evidence>;
  similar?: SimilarAffair[];
  flags: Record<string, FlagState>;
  reviewing: boolean;
  corr: Record<string, FlagState>;
  onCorrect: (topic: string, decision: "yes" | "no") => void;
  known: Set<string>;
  contextOpen: boolean;
  topicName: (id: string, names?: Partial<Record<Lang, string>>) => string;
  bodyName: (key?: string | null, name?: string | null, level?: string | null) => string;
  onContext: () => void;
  onRetryEvidence: () => void;
  onPick: (topic: string) => void;
  onFlag: (id: number, topic: string) => void;
  onSimilar: () => void;
  onSimilarPick: (title: string) => void;
}

function ListenButton({ L, label, phase, onPlay, onStop }: { L: Dict; label: string; phase: SpeakPhase; onPlay: () => void; onStop: () => void }) {
  const on = phase !== "idle";
  return (
    <button type="button" className={`listen${on ? " on" : ""}`} aria-busy={phase === "loading"} onClick={on ? onStop : onPlay}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        {on ? <rect x="7" y="7" width="10" height="10" /> : <><path className="fill" d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" /><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" /></>}
      </svg>
      <span>{phase === "loading" ? L.listen_loading : on ? L.listen_stop : label}</span>
    </button>
  );
}

function FlagButton({ L, state, label, className, onFlag }: { L: Dict; state?: FlagState; label: string; className: string; onFlag: () => void }) {
  if (state === "done") return <span className={`${className} done`}>{L.t_reported}</span>;
  if (state === "failed") return <button type="button" className={`${className} failed`} onClick={onFlag}>{L.flag_failed} {L.retry}</button>;
  return <button type="button" className={className} disabled={state === "sending"} onClick={onFlag}>{label}</button>;
}

function AffairBody({ L, id, listen, detail: d, titleOnly, verdict, searchTopic, stems, titleFor, live, evidence: ev, similar, flags, reviewing, corr, onCorrect, known, contextOpen, topicName, bodyName,
  onContext, onRetryEvidence, onPick, onFlag, onSimilar, onSimilarPick }: BodyProps) {
  const facts = ([[L.r_type, d.type], [L.r_state, d.state], [L.r_date, d.begin_date]] as [string, string | null | undefined][]).filter(([, x]) => x);
  const shownTopics = live?.status === "done" ? live.data.filter((r) => r.decision === "yes" || (reviewing && r.corrected)) : [];
  const addable = reviewing && live?.status === "done"
    ? live.data.filter((r) => r.decision === "no" && r.corrected === false).sort((a, b) => topicName(a.topic, a.names).localeCompare(topicName(b.topic, b.names))) : [];
  const yesno = (x?: string) => (x === "yes" ? L.rv_yesno_yes : L.rv_yesno_no);
  const quote = ev?.status === "done" ? ev.data.evidence_quote : null;
  const isTitleOnly = titleOnly || d.text_source === "title_only";
  const suggested = Boolean(searchTopic && verdict && verdict !== "no");
  return (
    <>
      {listen}
      {facts.length > 0 && <div className="facts">{facts.map(([k, x]) => <span key={k}>{k}: {x}</span>)}</div>}
      {suggested && searchTopic && verdict && (
        <div className="suggest">
          <p className="verdict-line"><span className={`tag ${verdict}`}>{topicName(searchTopic)} · {L.verdict[verdict]}</span> {L.auto_check}{isTitleOnly ? ` ${L.title_only}` : ""}</p>
          {ev?.status === "loading" && (
            <div className="sk-evidence" aria-busy="true">
              <figure className="quote sk-quote">
                <figcaption>{L.ev_loading}</figcaption>
                <span className="sk sk-line" style={{ width: "94%" }} aria-hidden="true" />
                <span className="sk sk-line" style={{ width: "68%" }} aria-hidden="true" />
              </figure>
              <span className="sk sk-line" style={{ width: "55%" }} aria-hidden="true" />
            </div>
          )}
          {ev?.status === "failed" && <p className="note">{L.ev_failed} <button type="button" className="inline" onClick={onRetryEvidence}>{L.retry}</button></p>}
          {quote && (
            <figure className="quote appear">
              <figcaption>{L.quote_hint}</figcaption>
              <blockquote>{quote}</blockquote>
            </figure>
          )}
          {ev?.status === "done" && ev.data.reason && <p className="reason appear"><b>{L.why}</b>{ev.data.reason}</p>}
        </div>
      )}
      {d.excerpt && (quote ? (
        <>
          <button type="button" className="inline ctx" aria-expanded={contextOpen} onClick={onContext}>{contextOpen ? L.context_hide : L.context_show}</button>
          {contextOpen && <div className="evidence"><Highlight text={d.excerpt} quote={quote} stems={stems} /></div>}
        </>
      ) : <div className="evidence"><Highlight text={d.excerpt} stems={stems} /></div>)}
      {isTitleOnly && !suggested && <p className="note">{L.title_only}</p>}
      {live?.status !== "failed" && (
        <div className="topics">
          <span className="num">{L.t_head}</span>
          {!live || live.status === "loading" ? <PillSkeleton label={L.t_loading} /> : !shownTopics.length && !addable.length ? <p className="note appear">{L.t_none}</p> : (
            <ul className="appear">
              {shownTopics.map((r) => {
                const v = verdictOf(r)!, key = `${id}:${r.topic}`, st = corr[key];
                const state = r.corrected ? (r.decision === "yes" ? `✓ ${L.rv_reviewed}` : L.rv_removed) : L.verdict[v];
                const label = `${topicName(r.topic, r.names)} · ${state}`;
                const orig = r.corrected && r.original_decision ? L.rv_orig.replace("{d}", yesno(r.original_decision)) : undefined;
                return (
                  <li key={r.topic} className={`pill ${r.corrected ? (r.decision === "yes" ? "yes reviewed" : "no reviewed") : v}`} title={orig}>
                    {known.has(r.topic)
                      ? <button type="button" className="pick" title={orig ?? L.t_pick} onClick={() => onPick(r.topic)}>{label}</button>
                      : <button type="button" className="pick" disabled>{label}</button>}
                    {reviewing ? (
                      <>
                        <button type="button" className="rv-mini" aria-label={`${topicName(r.topic, r.names)}: ${L.rv_yes}`} title={L.rv_yes}
                          aria-pressed={r.corrected && r.decision === "yes"} disabled={st === "sending"} onClick={() => onCorrect(r.topic, "yes")}>✓</button>
                        <button type="button" className="rv-mini" aria-label={`${topicName(r.topic, r.names)}: ${L.rv_no}`} title={L.rv_no}
                          aria-pressed={r.corrected && r.decision === "no"} disabled={st === "sending"} onClick={() => onCorrect(r.topic, "no")}>✕</button>
                        {st === "failed" && <span className="done failed">{L.rv_failed}</span>}
                      </>
                    ) : !r.corrected && <FlagButton L={L} state={flags[key]} label={L.t_wrong} className="wrong" onFlag={() => onFlag(id, r.topic)} />}
                  </li>
                );
              })}
            </ul>
          )}
          {reviewing && addable.length > 0 && (
            <select className="rv-add" value="" aria-label={L.rv_add} onChange={(e) => { if (e.target.value) onCorrect(e.target.value, "yes"); }}>
              <option value="">{L.rv_add}</option>
              {addable.map((r) => <option key={r.topic} value={r.topic}>{topicName(r.topic, r.names)}</option>)}
            </select>
          )}
        </div>
      )}
      <div className="links">
        {d.url_external && <a href={d.url_external} target="_blank" rel="noopener noreferrer">{L.r_open} ↗</a>}
        <a href={d.url_openparldata} target="_blank" rel="noopener noreferrer">OpenParlData ↗</a>
        {!similar && <button type="button" data-act="sim" onClick={onSimilar}>{L.r_similar}</button>}
        {searchTopic && (verdict === "yes" || verdict === "likely") && (
          <FlagButton L={L} state={flags[`${id}:${searchTopic}`]} label={L.flag.replace("{t}", topicName(searchTopic))} className="flag" onFlag={() => onFlag(id, searchTopic)} />
        )}
      </div>
      {similar && (
        <div className="similar">
          <span className="num">{L.r_similar}</span>
          <ol>
            {similar.map((x) => (
              <li key={x.openparldata_id}>
                <button type="button" onClick={() => onSimilarPick(titleFor(x))}>
                  <span className="t">{(titleFor(x) || `#${x.openparldata_id}`).slice(0, 150)}</span>
                  <span className="w">{bodyName(x.body_key, x.body_name)}</span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}
    </>
  );
}
