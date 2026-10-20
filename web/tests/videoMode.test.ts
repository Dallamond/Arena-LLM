import { describe, expect, it } from "vitest";
import { fromQuery, isTyping, nextOnKey } from "../src/lib/videoMode";

const el = (tagName: string, isContentEditable = false) => ({ tagName, isContentEditable }) as unknown as EventTarget;

describe("modo vídeo", () => {
  it("?video=1 activa y ?video=0 desactiva; sin parámetro no decide", () => {
    expect(fromQuery("?video=1")).toBe(true);
    expect(fromQuery("?a=2&video=0")).toBe(false);
    expect(fromQuery("")).toBeNull();
    expect(fromQuery("?video=si")).toBeNull();
  });
  it("detecta cuando se está escribiendo", () => {
    expect(isTyping(el("INPUT"))).toBe(true);
    expect(isTyping(el("TEXTAREA"))).toBe(true);
    expect(isTyping(el("DIV", true))).toBe(true);
    expect(isTyping(el("BUTTON"))).toBe(false);
    expect(isTyping(null)).toBe(false);
  });
  it("V alterna y Esc solo sale", () => {
    expect(nextOnKey("v", false, el("BODY"))).toBe(true);
    expect(nextOnKey("V", true, el("BODY"))).toBe(false);
    expect(nextOnKey("Escape", true, el("BODY"))).toBe(false);
    expect(nextOnKey("Escape", false, el("BODY"))).toBeNull();
    expect(nextOnKey("x", true, el("BODY"))).toBeNull();
  });
  it("ignora las teclas dentro de un campo o con modificadores", () => {
    expect(nextOnKey("v", false, el("INPUT"))).toBeNull();
    expect(nextOnKey("v", false, el("BODY"), true)).toBeNull();
  });
});
