# Short-code ticket exchange

This service exchanges a six-digit code for an opaque Sailry pairing ticket.
Sailry Link establishes the authenticated connection and saves peer trust.
There is no account login or second approval page. Codes expire after **60 seconds**.
Code `888888` is reserved for Mobile's local offline demonstration and is never allocated.
Clients mint a new invitation and publication request on rollover; they stop on
successful pairing, cancellation or closing the pairing view.

## Contract

All requests use JSON POST bodies over HTTPS. Request IDs are 64 lowercase hex
characters: a 12-character Unix millisecond timestamp followed by 52 random hex
characters (208 random bits). Retain the complete ID and body across retries.
The Go client and TS `requestId()` generate this format. IDs expire after 60
seconds; clocks may lead the server by at most five seconds. Before the first
product release, the contract stays at v1 and changes in place. Client and
service use the same current definition; no legacy formats or migrations are supported.

| Path | Body | Success |
| --- | --- | --- |
| `/v1/codes` | `request_id`, `ticket`, optional `expires_at_ms` | 201: `code`, `cancel_token`, `expires_at_ms` |
| `/v1/codes/redeem` | `request_id`, `code` (string) | 200: `ticket`, `expires_at_ms` |
| `/v1/codes/cancel` | `code`, `cancel_token` | 204 |

Redeem has one winner. Retrying the winning request ID returns the same ticket
until expiry; another claimant receives 404. A lost publication response can
be retried without allocating another code. Cancellation removes the ticket,
but revoking a ticket already delivered to a client must also revoke the local
Link invitation. It does not remove an already established pairing.

Publishers provide their invitation deadline. The server caps validity at both
that deadline and 60 seconds from admission. The client rolls over codes while
sharing is active. Ending sharing invalidates the local invitation, and the
client attempts remote cancellation. Expiry applies even if the network is unavailable.

The service sees the ticket, unlike the former password-authenticated mailbox.
Never publish a private identity key or business credential as a ticket. Disable
request-body logging. Responses are `no-store`; codes and tickets never go in URLs.
Six digits are not a long-term secret: short expiry, one-use arbitration, bounded
capacity and conservative source/global rate limits reduce guessing risk but do
not turn the public service into a high-entropy authentication credential.

## Run and verify

Run these commands from `pairing/` with Node.js 22.13.0 or newer and pnpm 10.31.0.

```sh
pnpm install --frozen-lockfile --ignore-scripts
pnpm typecheck
pnpm test
pnpm build
pnpm build:edgeone
pnpm build:node
```

`pnpm build` runs a Wrangler dry run. The tests cover workerd, Durable Object
SQLite, Node SQLite restart and concurrent HTTP redemption. `pnpm test:edgeone`
runs the EdgeOne Node handler and Blob adapter with a local SQLite-backed fixture.
The suite uses isolated storage. Pairing versions are recorded in `package.json`
and can be tagged as `pairing-v<VERSION>` in this repository.

`pnpm dev` starts Wrangler on loopback. To run the bundled Node service with a
local SQLite database, use the following commands.

```sh
pnpm build:node
mkdir -p .runtime
SAILRY_RELAY_DATABASE="$PWD/.runtime/codes.sqlite3" SAILRY_RELAY_PORT=8794 node dist/server.mjs
```

