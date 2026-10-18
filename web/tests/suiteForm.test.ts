import { describe, expect, it } from "vitest";
import type { Suite } from "../src/api/types";
import { initialState, parseNumList, parsePairs, toParams } from "../src/lib/suiteForm";

const suite = {
  id: "contexto",
  name: "Contexto",
  defaults: { sizes: [2048, 4096], depths: [10, 90], max_tokens: 64, include: null, custom: [] },
  fields: [
    { key: "sizes", label: "Tamaños", type: "numlist" },
    { key: "max_tokens", label: "Tokens", type: "number" },
    { key: "include", label: "Preguntas", type: "choices", choices: [{ value: "a", label: "a" }] },
    { key: "custom", label: "Propias", type: "pairs" },
  ],
} as unknown as Suite;

describe("formulario de suites de calidad", () => {
  it("lee listas de números con comas, espacios o punto y coma", () => {
    expect(parseNumList("2048, 4096 8192;16384")).toEqual([2048, 4096, 8192, 16384]);
    expect(parseNumList("")).toBeNull();
    expect(parseNumList("1, dos")).toBeNull();
  });

  it("lee preguntas propias «pregunta | respuesta» e ignora las líneas incompletas", () => {
    expect(parsePairs("¿2+2? | 4\nsolo pregunta\n¿a | b? | c\n | vacía")).toEqual([
      { pregunta: "¿2+2?", respuesta: "4" },
      { pregunta: "¿a", respuesta: "b? | c" },
    ]);
  });

  it("convierte el estado del formulario en parámetros de la API", () => {
    const state = initialState(suite);
    expect(state.sizes).toBe("2048, 4096");
    expect(toParams(suite, state)).toEqual({ sizes: [2048, 4096], max_tokens: 64, include: null, custom: [] });
    state.include = ["a"];
    state.custom = "p | r";
    state.sizes = "1024";
    expect(toParams(suite, state)).toMatchObject({ include: ["a"], custom: [{ pregunta: "p", respuesta: "r" }], sizes: [1024] });
  });

  it("explica qué campo está mal", () => {
    const state = initialState(suite);
    state.sizes = "x";
    expect(() => toParams(suite, state)).toThrow(/Tamaños/);
    state.sizes = "1";
    state.max_tokens = "";
    expect(() => toParams(suite, state)).toThrow(/Tokens/);
  });
});
