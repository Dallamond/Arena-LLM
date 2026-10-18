<script setup lang="ts">
// Formulario de una suite de calidad a partir de `suite.fields` (el servidor define las opciones).
import type { Suite } from "../api/types";
import type { FormState } from "../lib/suiteForm";

const props = defineProps<{ suite: Suite; modelValue: FormState; idPrefix: string }>();

function set(key: string, value: string | number | string[]) {
  props.modelValue[key] = value;
}
function toggle(key: string, value: string) {
  const cur = (props.modelValue[key] as string[]) ?? [];
  set(key, cur.includes(value) ? cur.filter((x) => x !== value) : [...cur, value]);
}
</script>

<template>
  <div class="sf">
    <template v-for="f in suite.fields ?? []" :key="f.key">
      <div v-if="f.type === 'choices'" class="sf__wide">
        <span class="label">{{ f.label }}</span>
        <div class="sf__choices" role="group" :aria-label="f.label">
          <label v-for="c in f.choices" :key="c.value" class="sf__check">
            <input
              type="checkbox"
              :checked="((modelValue[f.key] as string[]) ?? []).includes(c.value)"
              @change="toggle(f.key, c.value)"
            />
            <span>{{ c.label }}</span>
          </label>
        </div>
        <span v-if="f.help" class="dim sf__help">
          {{ f.help }} Marcadas: {{ ((modelValue[f.key] as string[]) ?? []).length || "todas" }}.
        </span>
      </div>

      <label v-else-if="f.type === 'pairs' || f.type === 'text'" class="sf__wide">
        <span class="label">{{ f.label }}</span>
        <textarea
          :id="`${idPrefix}-${f.key}`"
          :value="String(modelValue[f.key] ?? '')"
          rows="3"
          :placeholder="f.type === 'pairs' ? '¿Cuánto es 2+2? | 4' : ''"
          @input="set(f.key, ($event.target as HTMLTextAreaElement).value)"
        />
        <span v-if="f.help" class="dim sf__help">{{ f.help }}</span>
      </label>

      <label v-else>
        <span class="label">{{ f.label }}</span>
        <input
          :id="`${idPrefix}-${f.key}`"
          :type="f.type === 'number' ? 'number' : 'text'"
          :value="modelValue[f.key] as string | number"
          :placeholder="f.type === 'numlist' ? '2048, 4096, 8192' : ''"
          @input="set(f.key, f.type === 'number' ? ($event.target as HTMLInputElement).valueAsNumber : ($event.target as HTMLInputElement).value)"
        />
        <span v-if="f.help" class="dim sf__help">{{ f.help }}</span>
      </label>
    </template>
  </div>
</template>

<style scoped>
.sf {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px 14px;
  margin-bottom: 14px;
}
.sf label,
.sf__wide {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sf__wide {
  grid-column: 1 / -1;
}
.sf__choices {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 4px 14px;
  max-height: 160px;
  overflow: auto;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: var(--bg);
}
.sf__check {
  flex-direction: row !important;
  align-items: flex-start;
  gap: 8px !important;
  font-size: 13px;
  cursor: pointer;
}
.sf__help {
  font-size: 12px;
}
.dim {
  color: var(--ink-faint);
}
textarea {
  resize: vertical;
}
</style>
