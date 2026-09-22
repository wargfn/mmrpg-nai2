# mmrpg-nai2
Marvel Multiverse Narrator AI 2

## CLI configuration

The narrator CLI supports Open WebUI and can load settings from a TOML file, environment variables, or CLI flags.

- Copy `narrator_config.toml.example` to `narrator_config.toml`
- Edit `[open_webui]` values:
  - `host`
  - `model`
  - `api_key`
  - `timeout`

### Config precedence

1. CLI flags: `--model`, `--host`, `--api-key`, `--timeout`
2. Environment: `NARRATOR_MODEL`, `NARRATOR_OPEN_WEBUI_HOST`, `NARRATOR_API_KEY`, `NARRATOR_TIMEOUT`
3. Config file: `--config <path>` or `./narrator_config.toml`
4. Defaults: model `qwen2.5:14b-instruct`, host `http://127.0.0.1:3000`, timeout `120`

### Open WebUI host behavior

- The CLI sends chat requests to `<host>/api/chat/completions`.
- You can set `host` to a base URL like `http://localhost:3000` or to a custom base path.
- Use `--timeout`, `NARRATOR_TIMEOUT`, or `[open_webui].timeout` to override the default HTTP timeout in seconds.
- On startup, the CLI injects persisted SQLite campaign memories from `data/campaign.db` into the initial system prompt so the model begins with prior session continuity.

## Discord bot

The repository also includes a Discord interface that mirrors the shared `GameSessionController` backend used by the CLI.

- Install dependencies and set `NARRATOR_DISCORD_BOT_TOKEN` (preferred) or `DISCORD_BOT_TOKEN`.
- Optionally add a `[discord]` block to `narrator_config.toml`:
  - `command_prefix`
  - `campaign_channel_id` (required to enable freeform narration)
  - `history_limit`
  - `token` (environment variables are preferred for secrets)
- Start the bot with `marvel-narrator-discord` or `python -m marvel_mcp_narrator.interfaces.discord_bot`.
- Supported environment variables are `NARRATOR_DISCORD_BOT_TOKEN`, `DISCORD_BOT_TOKEN`, and `NARRATOR_DISCORD_CAMPAIGN_CHANNEL_ID`.
- You can also pass `--token <discord-bot-token>` and `--campaign-channel-id <channel-id>` on the command line; these override environment variables and config file values.
- To run it as a detached background service, use `marvel-narrator-discord --background --token <discord-bot-token> --campaign-channel-id <channel-id> --log-file /path/to/discord.log --pid-file /path/to/discord.pid`.
- Run `!sync-commands` once from a Discord server administrator account to sync slash commands when needed.
- The bot supports hybrid slash/text commands for:
  - `/roll` with arguments `edges`, `troubles`, and `modifier` (text form: `!roll [edges] [troubles] [modifier]`)
  - `/rule` with argument `query` (text form: `!rule <query>`)
  - `/combat status`
  - `/attack` with arguments `target`, `rank`, and `marvel_die` (text form: `!attack <target> <rank> <marvel_die>`)
- Natural messages are only forwarded when `campaign_channel_id` is configured; otherwise slash/text commands still work, but freeform narration is disabled.

## FastMCP narrator server

- Start the FastMCP narrator server with `python -m marvel_mcp_narrator.mcp_servers.narrator_tools`.
- List exposed tools with `python -m marvel_mcp_narrator.mcp_servers.narrator_tools --list-tools`.
- To run it as a detached background service, use `python -m marvel_mcp_narrator.mcp_servers.narrator_tools --background --log-file /path/to/narrator-tools.log --pid-file /path/to/narrator-tools.pid`.

## CLI commands and shutdown

- Run `marvel-narrator-cli --help` to see CLI flags and interactive command help.
- During a session:
  - `/help` shows the available commands
  - `/roll [edges] [troubles]` or `/roll [--edges N] [--troubles N] [--tn N]` runs a deterministic d616 roll
  - `/rules <keyword>` or `/rule <keyword>` searches the local rulebook
  - `/attack <attacker> <ability> <target> [manual d616 roll] [--edges N] [--troubles N] [--focus]` resolves a player attack and can ingest manual reports such as `[4, 5, 1 (Marvel)]` where the Marvel die is explicitly marked
  - `/npc-attack <attacker> <ability> <target> [--edges N] [--troubles N] [--focus]` automatically resolves an NPC or enemy action
  - `/combat` shows tracked combatant health/focus state
  - `/memories` prints stored campaign memory entries
  - A plain manual d616 report such as `[4, 5, 1 (Marvel)]` is normalized and added to the session history without calling the model; manual reports must explicitly mark the Marvel die
  - `exit`, `quit`, `/exit`, or `/quit` gracefully shut down the narrator
- Pressing `Ctrl+C` or `Ctrl+D` also exits the CLI cleanly.
