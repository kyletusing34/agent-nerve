# Security Notes

`Agent Nerve` is meant to be a coordination layer, not a dumping ground for raw
prompts, full repo diffs, or credentials.

## Safe defaults included

- Bearer-token protected write endpoints
- Server-side redaction for common secret patterns
- Local home-path redaction
- Lease-based claims so abandoned sessions do not create permanent locks
- Local queued writes so agents do not need to retry blindly on network failures

## Still recommended

- Keep deployment private by default.
- Put it behind Tailscale, a VPN, SSH tunnel, or a private reverse proxy.
- Use separate namespaces per client, repo, or incident.
- Keep summaries short and operational.
- Store links to artifacts, not the full sensitive artifact contents.
- Rotate the API key if it was ever exposed in agent output.

## Do not use this for

- long-term secret storage
- production credentials
- raw customer PII dumps
- unrestricted internet-facing anonymous writes

## Suggested redaction policy

Good event:

```text
Patched checkout webhook validation. Next: verify with one real test event.
```

Bad event:

```text
Here is the full .env plus the exact customer payload and auth headers.
```

## Suggested deployment pattern

For most teams, the best default is:

1. self-host the SQLite-backed service on a trusted machine
2. expose it only on a private network
3. put agents on the same private path
4. mirror or export selected namespaces elsewhere if humans need dashboards
