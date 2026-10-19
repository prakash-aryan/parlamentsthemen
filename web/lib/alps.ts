type Pt = [number, number];
type Stroke = [number, number, number];

const TOPIC_COLOURS = ["#e3000f", "#2160c4", "#0a8f4d", "#8a3fc0", "#d98b00", "#0094a8", "#c2185b"];
const RIDGE: Pt[] = [[-80, 2200], [0, 2350], [40, 2650], [70, 3050], [95, 3450], [110, 3692], [122, 3540], [135, 3704], [146, 3610], [158, 3689], [178, 3350], [195, 3150],
  [212, 3300], [230, 3620], [246, 3920], [255, 4078], [262, 3985], [272, 4042], [290, 3720], [306, 3480], [322, 3500], [345, 3820], [362, 4120], [370, 4274],
  [381, 4110], [398, 3860], [420, 3620], [442, 3480], [465, 3390], [482, 3560], [499, 3730], [512, 3890], [520, 3967], [530, 3840], [546, 3620], [562, 3470],
  [578, 3580], [592, 3820], [606, 4010], [616, 4092], [624, 4110], [634, 4078], [647, 3950], [662, 3700], [680, 3466], [697, 3560], [710, 3680], [718, 3695],
  [728, 3630], [743, 3910], [755, 4110], [762, 4158], [773, 4070], [791, 3850], [812, 3700], [832, 3800], [850, 3983], [866, 3870], [885, 3962], [902, 3700],
  [918, 3800], [936, 3600], [952, 3754], [975, 3520], [1000, 3780], [1020, 3460], [1042, 3300], [1062, 3360], [1078, 3590], [1088, 3661], [1098, 3560],
  [1108, 3650], [1118, 3590], [1128, 3623], [1146, 3400], [1172, 3020], [1200, 2700], [1280, 2300]];
const PREALPS: Pt[] = [[-80, 1500], [0, 1700], [30, 1950], [62, 2150], [80, 2197], [140, 2170], [165, 1980], [200, 1700], [250, 1600], [300, 1880], [330, 2051],
  [352, 1900], [400, 1550], [470, 1320], [560, 1250], [680, 1300], [780, 1380], [860, 1650], [915, 2000], [955, 2362], [995, 2050], [1030, 1700], [1055, 1820],
  [1078, 2150], [1084, 2190], [1102, 2178], [1108, 1980], [1135, 1930], [1160, 2080], [1176, 2175], [1200, 1950], [1280, 1600]];

interface Slip {
  x: number; y: number; vx: number; vy: number; rot: number; vr: number; ph: number; topic: number; read: number;
}

interface Cloud {
  u: number; y: number; w: number; sp: number; a: number; s: HTMLCanvasElement; layer: number;
}

