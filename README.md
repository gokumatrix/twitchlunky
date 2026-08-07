# Twitchlunky

Twitch chat controls your Spelunky 2 runs. Viewers trigger 60+ effects through chat commands, Channel Point redemptions, and community votes — spawning enemies, giving items, cursing the player, forcing dark levels, and more.

## How It Works

```
Twitch Chat --> bridge.py --HTTP:19030--> main.lua (Overlunky/Playlunky)
                    ^                         |
                    +------ UDP:19029 --------+
```

`bridge.py` connects to your Twitch channel, listens for `!commands` and Channel Point redemptions, and queues effects on an HTTP endpoint. The Lua mod polls that endpoint every few frames and applies effects in-game.

No external services, no Crowd Control subscription, no C# builds. Just Python and Lua.

## Requirements

- **Spelunky 2** (Steam)
- **Modlunky2** — [github.com/spelunky-fyi/modlunky2/releases](https://github.com/spelunky-fyi/modlunky2/releases)
- **Python 3.8+**
- **websocket-client** (optional, for Channel Points): `pip install websocket-client`
- A **Twitch application** — [dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps) with redirect URL `http://localhost:3000`

## File Structure

```
Spelunky 2/Mods/Packs/CrowdControl/
├── main.lua           ← game-side mod (effects, HUD, polling)
├── manifest.json      ← Playlunky mod metadata
├── cc_config.txt      ← who can trigger what (edit this)
├── auth.txt           ← Twitch credentials (edit this)
└── bridge/
    └── bridge.py      ← Twitch bot + HTTP server
```

## Setup

### 1. Place the mod files

Copy the `CrowdControl` folder into `Spelunky 2/Mods/Packs/`.

### 2. Configure Twitch credentials

Edit `auth.txt`:

```ini
[auth]
CHANNEL = your_twitch_channel
CLIENT_ID = your_client_id
CLIENT_SECRET = your_client_secret
```

### 3. Enable unsafe scripts

Add to `overlunky.ini` in your Spelunky 2 folder:

```
unsafe_scripts=true
```

### 4. Install websocket library (optional)

```
pip install websocket-client
```

### 5. Launch

1. Open **Modlunky2** → **Playlunky** tab → check **Crowd Control** → **Play**
2. The mod auto-launches `bridge.py` in a visible terminal
3. On first run, your browser opens for Twitch OAuth — authorize and close the tab
4. The terminal shows connection status and effect triggers in real time

## Debug Mode

For local testing without any Twitch account or authentication:

```
cd Mods/Packs/CrowdControl/bridge
python bridge.py --debug
```

This skips all OAuth, IRC, and PubSub connections. The game-side mod (`main.lua`) works normally — it still polls `localhost:19030` for effects.

### stdin Commands

Debug mode gives you an interactive prompt to trigger effects directly:

```
  DEBUG MODE — type effect codes to trigger them
>> spawn_snake                              # trigger as "Debug" user
>> give_jetpack TestUser                    # trigger as specific user
>> level_feeling TestUser i hate it here    # trigger with custom text
>> list                                     # show all available effects
>> quit                                     # exit
```

Format: `effect_code [viewer_name] [custom text]`

### HTTP Test Endpoints

These work in all modes (debug and normal):

**Trigger an effect (bypass all access control):**

```
http://localhost:19030/trigger/spawn_snake/TestUser
http://localhost:19030/trigger/level_feeling/TestUser/hello%20world
http://localhost:19030/trigger/give_jetpack/TestUser
```

**Trigger with full JSON payload:**

```powershell
$body = '{"id":99,"code":"level_feeling","viewer":"TestUser","duration":0,"type":"instant","text":"i hate it here"}'
Invoke-WebRequest -Uri "http://localhost:19030/test" -Method POST -Body $body -ContentType "application/json"
```

**Simulate chat with access control:**

```
http://localhost:19030/chattest/give_kapala/TestUser/nosub     # blocked if sub-only
http://localhost:19030/chattest/give_kapala/TestUser/sub       # allowed
http://localhost:19030/chattest/spawn_ghost/TestUser/sub       # blocked if vote-only
http://localhost:19030/chattest/randomize_item/TestUser/sub    # blocked if points-only
http://localhost:19030/chattest/give_bombs/TestUser/nosub      # allowed if everybody
```

**View loaded config:**

```
http://localhost:19030/config
```

**View active poll state:**

```
http://localhost:19030/status
```

Note: `/trigger/` and `/test` bypass all access control — they're admin endpoints. Use `/chattest/` to verify your `cc_config.txt` categories are working correctly.

## Configuration

### cc_config.txt

Controls who can trigger what. Restart `bridge.py` after changes.

```ini
# Any chatter can use these (free, with cooldown)
EVERYBODY = ["give_bombs", "spawn_snake", "heal_player"]
EVERYBODY_TIMEOUT = 30s

# Only subscribers, mods, and the broadcaster
SUBSCRIBERS_ONLY = ["give_kapala", "kill_player"]
SUBSCRIBERS_TIMEOUT = 15s

# Requires Channel Point redemptions
POINTS_ONLY = ["randomize_item", "steal_item"]

# Periodic polls — chat votes with !vote 1/2/3
VOTE_SYSTEM = ["spawn_ghost", "force_dark", "spawn_olmec"]
POLL_LASTS = 120s
POLL_TIMEOUT = 300s

# Global per-effect cooldown (regardless of who triggers)
TRIGGER_COOLDOWN = ["hurt_player"]
COOLDOWN_TIME = 60s

# Disabled effects (silently ignored)
NO_EFFECT = []
```

- Effects not in any list default to EVERYBODY
- The broadcaster bypasses all cooldowns
- Mods count as subscribers for access
- Time values: `30s` = 30 seconds, `5m` = 5 minutes

### Channel Points Setup

1. Twitch Creator Dashboard → Viewer Rewards → Channel Points → Custom Rewards
2. Name rewards to match effect codes (e.g. `steal_item`, `randomize_item`)
3. Set point costs per reward
4. Or use friendly names and map them in `bridge.py`'s `REWARD_MAP`

### Vote System

Polls auto-appear in chat every `POLL_TIMEOUT` seconds. Each picks 2 random effects from `VOTE_SYSTEM` plus "No Effect" as a third option. Viewers type `!vote 1`, `!vote 2`, or `!vote 3`. The winning effect triggers after `POLL_LASTS` seconds.

## Effects

### Buffs

| Command | Effect |
|---|---|
| `!heal_player` | +1 health |
| `!full_heal` | Full health |
| `!give_bombs` | +4 bombs |
| `!give_ropes` | +4 ropes |
| `!give_paste` | Sticky bomb paste |
| `!give_climbgloves` | Climbing gloves |
| `!give_spikeshoes` | Spike shoes |
| `!give_springshoes` | Spring shoes |
| `!give_kapala` | Kapala |
| `!give_aliencompass` | Alien compass |
| `!give_elixir` | Elixir |
| `!give_truecrown` | True Crown |
| `!give_royaljelly` | Royal Jelly |
| `!give_jetpack` | Jetpack (back item) |
| `!give_vladscape` | Vlad's Cape (back item) |
| `!give_cape` | Cape (back item) |
| `!give_shotgun` | Shotgun (held, drops current) |
| `!give_freezeray` | Freeze ray (held) |
| `!give_teleporter` | Teleporter (held) |
| `!give_scepter` | Scepter (held) |
| `!give_plasma` | Plasma cannon (held) |

### Debuffs

| Command | Effect |
|---|---|
| `!hurt_player` | -1 health |
| `!poison_player` | Poison |
| `!curse_player` | Curse (health set to 1) |
| `!remove_bombs` | Bombs set to 0 |
| `!remove_ropes` | Ropes set to 0 |
| `!remove_helditem` | Drop and destroy held item |
| `!remove_backitem` | Remove back item |
| `!steal_item` | Silently remove held item (protected items exempt) |
| `!stun_player` | Stun (3s) |
| `!giant_head` | Giant head (20s) |
| `!random_teleport` | Teleport to random position |
| `!randomize_item` | Replace held item with random weapon |
| `!punish` | Attach ball and chain |

### Enemies

| Command | Enemy |
|---|---|
| `!spawn_snake` | Snake |
| `!spawn_spider` | Spider |
| `!spawn_bat` | Bat |
| `!spawn_skeleton` | Skeleton |
| `!spawn_hornedlizard` | Horned Lizard |
| `!spawn_caveman` | Caveman |
| `!spawn_scorpion` | Scorpion |
| `!spawn_mantrap` | Mantrap |
| `!spawn_witchdoctor` | Witch Doctor |
| `!spawn_vampire` | Vampire |
| `!spawn_ufo` | UFO |
| `!spawn_shopkeeper` | Shopkeeper |
| `!spawn_hiredhand` | Hired Hand (follows player) |
| `!spawn_vlad` | Vlad |
| `!spawn_anubis2` | Anubis II |
| `!spawn_apep` | Apep (from off-screen) |
| `!spawn_jellyfish` | Mega Jellyfish |
| `!spawn_olmec` | Olmec |
| `!spawn_ghost` | Ghost |
| `!anubis_coffin` | Anubis Coffin |

### Hazards

| Command | Hazard |
|---|---|
| `!spawn_arrowtrap` | Arrow trap (replaces nearby wall) |
| `!spawn_tnt` | Powder keg |
| `!spawn_boulder` | Boulder (above player) |
| `!spawn_lavapot` | Lava pot |
| `!spawn_kali_altar` | Kali altar |
| `!hadoken` | Plasma shot (fires in facing direction) |

### Level Modifiers

| Command | Effect |
|---|---|
| `!speed_up` | 1.5x game speed (20s, stacks up to 3x) |
| `!slow_motion` | 0.5x game speed (15s, stacks up to 3x) |
| `!level_feeling [text]` | Display custom message on screen |
| `!force_dark` | Next level is dark |
| `!force_outpost` | Next level has shopkeeper outpost |
| `!forgive_player` | Reset shopkeeper aggro |

### Chaos

| Command | Effect |
|---|---|
| `!kill_player` | Instant death |
| `!enemy_rain` | Enemies fall from sky |
| `!bomb_rain` | Bombs fall from sky |
| `!explode_all` | All nearby enemies explode |
| `!destroy_altar` | Destroy Kali altar on level |

### Special Commands

| Command | Notes |
|---|---|
| `!effects` / `!help` | Lists available commands in chat |
| `!vote 1/2/3` | Vote in active poll |
| `!level_feeling your text` | Custom text displayed on screen |

## Command Line Options

```
python bridge.py                    # normal mode (requires auth.txt)
python bridge.py --debug            # local testing, no Twitch needed
python bridge.py --no-chat          # disable chat commands
python bridge.py --no-points        # disable channel points
python bridge.py --no-polls         # disable vote system
python bridge.py --config path.txt  # custom config file path
python bridge.py --http-port 19030  # custom HTTP port
python bridge.py --udp-port 19029   # custom UDP port
```

## Adding New Effects

### 1. Add the handler in main.lua

```lua
fx.my_effect = function(r)
    local p = P(); if not p then return false end
    -- your code here
    return true
end
```

### 2. Add to bridge.py's EFFECTS dict

```python
"my_effect": {"name": "My Effect"},
```

For timed effects, include a duration:

```python
"my_effect": {"name": "My Effect", "duration": 15},
```

### 3. Add to the appropriate list in cc_config.txt

```ini
EVERYBODY = [..., "my_effect"]
```

## Troubleshooting

| Problem | Fix |
|---|---|
| Bridge won't start | `taskkill /f /im python.exe` then relaunch |
| Port already in use | Kill leftover bridge process |
| Effects do nothing | Player must be alive and in a level |
| Entity errors on startup | Check `ENT_TYPE` names in Overlunky console (`~` key) |
| OAuth fails | Redirect URL must be exactly `http://localhost:3000` |
| Subscribers not detected | IRC tags capability is auto-requested in bridge.py |
| Speed effects won't revert | Fixed with stack system — update to latest main.lua |
| Game crashes on spawn | Reduce vertical offset or add entity to exclude list |
| Bridge freezes on start | Remove any `input()` or debug `print` statements from bridge.py |
| Config not loading | Check for double commas or syntax errors in cc_config.txt |

## Credits

Created by gokumatrix.