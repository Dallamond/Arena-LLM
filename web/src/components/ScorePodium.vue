<script setup lang="ts">
// Podio de la batalla: nota 0–100 por lado con el desglose por dimensión.
// La velocidad y la eficiencia son relativas al mejor lado; la calidad es absoluta (aciertos reales).
import { computed } from "vue";
import type { Scoring, ScoreDim } from "../api/types";
import { fmt, NO_DATA } from "../lib/format";

const props = defineProps<{
  scoring: Scoring;
  /** Nombre y color de cada columna, en el mismo orden que `scoring.scores`. */
  entries: { title: string; sub?: string | null; color?: string }[];
}>();

const LABEL: Record<ScoreDim, string> = {
  quality: "Calidad",
  speed: "Velocidad",
  efficiency: "Eficiencia",
  stability: "Estabilidad",
};
const HINT: Record<ScoreDim, string> = {
  quality: "Aciertos reales (absoluto)",
  speed: "t/s y TTFT frente al mejor lado",
  efficiency: "Tokens por Wh frente al mejor lado",
  stability: "100 menos throttling y degradación",
};

const rows = computed(() =>
  props.scoring.scores
    .map((s, i) => ({ ...s, i, ...props.entries[i] }))
    .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99) || a.i - b.i),
);
const anyScore = computed(() => rows.value.some((r) => r.score !== null));
const medal = (rank: number | null) => (rank === 1 ? "1.º" : rank ? `${rank}.º` : "—");
const tiedTop = computed(() => (props.scoring.tied?.length ?? 0) > 1);
</script>

<template>
  <div v-if="anyScore" class="podium">
    <ol class="podium__list">
      <li v-for="r in rows" :key="r.i" class="pod" :class="{ 'pod--top': r.rank === 1 }" :style="{ borderColor: r.color }">
        <div class="pod__head">
          <span class="pod__rank mono" :aria-label="`Puesto ${medal(r.rank)}`">{{ medal(r.rank) }}</span>
          <div class="pod__id">
            <b :style="{ color: r.color }">■ {{ r.title }}</b>
            <span v-if="r.sub" class="dim small mono">{{ r.sub }}</span>
          </div>
          <div class="pod__score">
            <span class="pod__num mono">{{ r.score === null ? NO_DATA : fmt(r.score, 0) }}</span>
            <span class="dim small">/ 100</span>
          </div>
        </div>
        <p v-if="r.partial" class="warn small">
          Run incompleto: nota provisional{{ r.rank === null ? ", no compite por el puesto" : "" }}.
        </p>
        <ul class="dims">
          <li v-for="d in scoring.dimensions" :key="d" :title="HINT[d]">
            <span class="dims__name">{{ LABEL[d] }}</span>
            <span class="dims__bar" aria-hidden="true">
              <span class="dims__fill" :style="{ width: (r.dims[d] ?? 0) + '%', background: r.color }" />
            </span>
            <span class="dims__val mono">{{ r.dims[d] === null ? NO_DATA : fmt(r.dims[d], 0) }}</span>
            <span class="dims__w dim small mono">{{ r.weights[d] ? `${fmt(r.weights[d], 0)} %` : "" }}</span>
          </li>
        </ul>
        <p v-if="r.quality_total" class="small mono">
          <span class="dim">aciertos</span> {{ r.quality_correct }} / {{ r.quality_total }}
        </p>
      </li>
    </ol>
    <p class="dim small note">
      <template v-if="tiedTop">Empate en cabeza (menos de 1 punto de diferencia). </template>
      La calidad es absoluta y comparable entre batallas. La velocidad y la eficiencia son relativas al mejor lado de
      <i>esta</i> batalla, así que la nota global solo vale aquí.
      <template v-if="!scoring.has_quality">
        Sin calidad: esta prueba no se corrige sola, y la nota solo mide rendimiento.
      </template>
    </p>
  </div>
</template>

<style scoped>
.podium__list {
  list-style: none;
  margin: 0 0 8px;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}
.pod {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  background: var(--panel-raised);
}
.pod--top {
  border-width: 2px;
}
.pod__head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.pod__rank {
  font-size: 15px;
  min-width: 2.2em;
  color: var(--ink-dim);
}
.pod__id {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}
.pod__id .small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pod__score {
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.pod__num {
  font-size: 34px;
  line-height: 1;
  color: var(--data-ink);
}
.dims {
  list-style: none;
  margin: 0 0 6px;
  padding: 0;
  display: grid;
  gap: 5px;
}
.dims li {
  display: grid;
  grid-template-columns: 84px 1fr 30px 38px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.dims__bar {
  height: 6px;
  border-radius: 3px;
  background: var(--line);
  overflow: hidden;
}
.dims__fill {
  display: block;
  height: 100%;
}
.dims__val,
.dims__w {
  text-align: right;
}
.warn {
  color: var(--warn);
  margin: 0 0 6px;
}
.note {
  margin: 4px 0 0;
}
.dim {
  color: var(--ink-faint);
}
.small {
  font-size: 12px;
}
</style>
