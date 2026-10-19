"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Lang } from "./i18n";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";
// Browsers ship no Romansh voice; a German voice reads it more faithfully than the default English one.
const BCP47: Record<Lang, string> = { de: "de-CH", fr: "fr-CH", it: "it-CH", rm: "de-CH", en: "en-GB" };

export interface Segment { text: string; lang: Lang }
export interface SpeechSupport { server: boolean; browser: boolean; dictation: boolean }
export type SpeakPhase = "idle" | "loading" | "playing";
export type DictationPhase = "idle" | "listening" | "working" | "failed";

export async function speechSupport(): Promise<SpeechSupport> {
  const browser = typeof window !== "undefined" && "speechSynthesis" in window;
  const recorder = typeof window !== "undefined" && "MediaRecorder" in window && Boolean(navigator.mediaDevices?.getUserMedia);
  try {
    const r = await fetch(`${BASE}/speech`);
    const s = r.ok ? await r.json() : {};
    return { server: Boolean(s.read_aloud), browser, dictation: recorder && Boolean(s.voice_search) };
  } catch {
    return { server: false, browser, dictation: false };
  }
}

export function merge(parts: (Segment | null | false | "" | undefined)[], limit = 280): Segment[] {
  const out: Segment[] = [];
  for (const p of parts) {
    if (!p || !p.text.trim()) continue;
    const last = out[out.length - 1];
    if (last && last.lang === p.lang && last.text.length + p.text.length < limit) last.text = `${last.text} ${p.text}`;
    else out.push({ ...p });
  }
  return out;
}

export function sentence(s: string): string {
  const t = s.trim();
  return !t ? "" : /[.!?…:]$/.test(t) ? t : `${t}.`;
}

export function excerpt(s: string, max = 600): string {
  const t = s.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max), end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("? "), cut.lastIndexOf("! "));
  return end > max / 3 ? cut.slice(0, end + 1) : `${cut.slice(0, cut.lastIndexOf(" "))} …`;
}

export function useSpeaker(support: SpeechSupport | null) {
  const [state, setState] = useState<{ key: string | null; phase: SpeakPhase }>({ key: null, phase: "idle" });
  const audio = useRef<HTMLAudioElement | null>(null);
  const run = useRef(0);
  const ctrl = useRef<AbortController | null>(null);
  const urls = useRef<Map<string, string>>(new Map());

  const stop = useCallback(() => {
    run.current += 1;
    ctrl.current?.abort();
    ctrl.current = null;
    audio.current?.pause();
    if (typeof window !== "undefined") window.speechSynthesis?.cancel();
    setState({ key: null, phase: "idle" });
  }, []);

  const fetchAudio = useCallback(async (seg: Segment, signal: AbortSignal) => {
    const id = `${seg.lang}|${seg.text}`;
    const known = urls.current.get(id);
    if (known) return known;
    const r = await fetch(`${BASE}/speech`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(seg), signal });
    if (!r.ok) throw new Error(String(r.status));
    const url = URL.createObjectURL(await r.blob());
    urls.current.set(id, url);
    return url;
  }, []);

  const playUrl = (url: string, mine: number) => new Promise<void>((resolve, reject) => {
    const a = audio.current ?? (audio.current = new Audio());
    a.src = url;
    a.onended = () => resolve();
    a.onerror = () => reject(new Error("audio"));
    a.play().catch(reject);
    if (run.current !== mine) a.pause();
  });

  const sayInBrowser = (segs: Segment[], mine: number) => new Promise<void>((resolve) => {
    const synth = window.speechSynthesis;
    if (!synth) return resolve();
    const voices = synth.getVoices();
    segs.forEach((seg, i) => {
      const u = new SpeechSynthesisUtterance(seg.text);
      u.lang = BCP47[seg.lang];
      const v = voices.find((x) => x.lang.toLowerCase().startsWith(u.lang.slice(0, 2)));
      if (v) u.voice = v;
      if (i === segs.length - 1) { u.onend = () => resolve(); u.onerror = () => resolve(); }
      if (run.current === mine) synth.speak(u);
    });
  });

  const speak = useCallback(async (key: string, segs: Segment[]) => {
    stop();
    if (!segs.length) return;
    const mine = run.current;
    const c = new AbortController();
    ctrl.current = c;
    const done = () => { if (run.current === mine) setState({ key: null, phase: "idle" }); };
    if (!support?.server) {
      if (!support?.browser) return;
      setState({ key, phase: "playing" });
      await sayInBrowser(segs, mine);
      return done();
    }
    setState({ key, phase: "loading" });
    try {
      let next = fetchAudio(segs[0], c.signal);
      for (let i = 0; i < segs.length; i++) {
        const url = await next;
        if (run.current !== mine) return;
        if (i + 1 < segs.length) next = fetchAudio(segs[i + 1], c.signal);
        setState({ key, phase: "playing" });
        await playUrl(url, mine);
        if (run.current !== mine) return;
      }
      done();
    } catch {
      if (run.current !== mine || c.signal.aborted) return;
      if (support.browser) {
        setState({ key, phase: "playing" });
        await sayInBrowser(segs, mine);
      }
      done();
    }
  }, [support, stop, fetchAudio]);

  useEffect(() => {
    if (state.phase === "idle") return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") stop(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.phase, stop]);

  useEffect(() => () => { stop(); urls.current.forEach((u) => URL.revokeObjectURL(u)); }, [stop]);

  return { state, speak, stop };
}

export function useDictation(onText: (text: string, lang: Lang | null) => void) {
  const [phase, setPhase] = useState<DictationPhase>("idle");
  const rec = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const cb = useRef(onText);
  useEffect(() => { cb.current = onText; });

  const stop = useCallback(() => {
    if (rec.current?.state === "recording") rec.current.stop();
  }, []);

  const start = useCallback(async () => {
    if (rec.current?.state === "recording") return stop();
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setPhase("failed");
      return;
    }
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported(t));
    const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks: Blob[] = [];
    r.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    r.onstop = async () => {
      window.clearTimeout(timer.current);
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks, { type: (r.mimeType || "audio/webm").split(";")[0] });
      if (blob.size < 1000) { setPhase("idle"); return; }
      setPhase("working");
      try {
        const res = await fetch(`${BASE}/speech/transcribe`, { method: "POST", headers: { "Content-Type": blob.type }, body: blob });
        const d = res.ok ? await res.json() : null;
        if (!d?.text) throw new Error("empty");
        setPhase("idle");
        cb.current(d.text, d.lang ?? null);
      } catch {
        setPhase("failed");
      }
    };
    rec.current = r;
    r.start();
    setPhase("listening");
    timer.current = window.setTimeout(() => { if (r.state === "recording") r.stop(); }, 12000);
  }, [stop]);

  useEffect(() => () => { window.clearTimeout(timer.current); if (rec.current?.state === "recording") rec.current.stop(); }, []);

  return { phase, start, stop };
}
