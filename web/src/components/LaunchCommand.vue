<script setup lang="ts">
// Comando de llama-server propuesto para un GGUF: opción (GPU / reparto), shell y copiar.
import { computed, ref, watch } from "vue";
import type { LaunchCommand } from "../api/types";
import Stamp from "./Stamp.vue";

const props = defineProps<{ command: LaunchCommand }>();

const SHELL_KEY = "arena.launch.shell";
const SHELL_NAME: Record<string, string> = { cmd: "cmd", powershell: "PowerShell", bash: "bash" };
const EXE_SOURCE: Record<string, string> = {
  configurado: "binario de la configuración del agente",
  detectado: "binario de un llama-server detectado",
  supuesto: "binario sin detectar: se supone en el PATH",
};

const optionId = ref<string | null>(null);
const shell = ref<string>(readShell());
const copied = ref(false);
const pre = ref<HTMLElement | null>(null);

function readShell(): string {
  try {
    return localStorage.getItem(SHELL_KEY) ?? "";
  } catch {
    return "";
  }
}

const cmd = computed(() => (props.command.available ? props.command : null));
const option = computed(() => cmd.value?.options.find((o) => o.id === optionId.value) ?? cmd.value?.options[0] ?? null);
const shells = computed(() => Object.keys(option.value?.shells ?? {}));
const activeShell = computed(() => (shells.value.includes(shell.value) ? shell.value : shells.value[0]));
const text = computed(() => (option.value && activeShell.value ? option.value.shells[activeShell.value] : ""));

watch(shell, (v) => {
  try {
    localStorage.setItem(SHELL_KEY, v);
  } catch {
    /* sin almacenamiento */
  }
});
watch(text, () => (copied.value = false));

async function copy() {
  try {
    await navigator.clipboard.writeText(text.value);
    copied.value = true;
    window.setTimeout(() => (copied.value = false), 2000);
  } catch {
    // Sin portapapeles (contexto no seguro): se selecciona el texto para copiarlo a mano.
    const sel = window.getSelection();
    if (pre.value && sel) {
      const range = document.createRange();
      range.selectNodeContents(pre.value);
      sel.removeAllRanges();
      sel.addRange(range);
    }
  }
}
</script>

<template>
  <div class="launch">
    <p v-if="!cmd" class="dim small">{{ (command as { reason: string }).reason }}</p>
    <template v-else>
      <div class="head">
        <h4 class="label">Comando de llama-server</h4>
        <Stamp text="estimado" tone="warn" :tilt="0" />
        <span class="dim small">{{ EXE_SOURCE[cmd.exe_source] }} · Arena no lo lanza: cópialo y ejecútalo tú.</span>
      </div>

      <div v-if="cmd.options.length > 1" class="seg" role="radiogroup" aria-label="Dónde cargarlo">
        <button
          v-for="o in cmd.options"
          :key="o.id"
          type="button"
          role="radio"
          class="seg__btn"
          :aria-checked="o.id === option?.id"
          @click="optionId = o.id"
        >
          {{ o.label }}
        </button>
      </div>
      <p v-else class="small opt">{{ option?.label }}</p>

      <div class="box">
        <div class="tabs" role="tablist" aria-label="Terminal">
          <button
            v-for="s in shells"
            :key="s"
            role="tab"
            type="button"
            class="tab"
            :aria-selected="s === activeShell"
            @click="shell = s"
          >
            {{ SHELL_NAME[s] ?? s }}
          </button>
          <button type="button" class="btn tiny copy" @click="copy">{{ copied ? "✓ Copiado" : "Copiar" }}</button>
        </div>
        <pre ref="pre" class="mono">{{ text }}</pre>
      </div>
      <ul v-if="cmd.notes.length" class="notes">
        <li v-for="n in cmd.notes" :key="n">{{ n }}</li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.launch {
  grid-column: 1 / -1;
  border-top: 1px dotted var(--line);
  padding-top: 8px;
  min-width: 0;
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.head .label {
  margin: 0;
}
.seg {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.seg__btn {
  background: none;
  border: 1px solid var(--line);
  color: var(--ink-dim);
  font-family: var(--font-sans);
  font-size: 12px;
  padding: 3px 9px;
  cursor: pointer;
}
.seg__btn[aria-checked="true"] {
  border-color: var(--accent);
  color: var(--ink);
  background: rgba(108, 180, 255, 0.08);
}
.seg__btn:focus-visible,
.tab:focus-visible {
  outline: 2px solid var(--accent);
}
.opt {
  margin: 0 0 8px;
  color: var(--ink-dim);
}
.box {
  border: 1px solid var(--line);
  background: var(--bg);
}
.tabs {
  display: flex;
  align-items: center;
  gap: 2px;
  border-bottom: 1px solid var(--line);
  padding: 0 4px;
}
.tab {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--ink-dim);
  font: inherit;
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
}
.tab[aria-selected="true"] {
  color: var(--ink);
  border-bottom-color: var(--accent);
  font-weight: 600;
}
.copy {
  margin-left: auto;
}
pre {
  margin: 0;
  padding: 8px 10px;
  font-size: 12px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--ink);
}
.notes {
  margin: 8px 0 0;
  padding-left: 16px;
  font-size: 12px;
  color: var(--ink-dim);
}
.dim {
  color: var(--ink-faint);
}
.small {
  font-size: 11px;
}
.btn.tiny {
  padding: 1px 8px;
  font-size: 11px;
}
</style>
