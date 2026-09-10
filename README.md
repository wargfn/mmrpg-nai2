# mmrpg-nai2
Marvel Multiverse Narrator AI 2

## CLI configuration

The narrator CLI can load Ollama settings from a TOML file, environment variables, or CLI flags.

- Copy `narrator_config.toml.example` to `narrator_config.toml`
- Edit `[ollama]` values:
  - `host`
  - `model`
  - `api_key`

### Config precedence

1. CLI flags: `--model`, `--host`, `--api-key`
2. Environment: `NARRATOR_MODEL`, `NARRATOR_OLLAMA_HOST`, `NARRATOR_API_KEY`
3. Config file: `--config <path>` or `./narrator_config.toml`
4. Defaults: model `llama3.3`, host `http://127.0.0.1:11434`
