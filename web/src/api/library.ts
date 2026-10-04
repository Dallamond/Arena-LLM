// Biblioteca de prompts del servidor, cargada una vez y compartida por todas las vistas.
import { ref } from "vue";
import { api } from "./live";
import type { PromptLibrary } from "./types";

export const library = ref<PromptLibrary | null>(null);
export const libraryError = ref<string | null>(null);
let pending: Promise<PromptLibrary | null> | null = null;

export function loadLibrary(): Promise<PromptLibrary | null> {
  pending ??= api<PromptLibrary>("/api/prompts")
    .then((l) => (library.value = l))
    .catch((e) => {
      libraryError.value = e instanceof Error ? e.message : String(e);
      pending = null; // se reintenta en la siguiente vista
      return null;
    });
  return pending;
}
