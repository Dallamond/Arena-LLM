<script setup lang="ts">
import { computed, ref } from "vue";
import { currentHost, currentSnapshot, gpus, gpuSample } from "../api/live";
import { deviceColor, shortName } from "../lib/devices";
import { gibPair } from "../lib/format";
import { NAV } from "../router";
import BarWithOverflow from "./BarWithOverflow.vue";
import Icon from "./Icon.vue";

// Menú plegado: se abre al pasar el cursor (o al enfocar con teclado) y las opciones
// cercanas a la que tocas se desplazan en ola según su distancia.
const open = ref(false);
const hovered = ref<number | null>(null);
function dist(i: number): number {
  return hovered.value === null ? 99 : Math.abs(i - hovered.value);
}

const gpuList = computed(() => gpus(currentHost.value));
const snap = currentSnapshot;
</script>

<template>
  <div class="navslot">
    <nav
      class="nav"
      :class="{ 'nav--open': open }"
      aria-label="Secciones"
      @mouseenter="open = true"
      @mouseleave="(open = false), (hovered = null)"
      @focusin="open = true"
      @focusout="open = false"
    >
      <ul class="nav__list">
        <li
          v-for="(item, i) in NAV"
          :key="item.path"
          :style="{ '--d': dist(i) }"
          @mouseenter="hovered = i"
        >
          <RouterLink :to="item.path" class="nav__link" :title="open ? undefined : item.label">
            <Icon :name="item.icon" />
            <span class="nav__text">{{ item.label }}</span>
            <span v-if="item.phase" class="nav__phase mono">{{ item.phase }}</span>
          </RouterLink>
        </li>
      </ul>

      <div class="nav__foot">
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
      </div>
    </nav>
  </div>
</template>

<style scoped>
/* El hueco en el layout es siempre el del menú plegado; al abrirse, el menú flota encima del contenido */
.navslot {
  width: var(--nav-w-collapsed);
  flex-shrink: 0;
  position: sticky;
  top: var(--topbar-h);
  height: calc(100vh / var(--zoom) - var(--topbar-h));
  z-index: 20;
}
.nav {
  position: absolute;
  inset: 0 auto 0 0;
  width: var(--nav-w-collapsed);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--line);
  background: var(--bg);
  transition: width 0.28s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.28s;
}
.nav--open {
  width: var(--nav-w);
  box-shadow: 8px 0 32px rgba(0, 0, 0, 0.6);
}
.nav__list {
  list-style: none;
  margin: 0;
  padding: 10px 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
  overflow-x: hidden;
}
.nav__list li {
  /* Ola: la opción bajo el cursor sale más, las vecinas menos (d = distancia en opciones) */
  --lift: clamp(0, calc(4 - var(--d, 99)), 4);
  transform: translateX(calc(var(--lift) * 3px)) scale(calc(1 + var(--lift) * 0.012));
  transform-origin: left center;
  transition: transform 0.22s cubic-bezier(0.22, 1, 0.36, 1);
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
  white-space: nowrap;
  transition: color 0.15s, background 0.15s;
}
.nav__link:hover {
  color: var(--ink);
  background: rgba(255, 255, 255, 0.08);
}
.nav__link:hover :deep(svg) {
  transform: scale(1.15);
}
.nav__link :deep(svg) {
  flex-shrink: 0;
  transition: transform 0.2s;
}
.nav__link.router-link-active {
  color: var(--ink);
  background: color-mix(in srgb, var(--accent) 16%, transparent);
}
.nav__link.router-link-active :deep(svg) {
  color: var(--accent);
}
.nav__text,
.nav__phase {
  opacity: 0;
  transition: opacity 0.15s;
}
.nav--open .nav__text,
.nav--open .nav__phase {
  opacity: 1;
  transition-delay: 0.08s;
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
  width: var(--nav-w);
  opacity: 0;
  transition: opacity 0.15s;
}
.nav--open .nav__foot {
  opacity: 1;
  transition-delay: 0.08s;
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
</style>
