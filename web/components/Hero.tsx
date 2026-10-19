"use client";

import { useEffect, useRef } from "react";
import { startAlps } from "@/lib/alps";
import { I18N, LANGS, type Lang } from "@/lib/i18n";

interface Props {
  lang: Lang;
  onLang: (lang: Lang) => void;
}

export default function Hero({ lang, onLang }: Props) {
  const heroRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const labelsRef = useRef<string[]>(I18N[lang].canvas);
  const L = I18N[lang];

  useEffect(() => {
    labelsRef.current = I18N[lang].canvas;
  }, [lang]);

  useEffect(() => {
    const hero = heroRef.current, cv = canvasRef.current;
    if (!hero || !cv) return;
    return startAlps(hero, cv, () => labelsRef.current, ".langs");
  }, []);

  return (
    <header className="hero" id="hero" ref={heroRef}>
      <canvas ref={canvasRef} aria-hidden="true" />
      <div className="hero-text">
        <nav className="langs" id="langs" aria-label={L.langs}>
          {LANGS.map((l) => (
            <span key={l} className="lang-slot">
              {l === "en" && <i className="sep" aria-hidden="true" />}
              <button type="button" lang={l} data-l={l} aria-pressed={l === lang}
                onMouseOver={() => onLang(l)} onFocus={() => onLang(l)} onClick={() => onLang(l)}>
                {l.toUpperCase()}
              </button>
            </span>
          ))}
        </nav>
        <h1><span>{L.h1a}</span><em>{L.h1b}</em></h1>
        <p className="lede">{L.lede}</p>
      </div>
    </header>
  );
}
