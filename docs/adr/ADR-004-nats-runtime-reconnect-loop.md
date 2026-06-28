# ADR-004: NATS Runtime Reconnect Loop

**Status:** Accepted
**Date:** 2026-06-03
**Deciders:** Hermes maintainers
**Supersedes:** ADR-001 §Consequences (the "no self-healing at runtime" clause only;
the `allow_reconnect=False` decision and rationale from ADR-001 remain in force)

---

## Context

ADR-001 set `allow_reconnect=False` on `nats.connect()` to keep the publish path
honest: a `POST /webhook` must not return `200 OK` while messages are silently
buffered in the nats-py client. As written, ADR-001's "Consequences" then stated
operators had to restart Hermes after any NATS disconnect.

In practice that restart-required posture proved operationally noisy: a 30-second
NATS blip required a full Hermes restart, dropping in-flight requests and tripping
unrelated alerts. We needed runtime self-healing **without** giving up the ADR-001
guarantees on the publish path.

---

## Decision

Keep `allow_reconnect=False` on `nats.connect()` at `src/hermes/publisher.py:159`.
Add a Hermes-owned background task `Publisher._reconnect_loop` that owns runtime
reconnection end-to-end.

- The loop is created by `Publisher.connect()` at `src/hermes/publisher.py:126-135`
  and torn down by `Publisher.disconnect()` at `src/hermes/publisher.py:288-303`.
- It polls `self._nc.is_closed` and, on observing a closed connection, re-runs
  `_connect_internal()` under an `asyncio.wait_for(..., timeout=hard_timeout)`
  guard.
- Backoff between *failed* reconnect attempts is bounded exponential:
  `delay = min(reconnect_interval * 2**failed_attempts, max_interval)`
  (`src/hermes/publisher.py:190-196`) with optional multiplicative jitter
  sampled from `[1 - jitter, 1 + jitter]` (`src/hermes/publisher.py:197-198`).
- `failed_attempts` resets to zero on a successful reconnect or when the
  connection is observed alive (`src/hermes/publisher.py:207, 220`); the
  exponent is also saturated at 32 to avoid overflow during very long outages
  (`src/hermes/publisher.py:230-231`).
- The success branch is the **sole** incrementer of `reconnect_count` and
  `NATS_RECONNECTS.labels(result="success")` (`src/hermes/publisher.py:219, 222`).
  The nats-py `reconnected_cb` is still registered for safety but is a documented
  no-op (`src/hermes/publisher.py:145-155`); see issue #526.

Configuration (defaults from `src/hermes/config.py:62-74`):

| Setting                          | Default | Source                |
|----------------------------------|---------|-----------------------|
| `NATS_RECONNECT_INTERVAL`        | 5.0 s   | `config.py:62`        |
| `NATS_RECONNECT_HARD_TIMEOUT`    | 5.0 s   | `config.py:63`        |
| `NATS_RECONNECT_MAX_INTERVAL`    | 60.0 s  | `config.py:69`        |
| `NATS_RECONNECT_JITTER`          | 0.1     | `config.py:74`        |

`Settings._validate_reconnect_backoff_bounds` (`src/hermes/config.py:88-101`)
rejects configurations where `max_interval < base_interval`.

`/health` exposes runtime loop state for operators: `nats_reconnect_count` and
`reconnect_loop_running` (`src/hermes/server.py:355, 361`;
`src/hermes/models.py:71, 77`).

---

## Rationale

- **Preserve ADR-001's publish-path contract.** The publish call still goes through
  a connected `JetStreamContext` and a `503` is returned to the upstream caller
  whenever `is_connected` is false. There is no silent buffering.
- **Bounded blast radius on NATS outages.** Backoff prevents reconnect storms; the
  `max_interval` cap keeps the `NATS_RECONNECTS{result="failed"}` counter linear
  rather than exploding during multi-hour outages (see #525).
- **One counter, one writer.** Centralising the `reconnect_count` increment in
  the loop's success path closes the double-count regression in #526.

---

## Consequences

- Operators get runtime self-healing for transient NATS drops without compromising
  the false-ACK protections from ADR-001.
- `/health` accurately reflects both connection state (`is_connected`) and
  reconnect progress (`nats_reconnect_count`, `reconnect_loop_running`).
- The `nats-py` `reconnected_cb` is registered but never expected to fire; the
  inline comment at `publisher.py:145-155` documents this contract so future
  contributors do not "fix" it.

---

## Alternatives Considered

| Alternative                                | Reason Rejected                                                                                  |
|--------------------------------------------|--------------------------------------------------------------------------------------------------|
| Flip `allow_reconnect=True` (the change #323 proposed) | Reopens ADR-001's false-ACK problem and #526's double-count. |
| Library reconnect + outbox buffer          | Adds complexity and a new failure mode (buffer overflow); does not solve the false-ACK problem. |
| Process restart only (the ADR-001 stance)  | Operationally noisy on transient blips; no clean recovery path for routine NATS rollouts.       |

---

## Cross-references

- ADR-001 (the `allow_reconnect=False` decision; this ADR amends only its
  "Consequences" section)
- Issue #524 — `_stop_event` reuse across `connect()` calls
- Issue #525 — exponential backoff
- Issue #526 — single-writer for `reconnect_count`
- Issue #528 — `/health` exposes `reconnect_loop_running`
- Issue #323 — original (incorrect) report that prompted this documentation refresh

---

## Document Metadata

**Status:** Accepted
**Supersedes:** N/A (amends ADR-001 §Consequences)
**Superseded by:** N/A
