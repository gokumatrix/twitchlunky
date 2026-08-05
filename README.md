# Twitchlunky

Twitch chat controls your Spelunky 2 runs. Viewers trigger 60+ effects through chat commands, Channel Point redemptions, and community votes.

## How It Works

```
Twitch Chat --> bridge.py --HTTP:19030--> main.lua (Overlunky/Playlunky)
                    ^                         |
                    +------ UDP:19029 --------+
```

bridge.py connects to your Twitch channel, listens for !commands and Channel Point redemptions, and queues effects on an HTTP endpoint. The Lua mod running inside Spelunky 2 polls that endpoint every few frames and applies effects in-game.

No external services, no Crowd Control subscription, no C# builds. Just Python and Lua.

## Requirements

- Spelunky 2 (Steam)
- Modlunky2: https://github.com/spelunky-fyi/modlunky2/releases
- Python 3.8+
- websocket-client (optional, for Channel Points): pip install websocket-client
- A Twitch application: https://dev.twitch.tv/console/apps (redirect URL: http://localhost:3000)

## File Structure

```
Spelunky 2/Mods/Packs/CrowdControl/
  main.lua           game-side mod (effects, HUD, polling)
  manifest.json      Playlunky mod metadata
  cc_config.txt      who can trigger what (edit this)
  auth.txt           Twitch credentials (edit this)
  bridge/
    bridge.py        Twitch bot + HTTP server
```

## Setup

### 1. Place the mod files
Copy the CrowdControl folder into Spelunky 2/Mods/Packs/.

### 2. Configure Twitch credentials
Edit auth.txt:
```
[auth]
CHANNEL = your_twitch_channel
CLIENT_ID = your_client_id
CLIENT_SECRET = your_client_secret
```

### 3. Enable unsafe scripts
Add to overlunky.ini in your Spelunky 2 folder:
```
unsafe_scripts=true
```

### 4. Install websocket library (optional)
```
pip install websocket-client
```

### 5. Launch
1. Open Modlunky2, Playlunky tab, check Crowd Control, click Play
2. The mod auto-launches bridge.py in a visible terminal
3. On first run, your browser opens for Twitch OAuth -- authorize and close the tab
4. The terminal shows connection status and effect triggers in real time

## Configuration (cc_config.txt)

Controls who can trigger what. Restart bridge.py after changes.

- EVERYBODY: any chatter can use (free, with cooldown)
- SUBSCRIBERS_ONLY: only subs, mods, and broadcaster
- POINTS_ONLY: requires Channel Point redemptions
- VOTE_SYSTEM: periodic polls, chat votes with !vote 1/2/3
- TRIGGER_COOLDOWN: global per-effect cooldown
- NO_EFFECT: disabled effects

Effects not in any list default to EVERYBODY. Broadcaster bypasses all cooldowns. Mods count as subscribers.

## Channel Points Setup
1. Twitch Creator Dashboard > Viewer Rewards > Channel Points > Custom Rewards
2. Name rewards to match effect codes (e.g. "steal_item", "randomize_item")
3. Set point costs per reward
4. Or use friendly names and map them in bridge.py REWARD_MAP

## Vote System
Polls auto-appear every POLL_TIMEOUT seconds. Each poll picks 2 random effects from VOTE_SYSTEM plus "No Effect." Viewers type !vote 1, !vote 2, or !vote 3. Winner triggers after POLL_LASTS seconds.

## Effects

BUFFS: !heal_player, !full_heal, !give_bombs, !give_ropes, !give_paste, !give_climbgloves, !give_spikeshoes, !give_springshoes, !give_kapala, !give_aliencompass, !give_elixir, !give_truecrown, !give_royaljelly, !give_jetpack, !give_vladscape, !give_cape, !give_shotgun, !give_freezeray, !give_teleporter, !give_scepter, !give_plasma

DEBUFFS: !hurt_player, !poison_player, !curse_player, !remove_bombs, !remove_ropes, !remove_helditem, !remove_backitem, !steal_item, !stun_player (3s), !giant_head (20s), !random_teleport, !randomize_item, !punish

ENEMIES: !spawn_snake, !spawn_spider, !spawn_bat, !spawn_skeleton, !spawn_hornedlizard, !spawn_caveman, !spawn_scorpion, !spawn_mantrap, !spawn_witchdoctor, !spawn_vampire, !spawn_ufo, !spawn_shopkeeper, !spawn_hiredhand, !spawn_vlad, !spawn_anubis2, !spawn_apep, !spawn_jellyfish, !spawn_olmec, !spawn_ghost, !anubis_coffin

HAZARDS: !spawn_arrowtrap, !spawn_tnt, !spawn_boulder, !spawn_lavapot, !spawn_kali_altar, !hadoken

LEVEL MODS: !speed_up (20s), !slow_motion (15s), !level_feeling [message], !force_dark, !force_outpost, !forgive_player

CHAOS: !kill_player, !enemy_rain, !bomb_rain, !explode_all, !destroy_altar

SPECIAL: !effects or !help (list commands), !vote 1/2/3 (vote in poll), !level_feeling your text here (custom message on screen)

## Testing

Browser:
  http://localhost:19030/trigger/spawn_snake/TestUser
  http://localhost:19030/trigger/level_feeling/TestUser/hello%20world

PowerShell:
  curl "http://localhost:19030/trigger/give_bombs/TestUser"

Access control test:
  curl "http://localhost:19030/chattest/give_kapala/TestUser/nosub"
  curl "http://localhost:19030/chattest/give_kapala/TestUser/sub"

Debug:
  http://localhost:19030/config (loaded config)
  http://localhost:19030/status (active poll state)

## Adding New Effects

1. Add handler in main.lua:
   fx.my_effect = function(r) --[[ code ]] return true end

2. Add to bridge.py EFFECTS:
   "my_effect": {"name": "My Effect"},

3. Add to appropriate list in cc_config.txt

## Troubleshooting

- Bridge won't start: taskkill /f /im python.exe, then relaunch
- Port in use: kill leftover bridge process
- Effects do nothing: player must be alive and in a level
- Entity errors: check ENT_TYPE names in Overlunky console (~)
- OAuth fails: redirect URL must be http://localhost:3000
- Subs not detected: IRC tags capability is auto-requested

## Credits
Created by gokumatrix.