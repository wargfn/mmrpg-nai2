# mmrpg-nai2
Marvel Multiverse Narrator AI 2

## CLI configuration

The narrator CLI supports Open WebUI and can load settings from a TOML file, environment variables, or CLI flags.

- Copy `narrator_config.toml.example` to `narrator_config.toml`
- Edit `[open_webui]` values:
  - `host`
  - `model`
  - `api_key`

### Config precedence

1. CLI flags: `--model`, `--host`, `--api-key`
2. Environment: `NARRATOR_MODEL`, `NARRATOR_OPEN_WEBUI_HOST`, `NARRATOR_API_KEY`
3. Config file: `--config <path>` or `./narrator_config.toml`
4. Defaults: model `llama3.3`, host `http://127.0.0.1:3000`

### Open WebUI host behavior

- The CLI sends chat requests to `<host>/api/chat/completions`.
- You can set `host` to a base URL like `http://localhost:3000` or to a custom base path.
