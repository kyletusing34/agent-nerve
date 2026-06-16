# Agent Nerve

[![PyPI version](https://img.shields.io/pypi/v/agent-nerve.svg)](https://pypi.org/project/agent-nerve/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/kyletusing34/agent-nerve?style=social)](https://github.com/kyletusing34/agent-nerve/stargazers)

`Agent Nerve` is a local-first shared operations layer for mixed agent fleets.

It gives Claude Code, Codex, Hermes, and custom agents a small common place to:

- write durable task updates
- hand off work across sessions and machines
- claim shared resources before they step on each other
- resume a task from what another agent already did

This is not a vector-memory product. It is an append-only coordination layer with
task state, event history, and lease-based claims.

## Install

```bash
pip install agent-nerve
```

## Why it exists

Most agent tools remember prompts. Fewer solve operational continuity.

The problem people actually hit is:

- one Claude session starts the work
- another Claude or Codex session picks it up later
- a server-side worker like Hermes does the heavy lifting
- nobody has a clean, shared, machine-readable history of what happened, what is
  still blocked, and who currently owns a risky resource

`Agent Nerve` is the missing shared log.

## What you get

- stdlib-only Python server
- SQLite storage
- bearer-token protected write API
- queued writes for flaky networks
- task records with `next_action`
- append-only event history
- lease-based claims for shared resources
- built-in redaction for common secrets and user-home paths
- CLI helpers for agents and operators

## Quickstart

```bash
git clone https://github.com/kyletusing34/agent-nerve.git
cd agent-nerve
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
export AGENT_NERVE_API_KEY="change-me"
agent-nerve serve --host 127.0.0.1 --port 8787
```

In another terminal:

```bash
export AGENT_NERVE_SERVER="http://127.0.0.1:8787"
export AGENT_NERVE_API_KEY="change-me"

agent-nerve task create \
  --namespace demo \
  --title "Build the launch page" \
  --owner claude-code \
  --summary "Initial task created"

agent-nerve event emit \
  --namespace demo \
  --agent claude-code \
  --kind progress \
  --summary "Read the repo and found the landing page entrypoint" \
  --details "Next: patch headline and CTA."

agent-nerve claim acquire \
  --namespace demo \
  --resource repo:landing-page \
  --agent claude-code \
  --ttl-seconds 1800 \
  --note "Editing homepage hero"
```

Inspect state:

```bash
agent-nerve task list --namespace demo
agent-nerve event tail --namespace demo --limit 20
agent-nerve claim list --namespace demo
```

## Core concepts

### Namespace

A namespace is the shared scope for a project, team, or incident.

Examples:

- `client-acme-site`
- `infra-maxxx`
- `offer-launch-june`

### Task

A task is the current durable snapshot:

- title
- status
- owner
- summary
- next action

### Event

An event is the historical timeline:

- progress updates
- blockers
- handoffs
- notes
- completion

### Claim

A claim is a temporary lease on a shared resource:

- a file or repo section
- a deploy slot
- a migration
- a queue item

Claims expire automatically based on `lease_expires_at`, so abandoned sessions do
not lock the system forever.

## Safe-by-default behavior

Before data is written, `Agent Nerve` redacts:

- `sk-...` style API keys
- bearer tokens
- AWS access key ids
- PEM private-key blocks
- local home-directory paths

You should still keep high-risk secrets out of summaries when possible, but the
server adds a defensive scrub instead of trusting every agent to behave.

More detail: [docs/security.md](docs/security.md)

## Suggested pattern for Claude Code / Codex / Hermes

1. Create or claim the task.
2. Emit short progress events at meaningful checkpoints.
3. Write blockers as explicit events, not hidden in chat.
4. Update `next_action` before handing off.
5. Use claims before editing risky shared resources.
6. Release claims when done.

## CLI reference

Start server:

```bash
agent-nerve serve --host 0.0.0.0 --port 8787 --db ./data/agent_nerve.sqlite3
```

Create task:

```bash
agent-nerve task create --namespace ops --title "Review queue" --owner hermes
```

Update task:

```bash
agent-nerve task update \
  --task-id 3 \
  --status blocked \
  --summary "Waiting on Cloudflare token" \
  --next-action "Human restores token"
```

Emit event:

```bash
agent-nerve event emit \
  --namespace ops \
  --agent codex \
  --kind handoff \
  --summary "Patched source and need maxxx deploy" \
  --details "Source is ready locally; remote deploy still pending."
```

Acquire claim:

```bash
agent-nerve claim acquire \
  --namespace ops \
  --resource service:lead-intake \
  --agent hermes \
  --ttl-seconds 900
```

Release claim:

```bash
agent-nerve claim release --claim-id 4
```

## API

Read endpoints:

- `GET /api/health`
- `GET /api/state?namespace=<name>`
- `GET /api/tasks?namespace=<name>`
- `GET /api/events?namespace=<name>&limit=100`
- `GET /api/claims?namespace=<name>`

Write endpoints:

- `POST /api/tasks`
- `PATCH /api/tasks/<id>`
- `POST /api/events`
- `POST /api/claims`
- `DELETE /api/claims/<id>`

Write calls require one of:

- `Authorization: Bearer <key>`
- `X-Agent-Nerve-Key: <key>`

## Example integrations

See [examples/claude-codex-hermes.md](examples/claude-codex-hermes.md)

## What this is not

- not a central planner
- not a vector store
- not a chat relay
- not a secret store
- not a replacement for repo-local docs or issue trackers

It is the smallest useful shared ops layer between agents.
