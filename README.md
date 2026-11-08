![Hermes Agent with Condense](docs/img/hermes-banner.svg)

**Compress long Hermes Agent conversations before they reach the model.** Keep using Hermes with your Anthropic, OpenAI or OpenRouter key. The plugin sends the headers Condense needs to compact conversation history and forward each request to the provider you choose.

[Quickstart](#quickstart) · [Provider profiles](#provider-profiles) · [How the plugin works](docs/how-it-works.md) · [Compatibility](docs/limitations.md)

## Quickstart

Start with a working [Hermes Agent](https://github.com/NousResearch/hermes-agent) installation. This example uses Anthropic. You’ll need an Anthropic API key and a [Condense API key](https://helm.condense.chat/#keys). Copy the Condense key when you create it. It’s shown once.

### 1. Install the plugin

```sh
git clone https://github.com/condense-chat/hermes-condense.git
mkdir -p ~/.hermes/plugins
cp -R hermes-condense/plugins/condense_headers ~/.hermes/plugins/
hermes plugins enable condense_headers
```

### 2. Configure a provider

Open the [example configuration](examples/config.yaml). Merge the `condense-anthropic` entry under `providers:` and the `compression:` settings into your existing `~/.hermes/config.yaml`. If Anthropic is your account’s default upstream and your account lacks the upstream-override capability, omit `x-condense-upstream-url` from that entry.

Set the following in the shell where you launch Hermes. Use the same profile name for `HERMES_CONDENSE_PROFILE` and `--provider` so the plugin selects the correct headers when several entries share a route.

```sh
export CONDENSE_API_TOKEN="your-condense-key"
export ANTHROPIC_API_KEY="your-anthropic-key"
export HERMES_CONDENSE_PROFILE=condense-anthropic
```

### 3. Check the connection

```sh
hermes chat -q "reply with pong" --provider "$HERMES_CONDENSE_PROFILE" -m claude-opus-4-5
```

A reply confirms that the request reached the model. To start an interactive session with the same configuration, run:

```sh
hermes --provider "$HERMES_CONDENSE_PROFILE" -m claude-opus-4-5
```

## Provider profiles

| Provider and API | Profile for `--provider` | Provider key |
| --- | --- | --- |
| Anthropic Messages | `condense-anthropic` | `ANTHROPIC_API_KEY` |
| OpenAI Chat Completions | `condense-openai-cc` | `OPENAI_API_KEY` |
| OpenAI Responses | `condense-openai-responses` | `OPENAI_API_KEY` |
| OpenRouter Chat Completions | `condense-openrouter-cc` | `OPENROUTER_API_KEY` |
| OpenRouter Anthropic Messages | `condense-openrouter-msg` | `OPENROUTER_API_KEY` |

For multi-turn OpenAI sessions, use Chat Completions. The Responses profile has been verified for a single turn. For OpenRouter, start with Chat Completions. Authentication on its Anthropic Messages route is unverified. [Provider limitations](docs/limitations.md)

## Troubleshooting

- **401 with `invalid API key` from Condense.** Check `CONDENSE_API_TOKEN`. For an upstream 401, check the key and auth format for the selected provider. [Routes and credentials](docs/setup.md)
- **Requests go to the wrong provider.** Check that `HERMES_CONDENSE_PROFILE` and `--provider` match the same entry in your config. [How profile selection works](docs/how-it-works.md)
- **An upgrade changes behavior.** The plugin was tested with Hermes Agent v0.21.3 and patches Hermes internals. Run the connection check again after upgrading. [Compatibility notes](docs/limitations.md#the-plugin-patches-internals-by-name)

[Condense benchmarks on other coding-agent workloads](https://condense-chat.github.io/dense/benchmarks/) · [MIT license](LICENSE)
