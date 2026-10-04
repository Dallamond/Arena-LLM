<script setup lang="ts">
// Prompts de una prueba: biblioteca (un clic añade o quita) + texto libre separado por "---".
import { computed, onMounted, ref } from "vue";
import { library, libraryError, loadLibrary } from "../api/library";
import { joinPrompts, splitPrompts, suggestedMaxTokens, togglePrompt } from "../lib/library";

const props = defineProps<{ modelValue: string; defaults: string[]; rows?: number }>();
const emit = defineEmits<{ "update:modelValue": [v: string]; maxTokens: [n: number] }>();

onMounted(loadLibrary);

const cat = ref<string>("todas");
const list = computed(() => splitPrompts(props.modelValue));
const visible = computed(() => (library.value?.prompts ?? []).filter((p) => cat.value === "todas" || p.categoria === cat.value));
const selected = computed(() => (library.value?.prompts ?? []).filter((p) => list.value.includes(p.prompt)));
const catCount = (id: string) => (library.value?.prompts ?? []).filter((p) => p.categoria === id).length;

function set(next: string[]) {
  emit("update:modelValue", joinPrompts(next.length ? next : props.defaults));
  const sug = suggestedMaxTokens(next, library.value?.prompts ?? []);
  if (sug !== null) emit("maxTokens", sug);
}
const toggle = (prompt: string) => set(togglePrompt(list.value, prompt, props.defaults));
function addVisible() {
  let next = list.value;
  for (const p of visible.value) if (!next.includes(p.prompt)) next = togglePrompt(next, p.prompt, props.defaults);
  set(next);
}
const clear = () => set(list.value.filter((p) => !selected.value.some((e) => e.prompt === p)));
</script>

<template>
  <div class="picker">
    <fieldset class="lib">
      <legend class="label">Biblioteca <span v-if="library" class="dim mono">v{{ library.version }}</span></legend>
      <p v-if="libraryError" class="error mono small">✕ {{ libraryError }}</p>
      <p v-for="w in library?.avisos ?? []" :key="w" class="warn small">▲ {{ w }}</p>
      <template v-if="library">
        <div class="lib__cats" role="group" aria-label="Categorías">
          <button type="button" class="chip" :aria-pressed="cat === 'todas'" @click="cat = 'todas'">
            Todas <span class="mono">{{ library.prompts.length }}</span>
          </button>
          <button v-for="c in library.categorias" :key="c.id" type="button" class="chip" :aria-pressed="cat === c.id" @click="cat = c.id">
            {{ c.nombre }} <span class="mono">{{ catCount(c.id) }}</span>
          </button>
        </div>
        <div class="lib__items">
          <button
            v-for="p in visible"
            :key="p.id"
            type="button"
            class="item"
            :aria-pressed="list.includes(p.prompt)"
            :title="p.prompt + (p.respuesta ? `\n\nReferencia: ${p.respuesta}` : '')"
            @click="toggle(p.prompt)"
          >
            <span aria-hidden="true">{{ list.includes(p.prompt) ? "■" : "□" }}</span> {{ p.titulo }}
            <span v-if="p.respuesta" class="item__tag mono">ref</span>
            <span v-if="p.origen === 'propia'" class="item__tag mono">propio</span>
          </button>
        </div>
        <p class="dim small lib__foot">
          {{ selected.length }} de la biblioteca en la lista ·
          <button type="button" class="link" @click="addVisible">añadir {{ cat === "todas" ? "todos" : "esta categoría" }}</button>
          <template v-if="selected.length"> · <button type="button" class="link" @click="clear">quitar los de la biblioteca</button></template>
          <br />Los marcados <span class="mono">ref</span> traen respuesta de referencia: se ve junto a la respuesta en el run. «Tokens máximos» pasa al mayor sugerido.
        </p>
      </template>
    </fieldset>
    <label class="prompts">
      <span class="label">prompts <span class="dim mono">({{ list.length }})</span></span>
      <textarea :value="modelValue" :rows="rows ?? 6" @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)" />
    </label>
  </div>
</template>

<style scoped>
.lib {
  border: 1px dashed var(--line);
  padding: 8px 10px 4px;
  margin: 0 0 12px;
  min-width: 0;
}
.lib legend {
  padding: 0 4px;
}
.lib__cats,
.lib__items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.lib__items {
  max-height: 168px;
  overflow-y: auto;
}
.chip,
.item {
  background: none;
  border: 1px solid var(--line);
  color: var(--ink-dim);
  font-family: var(--font-sans);
  font-size: 12px;
  padding: 3px 9px;
  cursor: pointer;
  display: inline-flex;
  gap: 6px;
  align-items: baseline;
}
.chip[aria-pressed="true"],
.item[aria-pressed="true"] {
  border-color: var(--accent);
  color: var(--ink);
  background: rgba(108, 180, 255, 0.08);
}
.chip:hover,
.item:hover {
  border-color: var(--line-strong);
}
.chip:focus-visible,
.item:focus-visible,
.link:focus-visible {
  outline: 2px solid var(--accent);
}
.chip .mono {
  font-size: 10px;
  color: var(--ink-faint);
}
.item__tag {
  font-size: 9px;
  color: var(--ink-faint);
  border: 1px solid var(--line);
  padding: 0 3px;
}
.lib__foot {
  margin: 0 0 4px;
}
.link {
  background: none;
  border: none;
  padding: 0;
  color: var(--accent);
  font: inherit;
  cursor: pointer;
  text-decoration: underline dotted;
}
.prompts {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
textarea {
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 5px 8px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink);
  resize: vertical;
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
</style>
