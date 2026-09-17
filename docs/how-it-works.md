# How it works

Condense takes its per-request settings as HTTP headers
(`x-condense-auth-token`, `x-condense-upstream-url`). hermes has no supported
way to set headers on the Anthropic Messages wire, so this plugin patches them
in.

## Why the plugin is needed

There are two problems. Both show up as errors that look like bad credentials.

**Headers get dropped on the Anthropic wire.** Put `extra_headers` on a
`providers:` entry with `api_mode: anthropic_messages` and hermes silently
throws them away. In `run_agent.py`, `_apply_user_default_headers` returns
early for `anthropic_messages` and `bedrock_converse`, and the guard just above
it skips `apply_custom_provider_extra_headers_to_client_kwargs` for the same two
modes. Both write into `client_kwargs["default_headers"]`, which only the OpenAI
client reads. `build_anthropic_client` in `agent/anthropic_adapter.py` accepts
no headers from its caller; it builds `default_headers` itself from a fixed
branch table. Nothing reaches the Anthropic SDK client, condense never gets your
key, and the request comes back 401.

The key can't go in `Authorization` instead, the Anthropic SDK owns that
header.

**Auxiliary calls build the wrong URL.** `_to_openai_base_url` in
`agent/auxiliary_client.py` rewrites `<root>/anthropic` to `<root>/v1`. That's
right for MiniMax and DashScope, but condense serves its OpenAI API at
`/openai/v1`. A title or compaction summary call ends up at
`https://api.condense.chat/v1/chat/completions`, which matches no route, and you
get `{"detail":"Not Found"}`. Fixing only the URL isn't enough, those calls
never see the per-provider headers and would 401 on the next hop.

## What the plugin does

Four hooks in `plugins/condense_headers/`. None of them change anything for
non-condense routes, and all of them fail open, so a bad lookup can't stop a
session from starting.

1. An `llm_request` middleware merges your `extra_headers` into the provider
   kwargs for the main conversation loop. This works because `extra_headers`
   isn't in `_RESPONSES_ONLY_KWARGS`, so `sanitize_anthropic_kwargs` leaves it
   alone and the SDK applies it per request. It's the only hook that uses a
   supported extension point.

2. A wrapper around `build_anthropic_client` covers agent init, credential
   swaps, client rebuilds and the auxiliary client. Titles, compaction
   summaries and vision build their own client in `agent/auxiliary_client.py`
   and never go through the conversation loop, but they all go through
   `build_anthropic_client`. The wrapper uses `with_options(default_headers=...)`,
   which merges onto the SDK's own headers and keeps base_url, auth, timeout,
   `anthropic-beta` and the OAuth identity headers.

3. Wrappers on `_to_openai_base_url` and `_create_openai_client` fix the
   auxiliary OpenAI path. The rewrite becomes `/openai/v1` for condense hosts
   only, and the client gets the condense headers.

4. A wrapper on `get_custom_provider_extra_headers` fixes the main OpenAI path.
   Core hermes returns the headers of the first entry on a `base_url`, so
   `condense-openai-cc` and `condense-openrouter-cc` would both send whichever
   upstream is listed first. The wrapper uses the plugin's own entry selection
   below.

## Picking which entry's headers apply

The plugin resolves by route, because the middleware context reports
`provider="custom"` for every named entry (hardcoded in
`runtime_provider.py::_resolve_named_custom_runtime`), so the entry name isn't
available there.

Routes are usually shared. Condense has two routes and the example config puts
six entries on them, differing only in `api_mode` and
`x-condense-upstream-url`. The plugin:

1. narrows by `api_mode`
2. then checks `HERMES_CONDENSE_PROFILE`
3. then looks for `--provider` in `sys.argv`
4. otherwise takes the first match and logs a warning

So set `HERMES_CONDENSE_PROFILE` to the entry name you launch with.
