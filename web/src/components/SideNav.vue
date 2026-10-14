<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { currentHost, currentSnapshot, gpus, gpuSample } from "../api/live";
import { deviceColor, shortName } from "../lib/devices";
import { gibPair } from "../lib/format";
import { NAV } from "../router";
import BarWithOverflow from "./BarWithOverflow.vue";
import Icon from "./Icon.vue";

const KEY = "arena.navCollapsed";
function read(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}
const collapsed = ref(read());
watch(collapsed, (v) => {
  try {
    localStorage.setItem(KEY, v ? "1" : "0");
  } catch {
    /* sin almacenamiento */
  }
});

const gpuList = computed(() => gpus(currentHost.value));
const snap = currentSnapshot;
</script>

<template>
  <nav class="nav" :class="{ 'nav--collapsed': collapsed }" aria-label="Secciones">
    <ul class="nav__list">
      <li v-for="item in NAV" :key="item.path">
        <RouterLink :to="item.path" class="nav__link" :title="collapsed ? item.label : undefined">
          <Icon :name="item.icon" />
          <span class="nav__text">{{ item.label }}</span>
          <span v-if="item.phase && !collapsed" class="nav__phase mono">{{ item.phase }}</span>
        </RouterLink>
      </li>
    </ul>

    <div class="nav__foot">
      <template v-if="!collapsed">
        <div v-for="d in gpuList" :key="d.device_id" class="mini">
          <div class="mini__head">
            <span :style="{ color: deviceColor(d) }">{{ shortName(d.name) }}</span>
          </div>
          <BarWithOverflow
            :used="gpuSample(snap, d.device_id)?.mem_used_mib"
            :total="gpuSample(snap, d.device_id)?.mem_total_mib ?? d.memory_total_mib"
            :color="deviceColor(d)"
            :label="`VRAM ${shortName(d.name)}`"
            :dimension="false"
            thin
          />
          <div class="mini__val">
            VRAM {{ gibPair(gpuSample(snap, d.device_id)?.mem_used_mib, d.memory_total_mib) }}
          </div>
        </div>
        <div class="mini">
          <div class="mini__head mono"><span style="color: var(--dev-ram)">RAM</span></div>
          <BarWithOverflow
            :used="snap?.ram?.used_mib"
            :total="snap?.ram?.total_mib"
            color="var(--dev-ram)"
            label="RAM"
            :dimension="false"
            thin
          />
          <div class="mini__val mono">{{ gibPair(snap?.ram?.used_mib, snap?.ram?.total_mib) }}</div>
        </div>
      </template>
      <button
        class="nav__toggle btn"
        type="button"
        :aria-label="collapsed ? 'Desplegar menú' : 'Plegar menú'"
        :aria-expanded="!collapsed"
        @click="collapsed = !collapsed"
      >
        <Icon :name="collapsed ? 'expand' : 'collapse'" :size="16" />
        <span v-if="!collapsed">Plegar</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.nav {
  width: var(--nav-w);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--line);
  background: var(--bg);
  position: sticky;
  top: var(--topbar-h);
  height: calc(100vh / var(--zoom) - var(--topbar-h));
}
.nav--collapsed {
  width: var(--nav-w-collapsed);
}
.nav__list {
  list-style: none;
  margin: 0;
  padding: 10px 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
}
.nav__link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  color: var(--ink-dim);
  text-decoration: none;
  border-radius: var(--radius-sm);
  font-weight: 500;
}
.nav__link:hover {
  color: var(--ink);
  background: rgba(255, 255, 255, 0.05);
}
.nav__link.router-link-active {
  color: var(--ink);
  background: color-mix(in srgb, var(--accent) 16%, transparent);
}
.nav__link.router-link-active :deep(svg) {
  color: var(--accent);
}
.nav--collapsed .nav__text {
  display: none;
}
.nav__phase {
  margin-left: auto;
  font-size: 10px;
  color: var(--ink-faint);
}
.nav__foot {
  margin-top: auto;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mini__head {
  font-size: 12px;
  margin-bottom: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mini__val {
  font-size: 11px;
  color: var(--ink-faint);
  margin-top: 2px;
}
.nav__toggle {
  justify-content: center;
  padding: 4px;
}
</style>
