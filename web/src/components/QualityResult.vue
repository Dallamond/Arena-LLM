<script setup lang="ts">
// Resultado de una prueba de calidad: aciertos (QA), pass@1 (código), cuadrícula tamaño × profundidad con
// velocidad y VRAM (contexto) o escalado por niveles (concurrencia). Todo sale de `summary.quality`.
import { computed } from "vue";
import type { QualitySummary, RunItem } from "../api/types";
import { NO_DATA, fmt, isNum } from "../lib/format";
import LineChart, { type ChartSeries } from "./LineChart.vue";

const props = defineProps<{ quality: QualitySummary; items: RunItem[] }>();

const q = computed(() => props.quality);
const pct = (v: number | null | undefined) => (isNum(v) ? `${fmt(v, 0)} %` : NO_DATA);
const gib = (mib: number | null | undefined) => (isNum(mib) ? fmt(mib / 1024, 2, "GiB") : NO_DATA);

const chips = computed(() =>
  props.items
    .filter((i) => i.eval && (i.eval.kind === "qa" || i.eval.kind === "code"))
    .map((i) => ({ name: i.name ?? `#${i.idx}`, ok: !!i.eval?.correct, note: i.eval?.note ?? i.eval?.status ?? "" })),
);

// --- contexto
const needle = computed(() => (q.value.suite === "contexto" ? q.value : null));
const depths = computed(() => [...new Set(needle.value?.rows.map((r) => r.depth) ?? [])].sort((a, b) => a - b));
const sizes = computed(() => needle.value?.by_size.map((s) => s.size) ?? []);
function cell(size: number, depth: number) {
  return needle.value?.rows.find((r) => r.size === size && r.depth === depth) ?? null;
}
const vramSeries = computed<ChartSeries[]>(() => {
  const pts = (needle.value?.by_size ?? []).filter((s) => isNum(s.vram_mib) && isNum(s.prompt_tokens));
  return pts.length ? [{ id: "vram", label: "VRAM", color: "var(--accent)", points: pts.map((s) => ({ x: s.prompt_tokens as number, y: (s.vram_mib as number) / 1024 })) }] : [];
});
const ppSeries = computed<ChartSeries[]>(() => {
  const pts = (needle.value?.by_size ?? []).filter((s) => isNum(s.pp_server) && isNum(s.prompt_tokens));
  return pts.length ? [{ id: "pp", label: "procesado", color: "var(--accent)", points: pts.map((s) => ({ x: s.prompt_tokens as number, y: s.pp_server as number })) }] : [];
});

// --- concurrencia
const conc = computed(() => (q.value.suite === "concurrencia" ? q.value : null));
const concSeries = computed<ChartSeries[]>(() => {
  const lv = conc.value?.levels ?? [];
  return [
    { id: "agg", label: "agregado", color: "var(--accent)", points: lv.map((l) => ({ x: l.level, y: l.tps_aggregate })) },
    { id: "per", label: "por petición", color: "var(--ink-dim)", dash: true, points: lv.map((l) => ({ x: l.level, y: l.tps_per_request })) },
  ];
});
</script>

