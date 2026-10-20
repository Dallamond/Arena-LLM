<script setup lang="ts">
// Nombre, etiquetas y notas de un run. Solo metadatos: no tocan resultados ni configuración.
import { ref, watch } from "vue";
import { api, live } from "../api/live";
import type { Run } from "../api/types";
import { MAX_TAGS, MAX_TAG_LEN, addTag, removeTag } from "../lib/tags";

const props = defineProps<{ run: Pick<Run, "id" | "label" | "notes" | "tags"> }>();
const emit = defineEmits<{ saved: [run: Run] }>();

const label = ref(props.run.label ?? "");
const notes = ref(props.run.notes ?? "");
const draft = ref("");
const error = ref<string | null>(null);
const saving = ref(false);

watch(
  () => props.run,
  (r) => {
    label.value = r.label ?? "";
    notes.value = r.notes ?? "";
  },
);

async function save(body: { label?: string; notes?: string; tags?: string[] }) {
  saving.value = true;
  error.value = null;
  try {
    const run = await api<Run>(`/api/runs/${props.run.id}`, { method: "PATCH", body: JSON.stringify(body) });
    live.runs[run.id] = { ...(live.runs[run.id] ?? {}), ...run };
    emit("saved", run);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

const tags = () => props.run.tags ?? [];
function add() {
  const next = addTag(tags(), draft.value);
  draft.value = "";
  if (next) void save({ tags: next });
}
const remove = (t: string) => save({ tags: removeTag(tags(), t) });
const saveNotes = () => notes.value.trim() !== (props.run.notes ?? "") && save({ notes: notes.value });
const saveLabel = () => label.value.trim() !== (props.run.label ?? "") && save({ label: label.value });
</script>

<template>
  <div class="meta">
    <div class="row">
      <label class="lbl" :for="`rm-label-${run.id}`">Nombre</label>
      <input :id="`rm-label-${run.id}`" v-model="label" class="field mono" maxlength="120" placeholder="Sin nombre" @change="saveLabel" />
    </div>
    <div class="row">
      <span class="lbl" id="rm-tags-lbl">Etiquetas</span>
      <div class="tags" role="group" aria-labelledby="rm-tags-lbl">
        <span v-for="t in run.tags ?? []" :key="t" class="tag mono">
          {{ t }}
          <button type="button" class="x" :aria-label="`Quitar la etiqueta ${t}`" @click="remove(t)">×</button>
        </span>
        <input
          v-if="(run.tags ?? []).length < MAX_TAGS"
          v-model="draft"
          class="field mono tag-in"
          :maxlength="MAX_TAG_LEN"
          placeholder="+ etiqueta"
          aria-label="Añadir etiqueta"
          @keydown.enter.prevent="add"
          @blur="add"
        />
      </div>
    </div>
    <div class="row">
      <label class="lbl" :for="`rm-notes-${run.id}`">Notas</label>
      <textarea :id="`rm-notes-${run.id}`" v-model="notes" class="field notes" rows="2" maxlength="4000" placeholder="Qué probaste, qué viste…" @blur="saveNotes"></textarea>
    </div>
    <p v-if="error" class="err mono" role="alert">▲ {{ error }}</p>
  </div>
</template>

<style scoped>
.meta {
  display: grid;
  gap: 8px;
}
.row {
  display: grid;
  grid-template-columns: 84px 1fr;
  gap: 10px;
  align-items: start;
}
.lbl {
  color: var(--ink-faint);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding-top: 6px;
}
.field {
  background: var(--bg);
  border: 1px solid var(--line);
  color: inherit;
  padding: 5px 8px;
  font-size: 12px;
  border-radius: 8px;
  width: 100%;
}
.notes {
  resize: vertical;
  font-family: inherit;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 4px 2px 10px;
  font-size: 12px;
}
.x {
  background: none;
  border: 0;
  color: var(--ink-faint);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0 6px;
}
.x:hover,
.x:focus-visible {
  color: var(--ink);
}
.tag-in {
  width: 130px;
  border-radius: 999px;
}
.err {
  color: var(--bad, #ff6b6b);
  font-size: 12px;
  margin: 0;
}
</style>
