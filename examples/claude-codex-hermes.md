# Example: Claude Code + Codex + Hermes

This is the simplest useful pattern.

## 1. Start the server

```bash
export AGENT_NERVE_API_KEY="change-me"
agent-nerve serve --host 0.0.0.0 --port 8787
```

## 2. Claude Code creates the task

```bash
export AGENT_NERVE_SERVER="http://127.0.0.1:8787"
export AGENT_NERVE_API_KEY="change-me"

agent-nerve task create \
  --namespace launch-june \
  --title "Publish open-source coordination core" \
  --owner claude-code \
  --status in_progress \
  --summary "Repo discovery complete" \
  --next-action "Extract generic coordination layer"
```

```bash
agent-nerve event emit \
  --namespace launch-june \
  --agent claude-code \
  --kind progress \
  --summary "Mapped existing private Nerve implementation" \
  --details "Safe to extract tasks, events, and claims into a public repo."
```

## 3. Codex claims the site page

```bash
agent-nerve claim acquire \
  --namespace launch-june \
  --resource page:ai-kyletusing-home \
  --agent codex \
  --ttl-seconds 1800 \
  --note "Editing public launch link and OSS wedge card"
```

## 4. Hermes picks up deployment work later

```bash
agent-nerve event emit \
  --namespace launch-june \
  --agent hermes \
  --kind handoff \
  --summary "Remote deploy step picked up on maxxx" \
  --details "Local source is ready; deploying site assets and verifying public path next."
```

## 5. Whoever finishes updates `next_action`

```bash
agent-nerve task update \
  --task-id 1 \
  --status blocked \
  --summary "Site source complete; GitHub push still pending auth" \
  --next-action "Human or authenticated agent pushes repo and swaps final GitHub URL"
```

That is enough for a second session on another machine to open the same
namespace, read the task summary, tail the events, inspect any active claims,
and continue without a long prompt recap.
