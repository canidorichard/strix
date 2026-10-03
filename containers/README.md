# Strix containers

This directory holds two Dockerfiles:

- `Dockerfile` — the **sandbox** image (Kali-based tooling) that Strix launches to actually run a scan.
- `client.Dockerfile` — the **Strix CLI** itself, built from this repo's source, so you can run the client without installing Python or Go locally.

## Build the client image

```bash
docker build -f containers/client.Dockerfile -t strix-agent .
```

It's a multi-stage build: a builder compiles the Go TUI sidecar and builds a platform wheel, then a slim runtime image installs only that wheel (plus Debian's `docker-cli`).

## Run a headless scan

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD":"$PWD" -w "$PWD" \
  -e STRIX_LLM="openai/gpt-5.4" \
  -e LLM_API_KEY="sk-..." \
  strix-agent -n -t "$PWD" --scan-mode quick --max-budget 10
```

## Other providers

`STRIX_LLM` is any supported model id; `LLM_API_KEY` holds the key for all of them.

| Provider | `STRIX_LLM` | Extra env |
|---|---|---|
| OpenAI | `openai/gpt-5.4` | — |
| Anthropic | `anthropic/claude-sonnet-4-6` | — |
| OpenRouter | `openrouter/z-ai/glm-5.3` | — |
| DeepSeek | `deepseek/deepseek-v4-pro` | `DEEPSEEK_API_BASE=https://api.deepseek.com` |
| Ollama (on host) | `ollama/qwen3-vl` | `LLM_API_BASE=http://host.docker.internal:11434` |
| LM Studio / vLLM | `openai/<model>` | `LLM_API_BASE=http://host.docker.internal:1234/v1` |

DeepSeek needs the base override because LiteLLM defaults the `deepseek/` provider to `https://api.deepseek.com/beta`, while DeepSeek documents `https://api.deepseek.com`.

For a local model running on your host, the container reaches it via `host.docker.internal`:

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD":"$PWD" -w "$PWD" \
  --add-host=host.docker.internal:host-gateway \
  -e STRIX_LLM="ollama/qwen3-vl" \
  -e LLM_API_BASE="http://host.docker.internal:11434" \
  strix-agent -n -t "$PWD" --scan-mode quick --max-budget 10
```

(`--add-host=host.docker.internal:host-gateway` is needed on Linux; Docker Desktop provides it automatically.)

### Why the mount flags are required

- **`-v /var/run/docker.sock:...`** — the client doesn't run tools itself; it drives your **host** Docker daemon to launch the sandbox image. Without the socket it can't scan.
- **`-v "$PWD":"$PWD" -w "$PWD"`** — bind mounts are resolved by the host daemon, so the target path must be identical inside the container and on the host. A remapped path like `-v "$PWD/DATA:/DATA"` makes the client hand `/DATA` to the daemon, which doesn't exist on the host, so the sandbox would mount an empty directory.

## Output

Results are written to `$PWD/strix_runs/<run-name>/`:

- `run.json` — `status`, timestamps, targets, and `llm_usage` (check `status` and `llm_usage.cost` against the budget before calling a run clean)
- `penetration_test_report.md`
- `vulnerabilities.json`, `vulnerabilities.csv`, and `vulnerabilities/<id>.md` (one per finding)
- `findings.sarif` (SARIF 2.1.0; emitted even when clean)
- `.state/` — resume state

## Caveats

- The local target is bind-mounted into the sandbox **read-write**, so the agent may create or modify files in your target directory.
- The client requires the `docker` CLI on `PATH` (a start-up guard); the image includes it via Debian's `docker-cli`. The daemon itself stays on the host.
