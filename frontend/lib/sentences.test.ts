import { describe, expect, it } from "vitest";
import { completedSentences, remainder } from "./sentences";

describe("completedSentences", () => {
  it("returns nothing while a sentence is still streaming", () => {
    expect(completedSentences("Hello there, how are", 0)).toEqual({ sentences: [], next: 0 });
  });

  it("returns finished sentences and keeps the tail for later", () => {
    const text = "Hello there. How are you? I am fine";
    const r = completedSentences(text, 0);
    expect(r.sentences).toEqual(["Hello there.", "How are you?"]);
    expect(remainder(text, r.next)).toBe("I am fine");
  });

  it("does not repeat sentences already spoken", () => {
    const first = completedSentences("One. Two. Thr", 0);
    expect(first.sentences).toEqual(["One.", "Two."]);
    const second = completedSentences("One. Two. Three. Fo", first.next);
    expect(second.sentences).toEqual(["Three."]);
  });

  it("handles the Devanagari danda", () => {
    const r = completedSentences("नमस्ते। आप कैसे हैं? ठीक", 0);
    expect(r.sentences).toEqual(["नमस्ते।", "आप कैसे हैं?"]);
  });

  it("does not split on a decimal number", () => {
    expect(completedSentences("Version 3.5 is out", 0).sentences).toEqual([]);
  });
});
