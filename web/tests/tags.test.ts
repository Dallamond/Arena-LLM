import { describe, expect, it } from "vitest";
import { MAX_TAGS, MAX_TAG_LEN, addTag, normalizeTag, removeTag } from "../src/lib/tags";

describe("etiquetas", () => {
  it("normaliza espacios y longitud", () => {
    expect(normalizeTag("  M40   Q4  ")).toBe("M40 Q4");
    expect(normalizeTag("x".repeat(50))).toHaveLength(MAX_TAG_LEN);
  });
  it("no añade vacías ni repetidas (sin distinguir mayúsculas)", () => {
    expect(addTag(["M40"], "  ")).toBeNull();
    expect(addTag(["M40"], "m40")).toBeNull();
    expect(addTag(["M40"], "3060")).toEqual(["M40", "3060"]);
  });
  it("respeta el máximo", () => {
    const full = Array.from({ length: MAX_TAGS }, (_, i) => `t${i}`);
    expect(addTag(full, "otra")).toBeNull();
  });
  it("quita una etiqueta", () => {
    expect(removeTag(["a", "b"], "a")).toEqual(["b"]);
  });
});
