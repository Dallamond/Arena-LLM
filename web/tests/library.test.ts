import { describe, expect, it } from "vitest";
import type { LibraryPrompt } from "../src/api/types";
import { findByText, joinPrompts, splitPrompts, suggestedMaxTokens, togglePrompt } from "../src/lib/library";

const entry = (over: Partial<LibraryPrompt>): LibraryPrompt => ({
  id: "x",
  categoria: "logica",
  titulo: "X",
  prompt: "P",
  respuesta: null,
  max_tokens: null,
  origen: "base",
  hash: "000000000000",
  ...over,
});

describe("biblioteca de prompts", () => {
  it("separa y une por líneas con ---", () => {
    expect(splitPrompts("uno\n---\n dos \n  ---  \n\ntres")).toEqual(["uno", "dos", "tres"]);
    expect(splitPrompts(joinPrompts(["a", "b"]))).toEqual(["a", "b"]);
    expect(splitPrompts("  \n---\n")).toEqual([]);
  });

  it("el primero añadido sustituye al prompt por defecto; después se acumulan y se quitan", () => {
    const def = ["por defecto"];
    let list = togglePrompt(def, "A", def);
    expect(list).toEqual(["A"]);
    list = togglePrompt(list, "B", def);
    expect(list).toEqual(["A", "B"]);
    expect(togglePrompt(list, "A", def)).toEqual(["B"]);
    expect(togglePrompt(["mío", "por defecto"], "A", def)).toEqual(["mío", "por defecto", "A"]);
  });

  it("max_tokens sugerido: el mayor de los que tienen sugerencia", () => {
    const lib = [entry({ prompt: "a", max_tokens: 256 }), entry({ prompt: "b", max_tokens: 768 }), entry({ prompt: "c" })];
    expect(suggestedMaxTokens(["a", "b", "c", "otro"], lib)).toBe(768);
    expect(suggestedMaxTokens(["c", "otro"], lib)).toBeNull();
  });

  it("busca por texto ignorando espacios de los extremos", () => {
    const lib = [entry({ id: "k", prompt: "hola" })];
    expect(findByText("  hola\n", lib)?.id).toBe("k");
    expect(findByText("adiós", lib)).toBeUndefined();
  });
});
