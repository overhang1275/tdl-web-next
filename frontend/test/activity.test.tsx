import { fireEvent, render, waitFor, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SessionActivity } from "@/components/session-activity";
vi.mock("next/navigation", () => ({ usePathname: () => "/downloads" }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });
it("records navigation and real interaction at most once per minute, without polling", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  render(<SessionActivity />);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  fireEvent.click(document); fireEvent.keyDown(document, { key: "Tab" });
  expect(fetch).toHaveBeenCalledTimes(1);
  vi.setSystemTime(Date.now() + 61_000);
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.keyDown(document, { key: "Tab" });
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(fetch.mock.calls[1][1].headers.get("x-requested-with")).toBe("tdl-web");
});
