// Biblioteca de prompts: separar/unir el texto de Prompt libre y buscar una entrada por su texto.
import type { LibraryPrompt } from "../api/types";

export const SEPARATOR = "\n---\n";

/** Divide el texto del formulario en prompts (separados por una línea con ---). */
export function splitPrompts(text: string): string[] {
  return text
    .split(/^\s*---\s*$/m)
    .map((p) => p.trim())
    .filter(Boolean);
}

export function joinPrompts(prompts: string[]): string {
  return prompts.join(SEPARATOR);
}

/**
 * Añade o quita un prompt de la lista. Si la lista solo tiene el prompt por defecto
 * de la suite, el primero que se añade lo sustituye.
 */
export function togglePrompt(current: string[], prompt: string, defaults: string[]): string[] {
  if (current.includes(prompt)) return current.filter((p) => p !== prompt);
  const onlyDefault = current.length > 0 && current.every((p) => defaults.includes(p));
  return onlyDefault ? [prompt] : [...current, prompt];
}

/** max_tokens sugerido para un conjunto: el mayor de las entradas de la biblioteca que lo tengan. */
export function suggestedMaxTokens(prompts: string[], library: LibraryPrompt[]): number | null {
  const vals = prompts
    .map((p) => library.find((e) => e.prompt === p)?.max_tokens)
    .filter((v): v is number => typeof v === "number");
  return vals.length ? Math.max(...vals) : null;
}

export function findByText(prompt: string, library: LibraryPrompt[]): LibraryPrompt | undefined {
  const t = prompt.trim();
  return library.find((e) => e.prompt === t);
}
