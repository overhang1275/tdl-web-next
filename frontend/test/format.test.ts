import { describe, expect, it } from "vitest";

import { formatBytes, formatDuration, statusLabel } from "@/lib/format";

describe("format helpers", () => {
  it("formats bytes with sensible units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1024 * 1024 * 3.5)).toBe("3.5 MB");
  });

  it("formats durations and missing values", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(42)).toBe("42s");
    expect(formatDuration(90)).toBe("1m 30s");
    expect(formatDuration(3700)).toBe("1h 1m");
  });

  it("translates statuses", () => {
    expect(statusLabel("running")).toBe("En curso");
    expect(statusLabel("completed")).toBe("Completado");
    expect(statusLabel("unknown")).toBe("unknown");
  });
});
