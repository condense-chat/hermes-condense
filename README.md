# hermes-condense

Glue for running [hermes-agent](https://github.com/NousResearch/hermes-agent)
through the [condense](https://condense.chat) proxy, so conversations get
compacted in flight before they reach Anthropic, OpenRouter, or whatever else
you point them at.

```
hermes ──► condense ──► Anthropic / OpenRouter / ...
           compaction
```

It's a plugin and some config examples, not a fork. The plugin exists for one
reason: condense takes its per-request instructions as HTTP headers
(`x-condense-auth-token`, `x-condense-upstream-url`), and hermes has no
supported way to set headers on the Anthropic Messages wire.

## Install

```sh
git clone <this-repo> hermes-condense
cp -r hermes-condense/plugins/condense_headers ~/.hermes/plugins/
hermes plugins enable condense_headers
```

Copy the provider entries you want out of
[`examples/config.yaml`](examples/config.yaml) into `~/.hermes/config.yaml`.
There are six, covering Anthropic direct, OpenAI direct over both OpenAI wire
formats, and OpenRouter over both chat/completions and the Anthropic Messages
API.

## Run

```sh
export CONDENSE_AUTH_TOKEN="ak_..."
export HERMES_CONDENSE_PROFILE=condense-openrouter-msg

hermes --provider condense-openrouter-msg
```

`CONDENSE_AUTH_TOKEN` is a condense API key, generated in the condense
dashboard. Keys are `ak_`-prefixed, and the full secret is only shown at
creation time.

`HERMES_CONDENSE_PROFILE` matters when config entries share a `base_url`, which
most of the example ones do — everything sits on one of two condense routes,
differing only in `api_mode` and `x-condense-upstream-url`. Set it. Details in
[picking which entry's headers apply](#picking-which-entrys-headers-apply).

## Check it works

Without spending tokens:

```sh
curl -s https://api.condense.chat/anthropic/v1/models \
  -H "x-condense-auth-token: $CONDENSE_AUTH_TOKEN"
```

A 401 from condense means the key isn't being accepted. An Anthropic-shaped
`authentication_error` complaining about a missing `x-api-key` is the success
case here: condense accepted your key and forwarded the request upstream,
where a bare model listing has no provider credential to use.

## Docs

[docs/setup.md](docs/setup.md) covers the routes, headers, and the six
configurations in the example config.

[docs/limitations.md](docs/limitations.md) lists what doesn't work yet and the
upstream change that would let most of this repo go away.

[`examples/config.yaml`](examples/config.yaml) is commented inline, including
the compaction settings. Both hermes and condense compact by default, so the
`compression:` block is worth reading before running long sessions.

---

## Why you need the plugin

Two separate problems, and both of them produce errors that look like bad
credentials when they aren't.

**Headers get dropped on the Anthropic wire.** Put `extra_headers` on a
`providers:` entry with `api_mode: anthropic_messages` and hermes silently
throws them away. Three things conspire here. In `run_agent.py`,
`_apply_user_default_headers` returns early for `anthropic_messages` and
`bedrock_converse`, and the guard just above it skips
`apply_custom_provider_extra_headers_to_client_kwargs` for the same two modes.
Both of those write into `client_kwargs["default_headers"]`, which only the
OpenAI client ever reads. Meanwhile `build_anthropic_client` in
`agent/anthropic_adapter.py` accepts no headers from its caller at all; it
computes `default_headers` itself from a fixed branch table. So nothing reaches
the Anthropic SDK client, condense never receives your key, and the request
comes back 401.

The header can't ride on `Authorization` instead; the Anthropic SDK owns that
slot.

**Auxiliary calls build the wrong URL.** `_to_openai_base_url` in
`agent/auxiliary_client.py` rewrites `<root>/anthropic` to `<root>/v1`. That's
right for MiniMax and DashScope. Condense puts its OpenAI surface at
`/openai/v1`, so a title or compaction-summary call ends up at
`https://api.condense.chat/v1/chat/completions`, which matches no route, and
FastAPI hands back `{"detail":"Not Found"}`. Fixing only the URL wouldn't be
enough either, since those calls never see the per-provider headers and would
401 on the next hop.

## What the plugin does about it

Three hooks, in `plugins/condense_headers/`. Nothing here changes behaviour for
non-condense routes, and every hook fails open, so a bad lookup can't stop a
session from starting.

An `llm_request` middleware covers the main conversation loop by merging your
`extra_headers` into the provider kwargs. This works because `extra_headers`
isn't in `_RESPONSES_ONLY_KWARGS`, so `sanitize_anthropic_kwargs` leaves it
alone and the SDK applies it per request. That's the one supported extension
point of the three.

A wrapper around `build_anthropic_client` catches everything else: agent init,
credential swaps, client rebuilds, and the auxiliary client. Middleware alone
isn't enough, because titles, compaction summaries and vision build their own
client in `agent/auxiliary_client.py` and never pass through the conversation
loop. `build_anthropic_client` is the one chokepoint they all share. The
wrapper uses `with_options(default_headers=...)`, which merges onto the SDK's
own headers and leaves base_url, auth, timeout, and the adapter's
`anthropic-beta` and OAuth identity headers intact.

Finally, wrappers on `_to_openai_base_url` and `_create_openai_client` fix the
auxiliary OpenAI-wire path: the rewrite becomes `/openai/v1` for condense hosts
only, and the client it builds gets the account headers.

### Picking which entry's headers apply

Resolution goes by route, because the middleware context reports
`provider="custom"` for every named entry. That's hardcoded in
`runtime_provider.py::_resolve_named_custom_runtime`, so the entry name isn't
available there.

Routes aren't always unique, though — that's the normal case, not the corner
case. Condense has two proxied routes and the example config puts six entries
on them, differing only in `api_mode` and `x-condense-upstream-url`. The plugin
narrows a tie by `api_mode`, then checks `HERMES_CONDENSE_PROFILE`, then falls
back to scanning `--provider` out of `sys.argv`, and failing all three takes the
first match and logs a warning. Set `HERMES_CONDENSE_PROFILE` whenever entries
share a `base_url`.

## Status

Verified against hermes-agent at commit `1dfe781ed` (v0.19.x) and condense as
of July 2026.

The plugin patches hermes internals by name, so treat any hermes upgrade as a
reason to re-run the checks in
[docs/limitations.md](docs/limitations.md#the-plugin-patches-internals-by-name).

The real fix is upstream: an `extra_headers` parameter on
`build_anthropic_client`, plus dropping the `anthropic_messages` exclusion in
`run_agent.py`. If that ever lands, most of this plugin can be deleted.

## License

MIT, see [LICENSE](LICENSE).
