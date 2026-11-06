import { describe, expect, it } from "vitest";

import { formatDuration, groupDecimal, humanize, parseUtc, shortHex } from "./format";

describe("format", () => {
  it("groups decimal strings exactly, without float conversion", () => {
    expect(groupDecimal("1234567890123456789012345")).toBe("1,234,567,890,123,456,789,012,345");
    expect(groupDecimal("-5057353294.895818000", 4)).toBe("-5,057,353,294.8958");
    expect(groupDecimal("0.000000004995241924", 12)).toBe("0.000000004995");
    expect(groupDecimal("12.000")).toBe("12");
    expect(groupDecimal(null)).toBe("—");
  });

  it("treats backend timestamps without a zone as UTC", () => {
    expect(parseUtc("2026-11-06T07:21:43.147113").toISOString()).toBe("2026-11-06T07:21:43.147Z");
    expect(parseUtc("2026-11-06T07:21:43+00:00").toISOString()).toBe("2026-11-06T07:21:43.000Z");
  });

  it("formats durations, hex and identifiers", () => {
    expect(formatDuration(850)).toBe("850 ms");
    expect(formatDuration(1300)).toBe("1.3 s");
    expect(formatDuration(125_000)).toBe("2m 5s");
    expect(shortHex("0x8c555A02175966f3c564bF3f3d62E722E6D04200")).toBe("0x8c555A…4200");
    expect(humanize("withdrawal_failure")).toBe("Withdrawal failure");
  });
});
