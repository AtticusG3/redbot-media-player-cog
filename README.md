# RedBot Media Player Cog

Standalone source for the `ha_red_rpc` cog used by the RedBot Media Player integration.

## Contents

- `ha_red_rpc`: JSON-RPC bridge methods for Red-DiscordBot Audio control.
- Root and cog `info.json`: downloader metadata for repository installs.

## Install (Red Downloader)

Install from this repository:

```text
[p]repo add redbot_media_player_cog https://github.com/AtticusG3/redbot-media-player-cog
[p]cog install redbot_media_player_cog ha_red_rpc
[p]load ha_red_rpc
```

## Requirements

- Red-DiscordBot `3.5+`
- Python `3.10+`
- Red started with `--rpc`
- Audio cog loaded (`[p]load audio`)

## Local path install

```text
[p]addpath /share/redbot_cogs
[p]cog installpath /share/redbot_cogs ha_red_rpc
[p]load ha_red_rpc
```

If you use the Home Assistant add-on stack in `redBot-hass`, `/share/redbot_cogs/ha_red_rpc` can be seeded and synced from this repository.

## Versioning and releases

- Current release: `1.0.0` (see `CHANGELOG.md`).
- This repository uses release tags for release tracking and changelog alignment.
- Unreleased changes are tracked under the `Unreleased` section in `CHANGELOG.md`.

## Related repositories

- Home Assistant custom component: [redbot-media-player-homeassistant](https://github.com/AtticusG3/redbot-media-player-homeassistant)
- Home Assistant add-on stack and automation flow: [redBot-hass](https://github.com/AtticusG3/redBot-hass)