<template>
  <div class="qr">
    <!-- QA y código -->
    <template v-if="q.suite === 'qa' || q.suite === 'codigo'">
      <div class="stats">
        <div class="stat">
          <span class="label">{{ q.suite === "qa" ? "Aciertos" : "pass@1" }}</span>
          <b class="num big">{{ q.correct }}<span class="unit">/ {{ q.total }}</span></b>
          <span class="dim">{{ pct(q.accuracy_pct) }}</span>
        </div>
        <div v-if="q.suite === 'qa'" class="stat">
          <span class="label">Formato correcto</span>
          <b class="num big">{{ pct(q.format_ok_pct) }}</b>
          <span class="dim">línea «RESPUESTA: …»</span>
        </div>
        <template v-if="q.suite === 'codigo'">
          <div v-for="(v, lv) in q.by_level" :key="lv" class="stat">
            <span class="label">Nivel {{ lv }}</span>
            <b class="num big">{{ v.correct }}<span class="unit">/ {{ v.total }}</span></b>
          </div>
          <div class="stat">
            <span class="label">Sin código · timeout</span>
            <b class="num big">{{ q.no_code }} · {{ q.timeouts }}</b>
          </div>
        </template>
        <div class="stat">
          <span class="label">Cortadas por tokens</span>
          <b class="num big">{{ q.truncated }}</b>
          <span class="dim">{{ q.truncated ? "súbelos en las opciones" : "ninguna" }}</span>
        </div>
        <div v-if="q.failed" class="stat">
          <span class="label">Errores del servidor</span>
          <b class="num big warn">{{ q.failed }}</b>
        </div>
      </div>
      <ul v-if="chips.length" class="chips" aria-label="Resultado por ítem">
        <li v-for="(c, i) in chips" :key="i" class="chip" :class="c.ok ? 'chip--ok' : 'chip--bad'" :title="c.note">
          <span aria-hidden="true">{{ c.ok ? "✓" : "✗" }}</span> {{ c.name }}
          <span class="sr-only">{{ c.ok ? "correcta" : "incorrecta" }}</span>
        </li>
      </ul>
    </template>

    <!-- Contexto -->
    <template v-else-if="needle">
      <div class="stats">
        <div class="stat">
          <span class="label">Aciertos</span>
          <b class="num big">{{ needle.correct }}<span class="unit">/ {{ needle.total }}</span></b>
          <span class="dim">{{ pct(needle.accuracy_pct) }}</span>
        </div>
        <div class="stat">
          <span class="label">Contexto más largo sin fallos</span>
          <b class="num big">{{ isNum(needle.max_size_ok) ? fmt(needle.max_size_ok) : NO_DATA }}</b>
          <span class="dim">tokens</span>
        </div>
        <div class="stat">
          <span class="label">Primer tamaño que falla por error</span>
          <b class="num big" :class="{ warn: isNum(needle.first_failed_size) }">{{ isNum(needle.first_failed_size) ? fmt(needle.first_failed_size) : "ninguno" }}</b>
          <span class="dim">{{ isNum(needle.first_failed_size) ? "no cabe o se agota el tiempo" : "" }}</span>
        </div>
      </div>

      <div class="scroll">
        <table class="grid mono">
          <caption class="label">Acierto por tamaño (tokens) y profundidad del código en el texto</caption>
          <thead>
            <tr><th>profundidad ↓ / tamaño →</th><th v-for="s in sizes" :key="s">{{ fmt(s) }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="d in depths" :key="d">
              <th>{{ d }} %</th>
              <td v-for="s in sizes" :key="s">
                <span v-if="cell(s, d)" class="gcell" :class="cell(s, d)!.failed ? 'gcell--err' : cell(s, d)!.correct ? 'gcell--ok' : 'gcell--bad'" :title="cell(s, d)!.note ?? ''">
                  {{ cell(s, d)!.failed ? "▲ error" : cell(s, d)!.correct ? "✓" : "✗" }}
                </span>
                <span v-else class="dim">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="scroll">
        <table class="grid mono">
          <caption class="label">Velocidad y memoria frente al contexto</caption>
          <thead>
            <tr>
              <th>tamaño</th><th>tokens reales</th><th>procesado (t/s)</th><th>TTFT</th><th>VRAM pico</th><th>sobre el reposo</th><th>aciertos</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in needle.by_size" :key="s.size">
              <td>{{ fmt(s.size) }}</td>
              <td>{{ fmt(s.prompt_tokens, 0) }}</td>
              <td>{{ fmt(s.pp_server, 0) }}</td>
              <td>{{ fmt(s.ttft_s, 2, "s") }}</td>
              <td>{{ gib(s.vram_mib) }}</td>
              <td>{{ isNum(s.vram_delta_mib) ? "+" + gib(s.vram_delta_mib) : NO_DATA }}</td>
              <td>{{ s.correct }}/{{ s.total }}<span v-if="s.failed" class="warn"> · {{ s.failed }} con error</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="charts">
        <LineChart v-if="vramSeries.length" title="VRAM frente al contexto" unit="GiB" :digits="1" :series="vramSeries" x-unit="tok" x-name="tokens" :x-min="0" dots />
        <LineChart v-if="ppSeries.length" title="Procesado de prompt frente al contexto" unit="t/s" :series="ppSeries" x-unit="tok" x-name="tokens" :x-min="0" :y-min="0" dots />
      </div>
      <p class="dim small">
        La VRAM es la mayor de las GPU del equipo durante cada petición (ESTIMADO por muestreo cada segundo: una petición muy corta puede quedarse sin lectura propia).
      </p>
    </template>

    <!-- Concurrencia -->
    <template v-else-if="conc">
      <div class="stats">
        <div class="stat">
          <span class="label">Mejor agregado</span>
          <b class="num big">{{ fmt(conc.best_tps_aggregate, 1) }}<span class="unit">t/s</span></b>
          <span class="dim">con {{ conc.best_level ?? NO_DATA }} a la vez</span>
        </div>
      </div>
      <div class="scroll">
        <table class="grid mono">
          <thead>
            <tr>
              <th>a la vez</th><th>peticiones</th><th>agregado (t/s)</th><th>por petición (t/s)</th><th>TTFT</th><th>escala</th><th>eficiencia</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="l in conc.levels" :key="l.level">
              <td>{{ l.level }}</td>
              <td>{{ l.requests }}<span v-if="l.errors" class="warn"> · {{ l.errors }} con error</span></td>
              <td>{{ fmt(l.tps_aggregate, 1) }}</td>
              <td>{{ fmt(l.tps_per_request, 1) }}</td>
              <td>{{ fmt(l.ttft_s, 2, "s") }}</td>
              <td>{{ isNum(l.scaling) ? "×" + fmt(l.scaling, 2) : NO_DATA }}</td>
              <td>{{ pct(l.efficiency_pct) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <LineChart title="t/s frente a peticiones a la vez" unit="t/s" :digits="1" :series="concSeries" x-unit="" x-name="a la vez" :x-min="0" :y-min="0" dots />
      <p class="dim small">«Escala» compara el agregado con el de una sola petición; 100 % de eficiencia sería escalar linealmente con los slots.</p>
    </template>
  </div>
</template>

<style scoped>
.qr {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--bg);
}
.big {
  font-size: 30px;
}
.unit {
  font-size: 15px;
  color: var(--ink-dim);
  margin-left: 4px;
}
.dim {
  color: var(--ink-faint);
  font-size: 12px;
}
.small {
  font-size: 12px;
}
.warn {
  color: var(--warn);
}
.chips {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 999px;
  cursor: help;
}
.chip--ok {
  color: var(--ok);
  background: color-mix(in srgb, var(--ok) 14%, transparent);
}
.chip--bad {
  color: var(--crit);
  background: color-mix(in srgb, var(--crit) 14%, transparent);
}
.scroll {
  overflow-x: auto;
}
.grid {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.grid caption {
  text-align: left;
  padding-bottom: 6px;
}
.grid th,
.grid td {
  padding: 6px 10px;
  text-align: right;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.grid th:first-child,
.grid td:first-child {
  text-align: left;
}
.grid thead th {
  font-weight: 500;
  color: var(--ink-dim);
}
.gcell {
  display: inline-block;
  min-width: 44px;
  text-align: center;
  padding: 1px 8px;
  border-radius: 6px;
  font-weight: 600;
}
.gcell--ok {
  color: var(--ok);
  background: color-mix(in srgb, var(--ok) 14%, transparent);
}
.gcell--bad {
  color: var(--crit);
  background: color-mix(in srgb, var(--crit) 14%, transparent);
}
.gcell--err {
  color: var(--warn);
  background: color-mix(in srgb, var(--warn) 14%, transparent);
}
.charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
}
</style>