export function startAlps(hero: HTMLElement, cv: HTMLCanvasElement, labels: () => string[], ignore: string): () => void {
  const ctx = cv.getContext("2d");
  if (!ctx) return () => {};
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let seed = 11;
  const rnd = () => (seed = seed * 16807 % 2147483647) / 2147483647;
  const Y = (a: number) => 300 - (a - 2600) * 0.16, YP = (a: number) => 300 - (a - 900) * 0.085;
  const crag = (pts: Pt[], depth: number, amp: number): Pt[] => {
    let out = pts;
    for (let d = 0; d < depth; d++) {
      const next: Pt[] = [out[0]];
      for (let i = 1; i < out.length; i++) {
        const [x0, y0] = out[i - 1], [x1, y1] = out[i], len = Math.hypot(x1 - x0, y1 - y0);
        next.push([(x0 + x1) / 2 + (rnd() - .5) * (x1 - x0) * .3, Math.max((y0 + y1) / 2 + (rnd() - .5) * len * amp, Math.min(y0, y1) + .4)], out[i]);
      }
      out = next;
    }
    return out;
  };
  const far = crag(RIDGE.map(([x, a]): Pt => [x, Y(a)]), 4, .3);
  const pre = crag(PREALPS.map(([x, a]): Pt => [x, YP(a)]), 3, .16);
  const hatch: { shade: Stroke[]; rock: Stroke[]; light: Stroke[] } = { shade: [], rock: [], light: [] };
  for (let i = 1; i < far.length; i++) {
    const [x0, y0] = far[i - 1], [x1, y1] = far[i];
    if (x1 <= x0) continue;
    const sl = (y1 - y0) / (x1 - x0);
    for (let x = Math.ceil(x0 / 2.4) * 2.4; x < x1; x += 2.4) {
      const y = y0 + sl * (x - x0) + 1;
      if (sl > .12) hatch.shade.push([x, y, (8 + Math.min(70, sl * 24)) * (.6 + rnd() * .7)]);
      if (sl > 2) hatch.rock.push([x, y, (4 + Math.min(26, sl * 5)) * (.6 + rnd() * .6)]);
      if (sl < -1.2 && rnd() < .35) hatch.light.push([x, y, (5 + Math.min(26, -sl * 6)) * (.5 + rnd() * .7)]);
    }
  }
  const hills: Pt[] = [], trees: Stroke[] = [];
  for (let x = -80; x <= 1280; x += 6) {
    const y = 280 + Math.sin(x / 97) * 7 + Math.sin(x / 37 + 1) * 3;
    hills.push([x, y]);
    if (Math.sin(x / 53) + Math.sin(x / 19) > .3) trees.push([x + rnd() * 3, y + 1, 4 + rnd() * 5]);
  }
  const sprite = () => {
    const c = document.createElement("canvas"), g = c.getContext("2d");
    c.width = 320; c.height = 90;
    if (!g) return c;
    for (let i = 0; i < 16; i++) {
      const x = 320 * (.12 + rnd() * .76), y = 90 * (.5 + rnd() * .22), r = 90 * (.18 + rnd() * .26);
      const grd = g.createRadialGradient(x, y, 0, x, y, r);
      grd.addColorStop(0, "rgba(255,255,255,.85)"); grd.addColorStop(1, "rgba(255,255,255,0)");
      g.fillStyle = grd; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
    }
    return c;
  };
  const sprites = [sprite(), sprite(), sprite()];
  const clouds: Cloud[] = Array.from({ length: 9 }, (_, i) => ({
    u: -200 + rnd() * 1500, y: i < 5 ? 205 + rnd() * 50 : 120 + rnd() * 45, w: 160 + rnd() * 220,
    sp: (i < 5 ? .006 : .01) * (.6 + rnd() * .8), a: i < 5 ? .7 : .35, s: sprites[i % 3], layer: i < 5 ? 0 : 1,
  }));
  const LAND = .45;
  const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const mix = (a: string, b: string, k: number) => { const A = hex(a), B = hex(b); return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * k)).join(",")})`; };

  let W = 0, H = 0, dpr = 1, s = 1, sy = 1, uc = 600, last = 0, running = true, frame = 0, alive = true;
  const parts: Slip[] = [];
  const ptr = { x: 0, y: 0, tx: 0, ty: 0, rx: 0, ry: 0, vis: 0, until: 0, active: false };
  let pinned: Slip | null = null, pinnedUntil = 0;
  const spawn = (x: number, y: number, burst: boolean): Slip => ({
    x, y, vx: burst ? (rnd() - .5) * 3 : .2 + rnd() * .3, vy: burst ? (rnd() - .5) * 3 : (rnd() - .5) * .2,
    rot: rnd() * 6, vr: (rnd() - .5) * .03, ph: rnd() * 6, topic: Math.floor(rnd() * TOPIC_COLOURS.length), read: 0,
  });
  const skyTop = () => H * .05, skyBottom = () => H - (300 - 150) * sy;

  function poly(pts: Pt[], px: (u: number) => number, ty: (v: number) => number, close: boolean) {
    ctx!.beginPath();
    pts.forEach(([u, v], i) => (i ? ctx!.lineTo(px(u), ty(v)) : ctx!.moveTo(px(u), ty(v))));
    if (close) { ctx!.lineTo(px(pts[pts.length - 1][0]), H + 2); ctx!.lineTo(px(pts[0][0]), H + 2); ctx!.closePath(); }
  }

  function draw(t: number) {
    const c = ctx!;
    const dt = Math.min(50, t - last || 16), k = dt / 16.7;
    last = t;
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, W, H);
    if (ptr.until && t > ptr.until) { ptr.active = false; ptr.until = 0; }
    ptr.vis += ((ptr.active ? 1 : 0) - ptr.vis) * .07 * k;
    ptr.rx += (ptr.tx - ptr.rx) * .16 * k; ptr.ry += (ptr.ty - ptr.ry) * .16 * k;
    ptr.x += ((ptr.active ? ptr.rx / W - .5 : 0) - ptr.x) * .03 * k; ptr.y += ((ptr.active ? ptr.ry / H - .5 : 0) - ptr.y) * .03 * k;
    const cyc = (t / 36000) % 1, g = Math.pow(Math.max(0, Math.sin(cyc * Math.PI * 2)), 1.4);
    const layer = (f: number) => (u: number) => W / 2 + (u - uc) * s - ptr.x * W * f + Math.sin(t * .00004) * W * f * .4;
    const lift = (f: number) => (v: number) => H - (300 - v) * sy - ptr.y * H * f * .4;

    const sky = c.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0, "#f6f4ef"); sky.addColorStop(.6, mix("#f6f4ef", "#f8f0ea", g)); sky.addColorStop(1, mix("#f3f3f0", "#f7eee7", g));
    c.fillStyle = sky; c.fillRect(0, 0, W, H);

    const pf = layer(.012), tf = lift(.012);
    const sunX = pf(1010), sunY = tf(40 + g * 130), sr = 30 * s;
    const sun = c.createRadialGradient(sunX, sunY, 0, sunX, sunY, sr * 3);
    sun.addColorStop(0, `rgba(255,${Math.round(214 - g * 50)},${Math.round(180 - g * 60)},.25)`); sun.addColorStop(.33, "rgba(255,200,170,.08)"); sun.addColorStop(1, "rgba(255,200,170,0)");
    c.fillStyle = sun; c.beginPath(); c.arc(sunX, sunY, sr * 3, 0, 7); c.fill();

    c.globalAlpha = LAND;
    const snow = c.createLinearGradient(0, tf(40), 0, tf(300));
    snow.addColorStop(0, mix("#fbfbfa", "#fde2d6", g * .8)); snow.addColorStop(.35, mix("#f3f4f4", "#f8e6de", g * .5)); snow.addColorStop(.75, "#e9edef"); snow.addColorStop(1, "#e2e7ea");
    poly(far, pf, tf, true); c.fillStyle = snow; c.fill();
    const strokes = (list: Stroke[], colour: string, width: number) => {
      c.beginPath();
      list.forEach(([u, v, l]) => { const x = pf(u); if (x < -2 || x > W + 2) return; c.moveTo(x, tf(v)); c.lineTo(x, tf(v + l)); });
      c.strokeStyle = colour; c.lineWidth = width; c.stroke();
    };
    strokes(hatch.shade, "rgba(59,74,92,.16)", Math.max(.5, .7 * s));
    strokes(hatch.light, "rgba(59,74,92,.08)", Math.max(.4, .55 * s));
    strokes(hatch.rock, "rgba(30,38,48,.26)", Math.max(.6, .95 * s));
    poly(far, pf, tf, false); c.strokeStyle = "rgba(17,17,17,.38)"; c.lineWidth = 1; c.lineJoin = "round"; c.stroke();

    const cloudPass = (lay: number, pfn: (u: number) => number, tfn: (v: number) => number) => clouds.forEach((cl) => {
      if (cl.layer !== lay) return;
      if (!reduce) cl.u += cl.sp * dt;
      if (cl.u > uc + W / (2 * s) + 60) cl.u = uc - W / (2 * s) - cl.w - 60;
      c.globalAlpha = cl.a * LAND; c.drawImage(cl.s, pfn(cl.u), tfn(cl.y) - cl.w * s * 90 / 640, cl.w * s, cl.w * s * 90 / 320);
    });
    cloudPass(1, pf, tf);
    c.globalAlpha = LAND;
    const pp = layer(.03), tp = lift(.03);
    cloudPass(0, pp, tp);
    c.globalAlpha = LAND;
    const haze = c.createLinearGradient(0, tp(170), 0, tp(300));
    haze.addColorStop(0, "#e1e6ea"); haze.addColorStop(1, "#eef0f0");
    poly(pre, pp, tp, true); c.fillStyle = haze; c.fill();
    poly(pre, pp, tp, false); c.strokeStyle = "rgba(93,110,128,.3)"; c.lineWidth = .9; c.stroke();

    const ph = layer(.06), th = lift(.06);
    poly(hills, ph, th, true); c.fillStyle = "#e4e7e6"; c.fill();
    poly(hills, ph, th, false); c.strokeStyle = "rgba(59,74,92,.22)"; c.lineWidth = .8; c.stroke();
    c.beginPath();
    trees.forEach(([u, v, h]) => { const x = ph(u), y = th(v); if (x < -4 || x > W + 4) return; c.moveTo(x - 1.9 * s, y); c.lineTo(x, y - h * sy); c.lineTo(x + 1.9 * s, y); });
    c.fillStyle = "rgba(59,74,92,.16)"; c.fill();

    c.globalAlpha = 1;
    const R = Math.max(44, Math.min(80, W * .065)) * (.8 + .2 * ptr.vis), top = skyTop(), bottom = skyBottom(), seen: [number, Slip][] = [];
    if (ptr.vis > .01) {
      const lens = c.createRadialGradient(ptr.rx, ptr.ry, R * .2, ptr.rx, ptr.ry, R);
      lens.addColorStop(0, `rgba(255,255,255,${.7 * ptr.vis})`); lens.addColorStop(1, "rgba(255,255,255,0)");
      c.fillStyle = lens; c.beginPath(); c.arc(ptr.rx, ptr.ry, R, 0, 7); c.fill();
      c.strokeStyle = `rgba(17,17,17,${.16 * ptr.vis})`; c.lineWidth = 1;
      c.beginPath(); c.arc(ptr.rx, ptr.ry, R, 0, 7); c.stroke();
      c.beginPath();
      for (let a = 0; a < 4; a++) {
        const co = Math.cos(a * Math.PI / 2 + t * .0002), sn = Math.sin(a * Math.PI / 2 + t * .0002);
        c.moveTo(ptr.rx + co * (R + 3), ptr.ry + sn * (R + 3)); c.lineTo(ptr.rx + co * (R + 8), ptr.ry + sn * (R + 8));
      }
      c.strokeStyle = `rgba(17,17,17,${.35 * ptr.vis})`; c.stroke();
    }
    if (!reduce && rnd() < .012 * k) parts[Math.floor(rnd() * parts.length)].read = 1;
    parts.forEach((p) => {
      if (!reduce) {
        p.vx += ((.32 + .22 * Math.sin(p.y * .01 + t * .0003)) - p.vx) * .02 * k;
        p.vy += (Math.sin(p.x * .008 + t * .0005 + p.ph) * .16 - p.vy) * .02 * k;
        if (p.y < top) p.vy += .03 * k;
        if (p.y > bottom) p.vy -= .03 * k;
      }
      const dx = p.x - ptr.rx, dy = p.y - ptr.ry, d = Math.hypot(dx, dy) || 1;
      if (ptr.vis > .3 && d < R) {
        p.read = Math.min(1, p.read + .07 * k);
        if (!reduce) { p.vx += (-dy / d) * .02 * k; p.vy += (dx / d) * .02 * k; }
        seen.push([d, p]);
      } else p.read = Math.max(0, p.read - .003 * k);
      if (!reduce) { p.x += p.vx * k; p.y += p.vy * k; p.rot += p.vr * k; }
      if (p.x > W + 12) Object.assign(p, spawn(-10, top + rnd() * (bottom - top), false));
      if (p.x < -14) p.x = W + 10;
      c.save(); c.translate(p.x, p.y); c.rotate(p.rot);
      c.fillStyle = p.read > .02 ? mix("#ffffff", TOPIC_COLOURS[p.topic], p.read) : "#ffffff";
      c.strokeStyle = "rgba(17,17,17,.32)"; c.lineWidth = .8;
      c.fillRect(-3.5, -4.5, 7, 9); c.strokeRect(-3.5, -4.5, 7, 9);
      c.beginPath(); c.moveTo(-1.8, -2); c.lineTo(1.8, -2); c.moveTo(-1.8, 0); c.lineTo(1.8, 0); c.moveTo(-1.8, 2); c.lineTo(.8, 2);
      c.strokeStyle = p.read > .5 ? "rgba(255,255,255,.8)" : "rgba(17,17,17,.2)"; c.stroke();
      c.restore();
    });

    if (pinned && t > pinnedUntil) pinned = null;
    seen.sort((a, b) => a[0] - b[0]);
    const tags: [number, Slip][] = (pinned ? [[1, pinned] as [number, Slip]] : []).concat(seen.filter(([, p]) => p !== pinned && p.read > .5).map(([, p]): [number, Slip] => [ptr.vis * (p.read - .5) * 2, p]));
    c.font = `600 10px "JetBrains Mono", ui-monospace, monospace`; c.textAlign = "left"; c.textBaseline = "middle";
    const placed: { x: number; y: number; w: number; h: number }[] = [];
    const names = labels();
    for (const [alpha, p] of tags) {
      if (placed.length >= (pinned ? 1 : 3) || alpha <= .02) break;
      const label = (names[p.topic] ?? "").toUpperCase(), w = c.measureText(label).width + 10, h = 16;
      const x = p.x + 9 + w > W ? p.x - 9 - w : p.x + 9, y = p.y - h / 2;
      if (placed.some((r) => x < r.x + r.w + 4 && x + w + 4 > r.x && y < r.y + r.h + 3 && y + h + 3 > r.y)) continue;
      placed.push({ x, y, w, h });
      c.globalAlpha = alpha;
      c.fillStyle = "rgba(255,255,255,.94)"; c.fillRect(x, y, w, h);
      c.strokeStyle = TOPIC_COLOURS[p.topic]; c.lineWidth = 1; c.strokeRect(x + .5, y + .5, w - 1, h - 1);
      c.fillStyle = TOPIC_COLOURS[p.topic]; c.fillText(label, x + 5, y + h / 2 + .5);
      if (p === pinned) { c.beginPath(); c.arc(p.x, p.y, 9 + 2 * Math.sin(t * .008), 0, 7); c.stroke(); }
    }
    c.globalAlpha = 1; c.textBaseline = "alphabetic";
  }

  function resize() {
    W = hero.clientWidth; H = hero.clientHeight; dpr = Math.min(2, devicePixelRatio || 1);
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    const [u0, u1] = W < 700 ? [430, 880] : [0, 1200];
    uc = (u0 + u1) / 2; s = W / (u1 - u0); sy = Math.min(s, H * .68 / 300);
    const n = Math.max(24, Math.min(80, Math.round(W * H / 15000)));
    while (parts.length < n) parts.push(spawn(rnd() * W, skyTop() + rnd() * (skyBottom() - skyTop()), false));
    parts.length = Math.min(parts.length, n + 60);
    if (reduce) draw(5000);
  }

  const loop = (t: number) => { if (!alive) return; if (running) draw(t); frame = requestAnimationFrame(loop); };
  const at = (e: PointerEvent): Pt => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  const onMove = (e: PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    if ((e.target as Element | null)?.closest(ignore)) { ptr.active = false; return; }
    [ptr.tx, ptr.ty] = at(e);
    if (ptr.vis < .05) { ptr.rx = ptr.tx; ptr.ry = ptr.ty; }
    ptr.active = true;
  };
  const onLeave = () => { ptr.active = false; };
  const onDown = (e: PointerEvent) => {
    if ((e.target as Element | null)?.closest(ignore)) return;
    const [x, y] = at(e); ptr.tx = x; ptr.ty = y;
    if (ptr.vis < .05) { ptr.rx = x; ptr.ry = y; }
    ptr.active = true; ptr.until = e.pointerType === "mouse" ? 0 : performance.now() + 2500;
    let best: Slip | null = null, bd = 34;
    parts.forEach((q) => { const d = Math.hypot(q.x - x, q.y - y); if (d < bd) { bd = d; best = q; } });
    const b = best as Slip | null;
    if (b) { pinned = b; pinnedUntil = performance.now() + 3500; b.read = 1; b.vx *= .2; b.vy *= .2; }
  };
  const onVisibility = () => { running = !document.hidden; };
  hero.addEventListener("pointermove", onMove);
  hero.addEventListener("pointerleave", onLeave);
  hero.addEventListener("pointerdown", onDown);
  const ro = new ResizeObserver(resize);
  ro.observe(hero);
  resize();
  let io: IntersectionObserver | null = null;
  if (!reduce) {
    io = new IntersectionObserver(([en]) => { running = en.isIntersecting && !document.hidden; });
    io.observe(hero);
    document.addEventListener("visibilitychange", onVisibility);
    frame = requestAnimationFrame(loop);
  }
  return () => {
    alive = false;
    cancelAnimationFrame(frame);
    ro.disconnect();
    io?.disconnect();
    document.removeEventListener("visibilitychange", onVisibility);
    hero.removeEventListener("pointermove", onMove);
    hero.removeEventListener("pointerleave", onLeave);
    hero.removeEventListener("pointerdown", onDown);
  };
}
