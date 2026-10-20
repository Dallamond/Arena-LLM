// Etiquetas de un run: mismas reglas que el servidor (`clean_tags` en server/app.py).
export const MAX_TAGS = 12;
export const MAX_TAG_LEN = 32;

/** Normaliza una etiqueta: espacios colapsados y recortada a la longitud máxima. */
export const normalizeTag = (raw: string): string => raw.split(/\s+/).filter(Boolean).join(" ").slice(0, MAX_TAG_LEN);

/** Lista con la etiqueta añadida, o `null` si no hay nada que cambiar (vacía, repetida o sin hueco). */
export function addTag(tags: string[], raw: string): string[] | null {
  const tag = normalizeTag(raw);
  if (!tag || tags.length >= MAX_TAGS) return null;
  if (tags.some((t) => t.toLowerCase() === tag.toLowerCase())) return null;
  return [...tags, tag];
}

export const removeTag = (tags: string[], tag: string): string[] => tags.filter((t) => t !== tag);
