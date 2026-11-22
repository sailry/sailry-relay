import { expect, it } from "vitest";
import { requestId } from "../src/contract";
import { start } from "./edgeone-server";

it("exchanges and cancels an opaque ticket through the local EdgeOne handler", async () => {
  const service = await start();
  const send = (route: string, body: object) => fetch(new URL(route, service.ready), {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  try {
    expect(await (await fetch(new URL("/healthz", service.ready))).json()).toEqual({ ok: true });
    const publication = { request_id: requestId(), ticket: "opaque-edgeone-fixture" };
    const published = await send("/v1/codes", publication);
    expect(published.status).toBe(201);
    const pin = await published.json() as { code: string; cancel_token: string; expires_at_ms: number };
    const replay = await send("/v1/codes", publication);
    expect(replay.status).toBe(201);
    expect(await replay.json()).toEqual(pin);

    const claim = { code: pin.code, request_id: requestId() };
    const redeemed = await send("/v1/codes/redeem", claim);
    expect(redeemed.status).toBe(200);
    expect(await redeemed.json()).toEqual({ ticket: publication.ticket, expires_at_ms: pin.expires_at_ms });
    expect((await send("/v1/codes/redeem", { ...claim, request_id: requestId() })).status).toBe(404);
    expect((await send("/v1/codes/cancel", { code: pin.code, cancel_token: pin.cancel_token })).status).toBe(204);
    expect((await send("/v1/codes/redeem", claim)).status).toBe(404);
  } finally { await service.dispose(); }
});
