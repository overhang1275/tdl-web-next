import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("parses the API error contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            error: { code: "duplicate_job", message: "Ya existe", detail: { job_id: 4 } },
          }),
          { status: 409, headers: { "content-type": "application/json" } },
        ),
      ),
    );
    await expect(apiFetch("/api/v1/jobs")).rejects.toMatchObject({
      status: 409,
      code: "duplicate_job",
      message: "Ya existe",
    });
  });

  it("returns undefined for 204", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    await expect(apiFetch("/api/v1/jobs/1/cancel")).resolves.toBeUndefined();
  });

  it("adds the CSRF header to requests", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/api/v1/jobs");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("x-requested-with")).toBe("tdl-web");
  });

  it("redirects to login only when the session is gone", async () => {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { pathname: "/change-password", assign } });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 401 })));
    await expect(apiFetch("/api/session/change-password")).rejects.toMatchObject({ status: 401 });
    expect(assign).toHaveBeenCalledWith("/login");
  });

  it("shows a rejected current password without leaving the form", async () => {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { pathname: "/change-password", assign } });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ error: { code: "invalid_credentials", message: "La contraseña actual es incorrecta." } }),
      { status: 400, headers: { "content-type": "application/json" } },
    )));
    await expect(apiFetch("/api/session/change-password")).rejects.toMatchObject({
      status: 400,
      code: "invalid_credentials",
      message: "La contraseña actual es incorrecta.",
    });
    expect(assign).not.toHaveBeenCalled();
  });
});
