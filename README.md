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
4. Defaults: model `qwen2.5:14b-instruct`, host `http://127.0.0.1:3000`

### Open WebUI host behavior

- The CLI sends chat requests to `<host>/api/chat/completions`.
- You can set `host` to a base URL like `http://localhost:3000` or to a custom base path.
- On startup, the CLI injects persisted SQLite campaign memories from `data/campaign.db` into the initial system prompt so the model begins with prior session continuity.

## CLI commands and shutdown

- Run `marvel-narrator-cli --help` to see CLI flags and interactive command help.
- During a session:
  - `/help` shows the available commands
  - `/roll [--edge|--trouble] [--tn N]` runs a deterministic roll
  - `/rule <keyword>` searches the local rulebook
  - `exit`, `quit`, `/exit`, or `/quit` gracefully shut down the narrator
- Pressing `Ctrl+C` or `Ctrl+D` also exits the CLI cleanly.
