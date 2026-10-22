import { describe, expect, it } from "vitest";

import { formatBytes, shortId } from "./utils";

describe("formatBytes", () => {
  it("formats document sizes for upload feedback", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(2 * 1024 * 1024)).toBe("2.0 MB");
  });
});

describe("shortId", () => {
  it("shortens opaque identifiers without changing short values", () => {
    expect(shortId("abc")).toBe("abc");
    expect(shortId("1234567890123456")).toBe("12345678…");
  });
});
