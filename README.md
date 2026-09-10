# mmrpg-nai2
Marvel Multiverse Narrator AI 2

## CLI configuration

The narrator CLI can load Open WebUI/Ollama settings from a TOML file, environment variables, or CLI flags.

- Copy `narrator_config.toml.example` to `narrator_config.toml`
- Edit `[ollama]` values:
  - `host`
  - `model`
  - `api_key`

### Config precedence

1. CLI flags: `--model`, `--host`, `--api-key`
2. Environment: `NARRATOR_MODEL`, `NARRATOR_OLLAMA_HOST`, `NARRATOR_API_KEY`
3. Config file: `--config <path>` or `./narrator_config.toml`
4. Defaults: model `llama3.3`, host `http://127.0.0.1:3000/ollama`

### Open WebUI host behavior

- If `host` has no path (for example `http://localhost:3000`), the CLI automatically uses `http://localhost:3000/ollama`.
- If `host` already includes `/ollama`, it is used as-is.
