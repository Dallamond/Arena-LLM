<script setup lang="ts">
import DeviceStrip from "./components/DeviceStrip.vue";
import SideNav from "./components/SideNav.vue";
import TopBar from "./components/TopBar.vue";
</script>

<template>
  <!-- Filtro de trazo "croquis" (desplazamiento ≈ 1 px). Se desactiva con reducción de movimiento. -->
  <svg width="0" height="0" style="position: absolute" aria-hidden="true">
    <filter id="sketch">
      <feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="2" seed="3" />
      <feDisplacementMap in="SourceGraphic" scale="1.6" />
    </filter>
  </svg>
  <a class="skip sr-only" href="#main">Saltar al contenido</a>
  <TopBar />
  <div class="layout">
    <SideNav />
    <div class="content">
      <DeviceStrip />
      <main id="main" class="main" tabindex="-1">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  min-height: calc(100vh / var(--zoom) - var(--topbar-h));
}
.content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.main {
  padding: 20px var(--gap) 40px;
  outline: none;
}
.skip:focus {
  position: fixed;
  top: 8px;
  left: 8px;
  width: auto;
  height: auto;
  clip: auto;
  padding: 6px 10px;
  background: var(--panel);
  z-index: 100;
}
</style>