Configure the running loopback origin as the pairing service in a Sailry test
profile. Host accepts `--pairing-service` with that origin. To test current Link
pairing, run `just test-integration ./internal/link` in a Harness checkout. It
exercises PIN pairing with an isolated HTTP exchange fixture and real loopback
Circuit Relay v2 servers. See the [Harness relay guide](https://github.com/sailry/sailry-harness/blob/main/docs/relays.md).

### Historical Rust/Iroh tests

The optional Rust tests require an external workspace. Harness commit
`aab29693d393e4d981907c235f9b8aa6b0360250` contains the original runtime, Host and
Desktop tests. Set `SAILRY_LEGACY_CHECKOUT` to an absolute path to that checkout
and use its toolchain and prerequisites. These commands attach the legacy
client to an isolated local relay and exercise the opaque ticket contract.

```sh
export SAILRY_LEGACY_CHECKOUT=/absolute/path/to/historical/harness
pnpm test:rust
pnpm test:desktop
pnpm test:rust --host
pnpm test:rust --edgeone
```

## Cloudflare and EdgeOne

EdgeOne Pages is the primary deployment at `https://sailry.link.dux.plus`, the
current client default (`link.DefaultPairingService` in Harness). The domain is
ICP-filed, so the project uses the global acceleration area, which includes
mainland China. Cloudflare at `link.sailry.dev` remains for older clients until
it is retired. The two relays have separate storage: a PIN published on one
cannot be redeemed on the other, so both devices must use the same relay, which
in practice means compatible client versions or the same explicit service URL.

Cloudflare: `wrangler.toml` provisions the `PairingCodes` SQLite Durable Object
binding when explicitly deployed. Development namespaces use the current v1
contract. Do not replace an existing deployment or convert its data implicitly.

EdgeOne deploys only through the manual `Pairing relay` workflow
(`.github/workflows/pairing-relay.yml` in the relay repository), which defaults
to preview. The workflow runs typecheck, tests and build checks, then
`edgeone makers deploy` from this directory without a path argument. The CLI
then builds the project locally into `.edgeone`, including `cloud-functions`
and the `edgeone.json` schedule, and uploads that output. Configure the
relay repository secret `EDGEONE_API_TOKEN` and optionally the variable
`EDGEONE_RELAY_PROJECT` (default `sailry-pairing-relay`). Repository-scoped GitHub Actions secrets must be configured again in the relay
repository. An administrator can grant this repository access to an existing
organization secret, or set a repository secret from the original token store.
When rotating the token, verify the new workflow before revoking the old token.
Keep the deployed EdgeOne project, domain and storage namespace for the cutover.

Console prerequisites:

1. Create an API token in the EdgeOne Pages console. The CLI creates the project
   on first deploy; an existing project must be a direct-upload project. The
   first deployment of a new project must use `production`; EdgeOne rejects a
   preview deployment until one exists.
2. Blob storage needs no binding. The SDK creates the `sailry-pairing-v1`
   namespace on first use; the console shows it read-only after a request.
3. Add the custom domain `sailry.link.dux.plus` to the project, then create the
   CNAME record EdgeOne provides in DNSPod for `dux.plus` (plus any ownership
   TXT record it requests).
4. Enable an HTTPS certificate for the domain (EdgeOne free certificate or an
   uploaded one) and confirm `https://sailry.link.dux.plus/healthz` returns
   `{"ok":true}`.
5. Confirm the `expire-pairing-codes` schedule appears in the project after
   deployment.

Both targets run `src/exchange.ts`, using native storage only: Durable Object/
SQLite on Cloudflare and Blob on EdgeOne. No Redis, external database or
cross-provider proxy is involved. The Blob adapter pins `@edgeone/pages-blob`
0.0.16, uses strong reads and `onlyIfNew` writes, and bypasses caches. See the
[official Blob API](https://pages.edgeone.ai/document/blob-storage).

EdgeOne's project root is this directory. `cloud-functions/[[default]].ts` is the
native Node handler; `edgeone.json` configures build output and a native daily
UTC schedule for `/internal/cleanup`. Daily is EdgeOne's minimum schedule
interval; a more frequent cron fails route generation, leaving only static
assets deployed. The SDK obtains platform credentials inside the deployed
function; never put a project token into client code. The handler
uses platform `clientIp`, not a client-supplied forwarding header. See the
[Node Functions contract](https://pages.edgeone.ai/document/node-functions).

Records belong to the request ID's immutable minute generation. PIN modulo 3
routes to that generation; a generation has 333,333 candidate six-digit codes,
minus the reserved demonstration code in the residue-zero generation.
The three neighboring generations are distinguishable, preserving validity
across minute boundaries and preventing immediate reuse. Publication election
makes orphan candidates unusable; a separate conditional claim selects one
redeemer. Cancellation and expiry are rechecked after asynchronous arbitration.
No distributed read/delete lock or SQL transaction emulation is used.

Rate limits use fixed UTC minute windows: at most 120 attempts per action
globally, six publications and five redemptions/cancellations per source, with
256 allocation slots per generation. A request takes its source slot, a
conditional write, before a global slot, so one source uses at most its
allowance of the global budget however its requests are timed. The global
budget is shared on purpose, because it bounds guessing: 24 sources at five
redemptions each spend it, and nobody else can redeem for the rest of that
minute. Once it is spent a request is refused on a read and writes nothing.
That read is not atomic with the writes: distinct sources that arrive
together while the last global slots are being taken may each leave one
source record and be refused, and such a request has used one of its source's
slots without being served. Those records expire with the window. A request
without a client address shares the single source `unknown`, and cancellation
uses the redemption allowance. Cleanup reads at most 128 records per
page and only deletes generations at least three minutes old. Cloudflare uses
an alarm plus request-driven cleanup; EdgeOne uses a bounded native scheduled
pass plus request-driven cleanup. A failed EdgeOne request-driven cleanup is
logged and the exchange continues; the explicit cleanup route still returns a
failure. Logical expiry is exactly the invitation/ID deadline, independent of
physical cleanup. Failed schedules can leave expired objects until a later
pass; they never make an expired ticket redeemable.

Verify cloud storage and scheduled cleanup separately on each configured cloud
service. Test commands use loopback services and isolated storage.
