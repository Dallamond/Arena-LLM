import type { DeviceInfo } from "../api/types";

/** Color estable del dispositivo (índice asignado y guardado por el servidor). */
export function deviceColor(dev: Pick<DeviceInfo, "kind" | "color_index">): string {
  if (dev.kind === "cpu") return "var(--dev-cpu)";
  if (dev.color_index === null || dev.color_index === undefined) return "var(--line-strong)";
  return `var(--dev-${(dev.color_index % 6) + 1})`;
}

/** Nombre corto: quita el prefijo del fabricante que no aporta en una tarjeta pequeña. */
export function shortName(name: string | null | undefined): string {
  if (!name) return "Dispositivo sin nombre";
  return name.replace(/^NVIDIA\s+(GeForce\s+)?/i, "").replace(/\s+\d+-Core Processor$/i, "");
}

/** El campo está marcado como no disponible por el propio dispositivo. */
export function unavailable(dev: DeviceInfo, field: string): boolean {
  return dev.fields_unavailable?.includes(field) ?? false;
}
