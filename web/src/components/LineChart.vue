<script setup lang="ts">
// Gráfica de líneas en SVG propio: varias series, bandas de fase, umbrales y anotaciones.
// Los huecos (null) cortan la línea. Ejes con trazo croquis; las líneas de datos, nunca.
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { fmt, isNum } from "../lib/format";

export interface ChartPoint {
  x: number;
  y: number | null;
}
export interface ChartSeries {
  id: string;
  label: string;
  color: string;
  points: ChartPoint[];
  dash?: boolean;
}
export interface ChartBand {
  from: number;
  to: number;
  label: string;
}
export interface ChartLine {
  y: number;
  label: string;
  color: string;
}
export interface ChartMarker {
  x: number;
  label: string;
  color?: string;
}

const props = withDefaults(
  defineProps<{
    title: string;
    unit: string;
    series: ChartSeries[];
    bands?: ChartBand[];
    lines?: ChartLine[];
    markers?: ChartMarker[];
    yMin?: number;
    yMax?: number;
    xMax?: number;
    digits?: number;
    height?: number;
    xUnit?: string; // unidad del eje X (por defecto segundos)
    xName?: string; // nombre de la variable X en la lectura
    xMin?: number;
    dots?: boolean; // marcar cada punto (series cortas, p. ej. barridos)
  }>(),
  { bands: () => [], lines: () => [], markers: () => [], digits: 0, height: 150, xUnit: "s", xName: "t", xMin: 0, dots: false },
);

// Ancho real en píxeles (ResizeObserver): el SVG se dibuja 1:1 y el texto no se deforma.
const W = ref(640);
const figRef = ref<HTMLElement | null>(null);
let ro: ResizeObserver | null = null;
onMounted(() => {
  if (!figRef.value || typeof ResizeObserver === "undefined") return;
  ro = new ResizeObserver(([entry]) => (W.value = Math.max(240, Math.round(entry.contentRect.width))));
  ro.observe(figRef.value);
});
onBeforeUnmount(() => ro?.disconnect());
const PAD = { l: 44, r: 12, t: 10, b: 22 };

const xs = computed(() => props.series.flatMap((s) => s.points.map((p) => p.x)));
const ys = computed(() => props.series.flatMap((s) => s.points.map((p) => p.y)).filter(isNum));
const xMaxV = computed(() => Math.max(props.xMax ?? 0, ...xs.value, ...props.bands.map((b) => b.to), 1));
const yRange = computed(() => {
  const vals = [...ys.value, ...props.lines.map((l) => l.y)];
  let lo = props.yMin ?? (vals.length ? Math.min(...vals) : 0);
  let hi = props.yMax ?? (vals.length ? Math.max(...vals) : 1);
  const pad = (hi - lo) * 0.1 || 1;
  if (props.yMin === undefined) lo = lo >= 0 ? Math.max(0, lo - pad) : lo - pad;
  if (props.yMax === undefined) hi = hi + pad;
  if (hi - lo < 1e-9) hi = lo + 1;
  return { lo, hi };
});

const H = computed(() => props.height);
const px = (x: number) => PAD.l + ((x - props.xMin) / (xMaxV.value - props.xMin || 1)) * (W.value - PAD.l - PAD.r);
const py = (y: number) => {
  const { lo, hi } = yRange.value;
  return PAD.t + (1 - (y - lo) / (hi - lo)) * (H.value - PAD.t - PAD.b);
};

