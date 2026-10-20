<script setup lang="ts">
import DeviceStrip from "./components/DeviceStrip.vue";
import SideNav from "./components/SideNav.vue";
import TopBar from "./components/TopBar.vue";
import { setVideoMode, videoMode } from "./lib/videoMode";
</script>

<template>
  <a class="skip sr-only" href="#main">Saltar al contenido</a>
  <!-- Modo vídeo: sin barra, menú ni franja de dispositivos; solo el contenido y una salida discreta -->
  <TopBar v-if="!videoMode" />
  <div class="layout">
    <SideNav v-if="!videoMode" />
    <div class="content">
      <DeviceStrip v-if="$route.path !== '/' && !videoMode" />
      <main
        id="main"
        class="main"
        :class="{ 'main--wide': $route.path.startsWith('/batalla/') && !videoMode }"
        tabindex="-1"
      >
        <h1 v-if="videoMode" class="sr-only">Arena LLM</h1>
        <RouterView />
      </main>
    </div>
  </div>
  <button v-if="videoMode" class="video-exit" type="button" title="Salir del modo vídeo (Esc o V)" @click="setVideoMode(false)">
    ✕ Salir del modo vídeo
  </button>
</template>

<style scoped>
.layout {
  display: flex;
  min-height: calc(100vh / (var(--zoom) * var(--video-zoom, 1)) - var(--topbar-h));
}
/* Modo vídeo: sin barra superior, el contenido ocupa toda la altura (1200 px de diseño × 1,6 = 1920 px) */
:global(.video-mode) .layout {
  min-height: calc(100vh / (var(--zoom) * var(--video-zoom, 1)));
}
.video-exit {
  position: fixed;
  right: 10px;
  bottom: 8px;
  z-index: 100;
  font-size: 11px;
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: color-mix(in srgb, var(--bg) 80%, transparent);
  color: var(--ink-dim);
  cursor: pointer;
  opacity: 0.9;
}
.video-exit:hover,
.video-exit:focus-visible {
  opacity: 1;
  color: var(--ink);
}
.content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.main {
  padding: 24px var(--gap) 48px;
  max-width: 1600px;
  width: 100%;
  margin: 0 auto;
  outline: none;
}
.main--wide {
  max-width: none;
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
