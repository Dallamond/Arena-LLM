import { describe, expect, it } from "vitest";
import type { Run } from "../src/api/types";
import { EMPTY_FILTERS, filterRuns, uniqueValues } from "../src/lib/history";

const run = (id: number, over: Partial<Run>): Run =>
  ({ id, kind: "free", suite: "libre", status: "done", label: null, tags: [], host_name: "pc", device_names: [], ...over }) as Run;

const runs = [
  run(1, { host_name: "pc-a", device_names: ["GPU X"], tags: ["base"] }),
  run(2, { host_name: "pc-b", device_names: ["GPU Y", "GPU X"], suite: "qa", status: "error" }),
  run(3, { host_name: "pc-a", device_names: [], suite: "qa", tags: ["base", "q4"] }),
];
const text = (r: Run) => `${r.id} ${r.suite}`;
const ids = (f: Partial<typeof EMPTY_FILTERS> & { text?: string }) =>
  filterRuns(runs, { ...EMPTY_FILTERS, ...f }, text).map((r) => r.id);

describe("historial · filtros", () => {
  it("sin filtros devuelve todo", () => expect(ids({})).toEqual([1, 2, 3]));
  it("filtra por equipo, dispositivo, prueba, estado y etiqueta", () => {
    expect(ids({ host: "pc-a" })).toEqual([1, 3]);
    expect(ids({ device: "GPU X" })).toEqual([1, 2]);
    expect(ids({ suite: "qa" })).toEqual([2, 3]);
    expect(ids({ status: "error" })).toEqual([2]);
    expect(ids({ tag: "base" })).toEqual([1, 3]);
  });
  it("combina filtros y texto", () => {
    expect(ids({ host: "pc-a", suite: "qa" })).toEqual([3]);
    expect(ids({ text: " QA " })).toEqual([2, 3]);
  });
  it("valores únicos ordenados", () => {
    expect(uniqueValues(runs, (r) => r.device_names ?? [])).toEqual(["GPU X", "GPU Y"]);
  });
});
