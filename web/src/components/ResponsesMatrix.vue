<script setup lang="ts">
// Respuestas por prompt: una fila por prompt (y repetición) y una columna por run.
// Con una sola columna es la vista de lectura de un run. Para revisar redacción y errores.
import { computed, onMounted, ref } from "vue";
import { library, loadLibrary } from "../api/library";
import type { CompareRow } from "../api/types";
import { NO_DATA, fmt } from "../lib/format";
import { findByText } from "../lib/library";

const props = defineProps<{
  rows: CompareRow[];
  columns: { title: string; sub?: string | null; color?: string | null }[];
  startCollapsed?: boolean;
}>();

onMounted(loadLibrary);

const filter = ref("");
const showReasoning = ref(false);
const compact = ref(true);
const collapsed = ref<Record<number, boolean>>(
  props.startCollapsed ? Object.fromEntries(props.rows.map((_, i) => [i, true])) : {},
);

const words = (t: string | null | undefined) => (t ? t.trim().split(/\s+/).filter(Boolean).length : 0);

const visible = computed(() => {
  const q = filter.value.trim().toLowerCase();
  return props.rows
    .map((r, i) => ({ r, i, ref: findByText(r.prompt, library.value?.prompts ?? []) }))
    .filter(
      ({ r, ref }) =>
        !q ||
        r.prompt.toLowerCase().includes(q) ||
        (ref?.titulo ?? "").toLowerCase().includes(q) ||
        r.cells.some((c) => (c?.response ?? "").toLowerCase().includes(q)),
    );
});
const anyReasoning = computed(() => props.rows.some((r) => r.cells.some((c) => c?.reasoning)));
const repeated = computed(() => props.rows.some((r) => r.rep > 0));

function allCollapsed(v: boolean) {
  collapsed.value = Object.fromEntries(props.rows.map((_, i) => [i, v]));
}
</script>

<template>
  <div class="matrix">
    <div class="tools">
      <input v-model="filter" class="search mono" type="search" placeholder="Buscar en prompts y respuestas…" aria-label="Buscar en prompts y respuestas" />
      <label class="check"><input v-model="compact" type="checkbox" /> recortar respuestas largas</label>
      <label v-if="anyReasoning" class="check"><input v-model="showReasoning" type="checkbox" /> ver razonamiento</label>
      <button type="button" class="btn tiny" @click="allCollapsed(false)">Desplegar todo</button>
      <button type="button" class="btn tiny" @click="allCollapsed(true)">Plegar todo</button>
      <span class="dim small">{{ visible.length }} de {{ rows.length }} prompts</span>
    </div>

    <p v-if="!rows.length" class="dim">Sin respuestas guardadas.</p>

    <section v-for="{ r, i, ref: lib } in visible" :key="i" class="row">
      <button type="button" class="row__head" :aria-expanded="!collapsed[i]" @click="collapsed[i] = !collapsed[i]">
        <span aria-hidden="true">{{ collapsed[i] ? "▸" : "▾" }}</span>
        <b>Prompt {{ i + 1 }}</b>
        <span v-if="repeated" class="dim mono">rep {{ r.rep + 1 }}</span>
        <span v-if="lib" class="tag">{{ lib.titulo }}</span>
        <span class="row__prompt dim">{{ r.prompt }}</span>
      </button>
      <template v-if="!collapsed[i]">
        <pre class="prompt">{{ r.prompt }}</pre>
        <div v-if="lib?.respuesta" class="ref">
          <span class="label">Referencia</span> {{ lib.respuesta }}
          <span class="dim small">· compárala tú: no hay corrección automática</span>
        </div>
        <div class="cells" :style="{ gridTemplateColumns: `repeat(${columns.length}, minmax(300px, 1fr))` }">
          <article v-for="(c, ci) in r.cells" :key="ci" class="cell" :style="columns[ci]?.color ? { borderTopColor: columns[ci].color! } : {}">
            <header v-if="columns.length > 1" class="cell__head">
              <b>{{ columns[ci]?.title }}</b>
              <span v-if="columns[ci]?.sub" class="dim small">{{ columns[ci]?.sub }}</span>
            </header>
            <template v-if="c">
              <div class="facts mono small">
                {{ fmt(c.tokens) }} tokens · {{ words(c.response) }} palabras · {{ fmt(c.tps, 1, "t/s") }} · TTFT {{ fmt(c.ttft, 2, "s") }}
                <span v-if="c.finish === 'length'" class="warn" title="La respuesta llegó al límite de tokens máximos">· ■ cortada por tokens máximos</span>
              </div>
              <p v-if="c.error" class="error small">✕ {{ c.error }}</p>
              <details v-if="showReasoning && c.reasoning" class="reasoning">
                <summary class="small">Razonamiento ({{ words(c.reasoning) }} palabras)</summary>
                <pre>{{ c.reasoning }}</pre>
              </details>
              <pre class="response" :class="{ 'response--compact': compact }">{{ c.response || NO_DATA }}</pre>
            </template>
            <p v-else class="dim small">Este run no tiene este prompt.</p>
          </article>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  margin-bottom: 12px;
}
.search {
  min-width: 260px;
  flex: 1;
  max-width: 420px;
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 5px 8px;
  font-size: 12px;
  color: var(--ink);
}
.check {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  font-size: 12px;
}
.row {
  border: 1px solid var(--line);
  background: var(--panel);
  margin-bottom: 10px;
  min-width: 0;
}
.row__head {
  display: flex;
  gap: 10px;
  align-items: baseline;
  width: 100%;
  background: none;
  border: none;
  border-bottom: 1px dotted var(--line);
  padding: 8px 12px;
  color: var(--ink);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.row__head:focus-visible {
  outline: 2px solid var(--accent);
}
.row__prompt {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
  font-size: 12px;
}
.tag {
  font-family: var(--font-mono);
  font-size: 10px;
  border: 1px solid var(--line);
  padding: 0 5px;
  color: var(--ink-dim);
  white-space: nowrap;
}
.prompt {
  margin: 0;
  padding: 8px 12px;
  white-space: pre-wrap;
  font-size: 12px;
  color: var(--ink-dim);
}
.ref {
  margin: 0 12px 8px;
  padding: 6px 10px;
  border-left: 2px solid var(--accent);
  font-size: 13px;
}
.cells {
  display: grid;
  gap: 10px;
  padding: 0 12px 12px;
  overflow-x: auto;
}
.cell {
  border: 1px solid var(--line);
  border-top: 2px solid var(--line-strong);
  background: var(--bg);
  padding: 8px 10px;
  min-width: 0;
}
.cell__head {
  display: flex;
  flex-direction: column;
  margin-bottom: 4px;
  font-size: 12px;
}
.facts {
  color: var(--ink-faint);
  margin-bottom: 6px;
}
.response {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.55;
  color: var(--ink);
}
.response--compact {
  max-height: 360px;
  overflow-y: auto;
}
.reasoning pre {
  white-space: pre-wrap;
  font-size: 12px;
  color: var(--ink-faint);
  max-height: 240px;
  overflow: auto;
}
.dim {
  color: var(--ink-faint);
}
.small {
  font-size: 11px;
}
.warn {
  color: var(--warn);
}
.error {
  color: var(--crit);
}
.btn.tiny {
  padding: 1px 8px;
  font-size: 11px;
}
</style>
