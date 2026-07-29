# Limitations

## What works

| Configuration | Route | Status |
|---|---|---|
| condense → Anthropic direct | `/anthropic` | works with the plugin |
| condense → OpenAI, chat/completions | `/openai/v1` | works **without** the plugin |
| condense → OpenAI, Responses | `/openai/v1` | unverified; see below |
| condense → OpenRouter, chat/completions | `/openai/v1` | works **without** the plugin |
| condense → OpenRouter, Anthropic Messages | `/anthropic` | works with the plugin; see the auth note below |
| condense → Vertex AI, Anthropic Messages | `/anthropic` | not supported; use the chat/completions route |

There is no OpenAI entry on the `/anthropic` route. OpenAI serves no Anthropic
Messages endpoint, so there is no upstream to override to.

---

## OpenAI over the Responses API

Unverified end to end. The route exists on condense
(`POST /openai/v1/responses`) and hermes has the matching `codex_responses`
api_mode, but the combination has not been exercised here.

Two things to watch if you try it. Hermes routes a distinct kwarg set to this
wire — `_RESPONSES_ONLY_KWARGS` in `sanitize_anthropic_kwargs` exists precisely
because the two OpenAI wires disagree — so a kwarg rejected on one may be
required on the other. And compaction on this wire has to preserve encrypted
reasoning items across turns; if condense drops or reorders them, expect the
upstream to reject the turn rather than silently degrade.

Use `condense-openai-cc` if you want the verified path.

---

## Vertex AI over the Anthropic Messages API

Not supported. On the Anthropic route condense appends a fixed `/v1/messages`
to the base you give it. Vertex's Anthropic route puts the model in the path
instead:

```
{base}/v1/projects/<p>/locations/<l>/publishers/anthropic/models/<model>:streamRawPredict
```

and expects a different body shape. The `condense-vertex-msg` entry in the
example config is disabled, and kept only as a record of the shape.

**Use Vertex through the chat/completions route instead.** Point
`x-condense-upstream-url` at its OpenAI-compatible surface:

```
https://<region>-aiplatform.googleapis.com/v1beta1/projects/<project>/locations/<region>/endpoints/openapi
```

Condense appends `/chat/completions`, and the rotating google-auth bearer is
forwarded as-is. You give up thinking-signature fidelity and `cache_control`.

---

## OpenRouter over the Anthropic Messages API

Unverified. On the Anthropic route the credential is forwarded upstream as
`x-api-key`, which is what the Anthropic SDK sends. OpenRouter documents
`Authorization: Bearer`.

If `condense-openrouter-msg` authenticates against condense and then 401s at
OpenRouter, that is the reason, and no header on the hermes end changes it. Use
`condense-openrouter-cc` instead. `condense-anthropic` is unaffected.

---

## Entries sharing a base_url

`get_custom_provider_extra_headers` matches by **base_url**, so two entries on
`/anthropic` that differ only by `x-condense-upstream-url` are ambiguous to it:
the first match wins for both. The plugin resolves this with
`HERMES_CONDENSE_PROFILE` (then `--provider` from argv), but any *upstream* fix
should use the name-resolved `runtime["extra_headers"]`, which
`resolve_runtime_provider` already populates correctly per entry.

---

## Auxiliary traffic follows the route, not the profile

Auxiliary calls (titles, compaction summaries, vision) land on the rewritten
`/openai/v1` route and pick up whichever entry sits there, which is rarely the
one the main conversation is using. On the `condense-anthropic` profile the
main conversation goes to Anthropic while auxiliary calls go somewhere else
entirely.

With more than one chat/completions entry on that route — the example config
has two, `condense-openai-cc` and `condense-openrouter-cc` — the choice is also
ambiguous. `HERMES_CONDENSE_PROFILE` only disambiguates when it names one of
the matching entries, and for auxiliary traffic it usually names the *main*
provider instead, which is on a different route. The plugin then logs a warning
and takes the first match in config order, i.e. `condense-openai-cc`.

Functional and cheap either way, but if you care where auxiliary traffic goes,
pin it explicitly rather than letting it be inferred from a URL:

```yaml
auxiliary:
  title_generation:
    provider: condense-openai-cc
  compression:
    provider: condense-openai-cc
```

---

## Signed thinking blocks

Hermes replays signed thinking blocks on the latest assistant turn, and
`agent/transports/anthropic.py` documents that modifying or reordering them
yields `HTTP 400 "thinking ... blocks in the latest assistant message cannot be
modified"`.

Condense leaves a window of recent conversation uncompacted, so in normal use
the latest turn is untouched. **Unverified**: whether a very large reasoning
turn can outgrow that window.

---

## The plugin patches internals by name

Three symbols, all fail-open:

| Symbol | Module |
|---|---|
| `build_anthropic_client` | `agent/anthropic_adapter.py` |
| `_to_openai_base_url` | `agent/auxiliary_client.py` |
| `_create_openai_client` | `agent/auxiliary_client.py` |

Only the `llm_request` middleware uses a supported extension point. After a
hermes upgrade, re-verify:

1. those three symbols still exist with compatible signatures
2. `extra_headers` is still absent from `_RESPONSES_ONLY_KWARGS` in
   `sanitize_anthropic_kwargs`
3. `_apply_user_default_headers` still returns early for `anthropic_messages`
   (if it no longer does, the plugin may be redundant)

A missing symbol degrades to "headers not attached", i.e. a 401, rather than a
crash.

---

## The upstream fix

Most of this repo exists because hermes has no supported way to attach headers
on the Anthropic wire. The durable fix, in hermes:

1. add `extra_headers: dict[str, str] | None = None` to
   `build_anthropic_client`, merged into `default_headers` **after** the auth
   branch table so caller headers win without clobbering `x-api-key` /
   `anthropic-version`; mirror it in
   `_build_anthropic_client_with_bearer_hook`
2. drop the `anthropic_messages` exclusion in `run_agent.py`
   (`_apply_user_default_headers` and the guard above it), routing the merged
   headers to the new parameter at the `agent/agent_init.py` call site, reusing
   the name-resolved `runtime["extra_headers"]`, not the base_url lookup
3. special-case condense in `_to_openai_base_url`, alongside the existing
   ZAI and Kimi branches

With 1 and 2, the plugin reduces to nothing. With 3 as well, it can be deleted.
