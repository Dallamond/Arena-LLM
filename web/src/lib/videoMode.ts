// Modo vídeo: pantalla limpia y grande para grabar. Clase `video-mode` en <html> (ver base.css).
// Se activa con el botón de la barra superior, la tecla V o `?video=1`; se sale con Esc o el mismo botón.
// La preferencia se recuerda en localStorage (si no hay almacenamiento, solo dura la sesión).

import { ref, watch } from "vue";

const KEY = "arena.videoMode";

/** Factor de alto que aplican las gráficas en modo vídeo. */
export const VIDEO_CHART_SCALE = 1.5;

function readStored(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

/** `?video=1` activa, `?video=0` desactiva; cualquier otra cosa no decide nada. */
export function fromQuery(search: string): boolean | null {
  const v = new URLSearchParams(search).get("video");
  return v === "1" ? true : v === "0" ? false : null;
}

/** Las teclas V y Esc no valen mientras se escribe en un campo. */
export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

/** Qué hace una tecla con el modo actual: el nuevo valor, o `null` si no cambia nada. */
export function nextOnKey(key: string, active: boolean, target: EventTarget | null, mods = false): boolean | null {
  if (mods || isTyping(target)) return null;
  if (key === "v" || key === "V") return !active;
  if (key === "Escape" && active) return false;
  return null;
}

export const videoMode = ref(false);

export function setVideoMode(on: boolean): void {
  videoMode.value = on;
}

export const toggleVideoMode = () => setVideoMode(!videoMode.value);

let started = false;

/** Lee la preferencia, aplica la clase al <html> y engancha el teclado. Idempotente. */
export function initVideoMode(): void {
  if (started) return;
  started = true;
  videoMode.value = fromQuery(window.location.search) ?? readStored();
  watch(
    videoMode,
    (on) => {
      document.documentElement.classList.toggle("video-mode", on);
      try {
        localStorage.setItem(KEY, on ? "1" : "0");
      } catch {
        /* sin almacenamiento: solo se pierde la preferencia */
      }
    },
    { immediate: true },
  );
  window.addEventListener("keydown", (e) => {
    const next = nextOnKey(e.key, videoMode.value, e.target, e.ctrlKey || e.metaKey || e.altKey);
    if (next !== null) setVideoMode(next);
  });
}