function niceStep(span: number, target: number): number {
  const raw = span / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  return (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
}

const yTicks = computed(() => {
  const { lo, hi } = yRange.value;
  const step = niceStep(hi - lo, 4);
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
});
const xTicks = computed(() => {
  const step = niceStep(xMaxV.value - props.xMin || 1, 6);
  const out: number[] = [];
  for (let v = Math.ceil(props.xMin / step) * step; v <= xMaxV.value + 1e-9; v += step) out.push(v);
  return out;
});

const paths = computed(() =>
  props.series.map((s) => {
    const segs: string[] = [];
    let cur = "";
    for (const p of s.points) {
      if (!isNum(p.y)) {
        if (cur) segs.push(cur);
        cur = "";
        continue;
      }
      cur += `${cur ? "L" : "M"}${px(p.x).toFixed(1)},${py(p.y).toFixed(1)}`;
    }
    if (cur) segs.push(cur);
    return { ...s, segs };
  }),
);

function lastValue(s: ChartSeries): number | null {
  for (let i = s.points.length - 1; i >= 0; i--) if (isNum(s.points[i].y)) return s.points[i].y;
  return null;
}

// --- lectura al pasar el ratón
const hoverX = ref<number | null>(null);
const svgRef = ref<SVGSVGElement | null>(null);
function onMove(e: MouseEvent) {
  const el = svgRef.value;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  const sx = ((e.clientX - rect.left) / rect.width) * W.value;
  const x = props.xMin + ((sx - PAD.l) / (W.value - PAD.l - PAD.r)) * (xMaxV.value - props.xMin);
  hoverX.value = x >= props.xMin && x <= xMaxV.value ? x : null;
}
const hoverValues = computed(() => {
  const x = hoverX.value;
  if (x === null) return null;
  return props.series.map((s) => {
    let best: ChartPoint | null = null;
    for (const p of s.points) if (!best || Math.abs(p.x - x) < Math.abs(best.x - x)) best = p;
    const tol = props.dots ? (xMaxV.value - props.xMin) / 10 : (xMaxV.value - props.xMin) / 40;
    return { label: s.label, color: s.color, y: best && Math.abs(best.x - x) < tol ? best.y : null };
  });
});
</script>

<template>
  <figure ref="figRef" class="chart">
    <figcaption class="chart__head">
      <span class="label">{{ title }}</span>
      <span class="legend mono">
        <span v-for="s in series" :key="s.id" class="legend__item">
          <span class="swatch" :class="{ 'swatch--dash': s.dash }" :style="{ background: s.color }" aria-hidden="true" />
          {{ s.label }} <b>{{ fmt(lastValue(s), digits, unit) }}</b>
        </span>
      </span>
    </figcaption>
    <svg
      ref="svgRef"
      :viewBox="`0 0 ${W} ${H}`"
      class="chart__svg"
      :style="{ height: H + 'px' }"
      role="img"
      :aria-label="`${title}: ${series.map((s) => `${s.label} ${fmt(lastValue(s), digits, unit)}`).join(', ')}`"
      @mousemove="onMove"
      @mouseleave="hoverX = null"
    >
      <!-- bandas de fase -->
      <g v-for="b in bands" :key="b.label + b.from">
        <rect
          :x="px(b.from)"
          :y="PAD.t"
          :width="Math.max(0, px(b.to) - px(b.from))"
          :height="H - PAD.t - PAD.b"
          :class="`band band--${b.label}`"
        />
        <text v-if="px(b.to) - px(b.from) > 70" :x="px(b.from) + 4" :y="PAD.t + 10" class="band__label">{{ b.label }}</text>
      </g>
      <!-- rejilla y ejes -->
      <g class="grid">
        <line v-for="v in yTicks" :key="'y' + v" :x1="PAD.l" :x2="W - PAD.r" :y1="py(v)" :y2="py(v)" />
      </g>
      <g class="axes sketch">
        <rect :x="PAD.l" :y="PAD.t" :width="W - PAD.l - PAD.r" :height="H - PAD.t - PAD.b" class="frame" />
      </g>
      <text v-for="v in yTicks" :key="'yt' + v" :x="PAD.l - 6" :y="py(v) + 3" class="tick tick--y">
        {{ fmt(v, digits > 0 && v < 10 ? 1 : 0) }}
      </text>
      <text v-for="v in xTicks" :key="'xt' + v" :x="px(v)" :y="H - 6" class="tick tick--x">{{ fmt(v, 0) }}{{ xUnit ? " " + xUnit : "" }}</text>
      <!-- umbrales -->
      <g v-for="l in lines" :key="'l' + l.label">
        <line :x1="PAD.l" :x2="W - PAD.r" :y1="py(l.y)" :y2="py(l.y)" :stroke="l.color" class="hline" />
        <text :x="W - PAD.r - 4" :y="py(l.y) + 12" class="hline__label" :fill="l.color">{{ l.label }}</text>
      </g>
      <!-- series -->
      <g v-for="s in paths" :key="s.id">
        <path v-for="(d, i) in s.segs" :key="i" :d="d" :stroke="s.color" class="line" :class="{ 'line--dash': s.dash }" />
        <template v-if="dots">
          <circle
            v-for="(p, i) in s.points.filter((q) => q.y !== null)"
            :key="'c' + i"
            :cx="px(p.x)"
            :cy="py(p.y as number)"
            r="3"
            :fill="s.color"
          />
        </template>
      </g>
      <!-- anotaciones -->
      <g v-for="m in markers" :key="'m' + m.x + m.label">
        <line :x1="px(m.x)" :x2="px(m.x)" :y1="PAD.t" :y2="H - PAD.b" class="marker" :stroke="m.color ?? 'var(--crit)'" />
        <text :x="px(m.x) + 4" :y="PAD.t + 22" class="marker__label" :fill="m.color ?? 'var(--crit)'">← {{ m.label }}</text>
      </g>
      <line v-if="hoverX !== null" :x1="px(hoverX)" :x2="px(hoverX)" :y1="PAD.t" :y2="H - PAD.b" class="cursor" />
    </svg>
    <div v-if="hoverValues" class="readout mono" aria-hidden="true">
      {{ xName }} = {{ fmt(hoverX, 0) }}{{ xUnit ? " " + xUnit : "" }}
      <span v-for="v in hoverValues" :key="v.label" :style="{ color: v.color }">· {{ v.label }} {{ fmt(v.y, digits, unit) }}</span>
    </div>
  </figure>
</template>

<style scoped>
.chart {
  margin: 0;
  position: relative;
}
.chart__head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.legend {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--ink-dim);
}
.legend b {
  color: var(--ink);
  font-weight: 600;
}
.legend__item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.swatch {
  width: 14px;
  height: 3px;
  display: inline-block;
}
.swatch--dash {
  background: repeating-linear-gradient(90deg, currentColor 0 4px, transparent 4px 7px) !important;
}
.chart__svg {
  width: 100%;
  display: block;
}
.frame {
  fill: none;
  stroke: var(--line-strong);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.grid line {
  stroke: var(--line);
  stroke-width: 1;
  stroke-dasharray: 2 4;
  vector-effect: non-scaling-stroke;
  opacity: 0.6;
}
.tick {
  font-family: var(--font-mono);
  font-size: 10px;
  fill: var(--ink-faint);
}
.tick--y {
  text-anchor: end;
}
.tick--x {
  text-anchor: middle;
}
.band {
  fill: transparent;
}
.band--reposo {
  fill: rgba(147, 168, 200, 0.06);
}
.band--enfriamiento {
  fill: rgba(110, 231, 183, 0.05);
}
.band__label {
  font-family: var(--font-mono);
  font-size: 9px;
  fill: var(--ink-faint);
  text-transform: uppercase;
}
.hline {
  stroke-width: 1;
  stroke-dasharray: 6 4;
  vector-effect: non-scaling-stroke;
}
.hline__label,
.marker__label {
  font-family: var(--font-mono);
  font-size: 10px;
  text-anchor: end;
}
.marker__label {
  text-anchor: start;
}
.line {
  fill: none;
  stroke-width: 1.8;
  vector-effect: non-scaling-stroke;
  stroke-linejoin: round;
}
.line--dash {
  stroke-dasharray: 5 4;
}
.marker {
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
}
.cursor {
  stroke: var(--ink-dim);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.readout {
  position: absolute;
  top: 0;
  right: 0;
  font-size: 11px;
  background: var(--panel-raised);
  border: 1px solid var(--line);
  padding: 2px 6px;
  pointer-events: none;
}
</style>
