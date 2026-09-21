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
  - `/roll [edges] [troubles]` or `/roll [--edges N] [--troubles N] [--tn N]` runs a deterministic d616 roll
  - `/rules <keyword>` or `/rule <keyword>` searches the local rulebook
  - `/attack <attacker> <ability> <target> [manual d616 roll] [--edges N] [--troubles N] [--focus]` resolves a player attack and can ingest manual reports such as `[4, 5, 1 (Marvel)]`
  - `/npc-attack <attacker> <ability> <target> [--edges N] [--troubles N] [--focus]` automatically resolves an NPC or enemy action
  - `/combat` shows tracked combatant health/focus state
  - `/memories` prints stored campaign memory entries
  - A plain manual d616 report such as `[4, 5, 1 (Marvel)]` is normalized and added to the session history without calling the model
  - `exit`, `quit`, `/exit`, or `/quit` gracefully shut down the narrator
- Pressing `Ctrl+C` or `Ctrl+D` also exits the CLI cleanly.
