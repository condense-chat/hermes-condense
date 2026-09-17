# hermes-condense

Run [hermes-agent](https://github.com/NousResearch/hermes-agent) through the
[condense](https://condense.chat) proxy. Condense compacts the conversation
before it reaches Anthropic, OpenAI or OpenRouter.

It's a hermes plugin plus an example config.

## Setup

Get a condense API key at <https://helm.condense.chat/#keys>. It's shown once,
so copy it.

Install the plugin:

```sh
git clone https://github.com/condense-chat/hermes-condense.git
cp -r hermes-condense/plugins/condense_headers ~/.hermes/plugins/
hermes plugins enable condense_headers
```

Copy the entries you want from [`examples/config.yaml`](examples/config.yaml)
into `~/.hermes/config.yaml`, plus the `compression:` block.

| Entry | Upstream | Provider key |
|---|---|---|
| `condense-anthropic` | Anthropic | `ANTHROPIC_API_KEY` |
| `condense-openai-cc` | OpenAI, chat/completions | `OPENAI_API_KEY` |
| `condense-openai-responses` | OpenAI, Responses | `OPENAI_API_KEY` |
| `condense-openrouter-cc` | OpenRouter, chat/completions | `OPENROUTER_API_KEY` |
| `condense-openrouter-msg` | OpenRouter, Anthropic Messages | `OPENROUTER_API_KEY` |

## Run

```sh
export CONDENSE_API_TOKEN="ck_api_..."
export ANTHROPIC_API_KEY="sk-ant-..."
export HERMES_CONDENSE_PROFILE=condense-anthropic

hermes --provider condense-anthropic -m claude-opus-4-5
```

Set `HERMES_CONDENSE_PROFILE` to the same name you pass to `--provider`.

Quick check:

```sh
hermes chat -q "reply with pong" --provider condense-anthropic -m claude-opus-4-5
```

A 401 with `invalid API key` means condense rejected `CONDENSE_API_TOKEN`. Any
other 401 is coming from the upstream provider key.

## Docs

- [docs/setup.md](docs/setup.md): routes, headers, credentials
- [docs/how-it-works.md](docs/how-it-works.md): why the plugin exists and what
  it patches
- [docs/limitations.md](docs/limitations.md): what doesn't work yet

Tested with hermes-agent v0.21.3. The plugin patches hermes internals, so
recheck after upgrading hermes, see
[docs/limitations.md](docs/limitations.md#the-plugin-patches-internals-by-name).

## License

MIT, see [LICENSE](LICENSE).
