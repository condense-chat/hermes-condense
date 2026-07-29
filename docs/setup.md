# Setup

## Routes

Condense exposes two proxied wire formats, plus verbatim passthrough for
everything else:

| Condense route | hermes `base_url` | hermes `api_mode` |
|---|---|---|
| `POST /anthropic/v1/messages` | `https://<host>/anthropic` | `anthropic_messages` |
| `POST /openai/v1/chat/completions` | `https://<host>/openai/v1` | `chat_completions` |
| `POST /openai/v1/responses` | `https://<host>/openai/v1` | `codex_responses` |
| `ANY /anthropic/{path}`, `ANY /openai/{path}` | (n/a) | passthrough, no compaction |

The SDKs append the rest: the Anthropic SDK adds `/v1/messages` to the base
URL, the OpenAI SDK adds `/chat/completions`. Set `base_url` to the prefix
only.

A base URL whose path ends in `/anthropic` also makes hermes auto-select
`api_mode: anthropic_messages` (`agent/agent_init.py`), so the explicit
`api_mode` in the examples is belt-and-braces.

## Headers

| Header | Purpose |
|---|---|
| `x-condense-auth-token` | your condense account key. Required. Cannot use `Authorization`, since the Anthropic SDK owns that slot |
| `x-condense-upstream-url` | which upstream condense forwards to. Omit for the account default |
| `x-condense-upstream-key` | use condense's stored upstream key instead of the one hermes sends |
| `x-condense-session-id` | groups requests into one session in the dashboard |
| `x-condense-auto-condense-mode` | `sync` \| `async` |
| `x-condense-auto-condense-min-tokens` | hold auto-condense off below N tokens |

`x-condense-upstream-url` needs the upstream-override capability on your
account, and the URL must be HTTPS on a publicly resolvable host. If you run
your own condense, you can pin the upstream in the deployment config instead
and drop the header entirely.

## Upstream base URL shapes

The override you pass is a **base**, not a full URL. Condense appends the rest,
and what it appends differs per wire:

| Wire | condense appends | Anthropic | OpenAI | OpenRouter |
|---|---|---|---|---|
| Anthropic Messages | `/v1/messages` | `https://api.anthropic.com` | (none) | `https://openrouter.ai/api` |
| OpenAI chat/completions | `/chat/completions` | (none) | `https://api.openai.com/v1` | `https://openrouter.ai/api/v1` |
| OpenAI Responses | `/responses` | (none) | `https://api.openai.com/v1` | `https://openrouter.ai/api/v1` |

Note the asymmetry: the Anthropic-wire base carries no `/v1` because condense
adds it, while the OpenAI-wire base keeps its own. Getting this backwards is a
404 from the upstream, not from condense.

The `(none)` cells are gaps in the upstreams, not in condense: OpenAI serves no
Anthropic Messages endpoint, and Anthropic serves no OpenAI-wire endpoint.

## Credentials

`x-condense-auth-token` carries a condense API key, generated in the condense
dashboard. Keys are `ak_`-prefixed. The full secret is shown once at creation;
after that `/me` returns only the masked `ak_<6chars>...` prefix, so copy it
while it is on screen.

```sh
export CONDENSE_AUTH_TOKEN="ak_..."
```

Config values use `${VAR}` expansion, so no secret is written to
`config.yaml`.

### `x-condense-user-id` is not needed

The API key is sufficient on its own. The example config omits it.

## Selecting a configuration

```sh
hermes --provider condense-openrouter-msg
```

`--provider` accepts any name from `providers:`, because the flag deliberately has no
`choices=` restriction. At runtime, `/model` lists them as
`custom:<name>`.

When entries share a `base_url`, also set:

```sh
export HERMES_CONDENSE_PROFILE=condense-openrouter-msg
```

Most of the example config shares: entries 1 and 5 sit on `/anthropic` (as does
the disabled entry 6), and entries 2, 3 and 4 sit on `/openai/v1`. The plugin
narrows a tie by `api_mode` first, which separates the two OpenAI entries from
each other, but `condense-openai-cc` and `condense-openrouter-cc` remain
ambiguous to it, as do `condense-anthropic` and `condense-openrouter-msg`. Set
the variable and the ambiguity goes away.

Without it the plugin falls back to scanning `--provider` from `sys.argv`,
which works for the common launch but not for programmatic use.

## Verifying

Free check, no model invoked:

```sh
curl -s https://api.condense.chat/anthropic/v1/models \
  -H "x-condense-auth-token: $CONDENSE_AUTH_TOKEN"
```

| Response | Meaning |
|---|---|
| 401 from condense | key not sent, or not accepted |
| 404 from condense | wrong route; check the `/anthropic` vs `/openai/v1` prefix |
| Anthropic `authentication_error`, "x-api-key header is required" | **success**: your key was accepted and the request went upstream |

Then one real turn, checking that tool calls and streaming survive the hop.
Watch the reported cache-read ratio: a proxy that mangles `cache_control`
shows up as a collapse in cache hits, which hermes prints per turn.
