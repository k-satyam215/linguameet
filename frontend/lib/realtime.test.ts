import { describe, expect, it } from "vitest";
import { MAX_CHAT, encode, parseChat, parseReaction } from "./realtime";

const dec = (b: Uint8Array) => new TextDecoder().decode(b);

describe("parseChat", () => {
  it("accepts and trims text", () => {
    expect(parseChat(dec(encode({ text: "  hello  " })))).toBe("hello");
  });
  it("rejects empty, non-string, malformed and non-object payloads", () => {
    for (const raw of ["", "not json", "[]", "null", '{"text":""}', '{"text":"   "}', '{"text":5}', '{"nope":1}']) {
      expect(parseChat(raw)).toBeNull();
    }
  });
  it("caps very long messages", () => {
    expect(parseChat(JSON.stringify({ text: "x".repeat(MAX_CHAT * 3) }))!.length).toBe(MAX_CHAT);
  });
  it("keeps markup as inert text (React escapes it on render)", () => {
    expect(parseChat('{"text":"<img src=x onerror=alert(1)>"}')).toBe("<img src=x onerror=alert(1)>");
  });
});

describe("parseReaction", () => {
  it("parses hand raise and lower", () => {
    expect(parseReaction('{"hand":true}')).toEqual({ kind: "hand", on: true });
    expect(parseReaction('{"hand":false}')).toEqual({ kind: "hand", on: false });
  });
  it("only allows whitelisted emoji", () => {
    expect(parseReaction('{"emoji":"🎉"}')).toEqual({ kind: "emoji", emoji: "🎉" });
    expect(parseReaction('{"emoji":"<script>"}')).toBeNull();
    expect(parseReaction('{"emoji":"💩"}')).toBeNull();
  });
  it("rejects garbage", () => {
    expect(parseReaction("zzz")).toBeNull();
    expect(parseReaction('{"hand":"yes"}')).toBeNull();
  });
});
