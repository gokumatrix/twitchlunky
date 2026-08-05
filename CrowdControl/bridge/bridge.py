#!/usr/bin/env python3
"""
Spelunky 2 Twitch Crowd Control
  - Config-driven access control (cc_config.txt)
  - Subscriber detection via IRC tags
  - Voting/poll system for selected effects
  - Category-based cooldowns

Setup:
  1. Edit cc_config.txt to control who can trigger what
  2. OAuth token with scopes: channel:read:redemptions chat:read chat:edit
  3. pip install websocket-client (for channel points)
  4. python bridge.py
"""

import argparse, json, logging, os, random, re, socket, threading, time
from http.server import HTTPServer, BaseHTTPRequestHandler
import configparser
# ═══════════════════════════════════════════════════════════════
#  CONFIG FILE PARSER
# ═══════════════════════════════════════════════════════════════

def parse_time(val):
    """Parse '30s', '5m', '120s' etc into seconds."""
    val = val.strip().lower()
    if val.endswith("m"):
        return int(val[:-1]) * 60
    elif val.endswith("s"):
        return int(val[:-1])
    else:
        return int(val)

def parse_list(val):
    """Parse '["item1","item2"]' or 'item1,item2' into a list."""
    val = val.strip()
    # Remove brackets
    if val.startswith("["):
        val = val[1:]
    if val.endswith("]"):
        val = val[:-1]
    items = []
    for item in val.split(","):
        item = item.strip().strip('"').strip("'").strip("=")
        if item:
            items.append(item)
    return items

def load_config(path):
    """Load cc_config.txt and return a dict of settings."""
    conf = {
        "EVERYBODY": [],
        "EVERYBODY_TIMEOUT": 30,
        "SUBSCRIBERS_ONLY": [],
        "SUBSCRIBERS_TIMEOUT": 15,
        "POINTS_ONLY": [],
        "VOTE_SYSTEM": [],
        "POLL_LASTS": 120,
        "POLL_TIMEOUT": 300,
        "TRIGGER_COOLDOWN": [],
        "COOLDOWN_TIME": 10,
        "NO_EFFECT": [],
    }

    if not os.path.exists(path):
        log.warning("Config file '%s' not found, using defaults", path)
        return conf

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.split("#")[0].strip()  # strip inline comments

            if key in ("EVERYBODY", "SUBSCRIBERS_ONLY", "POINTS_ONLY",
                       "VOTE_SYSTEM", "TRIGGER_COOLDOWN", "NO_EFFECT"):
                conf[key] = parse_list(val)
            elif key in ("EVERYBODY_TIMEOUT", "SUBSCRIBERS_TIMEOUT",
                         "POLL_LASTS", "POLL_TIMEOUT", "COOLDOWN_TIME"):
                conf[key] = parse_time(val)

    log.info("Config loaded: %s", path)
    log.info("  EVERYBODY: %d effects, timeout %ds", len(conf["EVERYBODY"]), conf["EVERYBODY_TIMEOUT"])
    log.info("  SUBSCRIBERS_ONLY: %d effects, timeout %ds", len(conf["SUBSCRIBERS_ONLY"]), conf["SUBSCRIBERS_TIMEOUT"])
    log.info("  POINTS_ONLY: %d effects", len(conf["POINTS_ONLY"]))
    log.info("  VOTE_SYSTEM: %d effects, poll %ds, gap %ds", len(conf["VOTE_SYSTEM"]), conf["POLL_LASTS"], conf["POLL_TIMEOUT"])
    log.info("  TRIGGER_COOLDOWN: %d effects, %ds", len(conf["TRIGGER_COOLDOWN"]), conf["COOLDOWN_TIME"])
    log.info("  NO_EFFECT: %d disabled", len(conf["NO_EFFECT"]))
    return conf


# ═══════════════════════════════════════════════════════════════
#  CORE CONFIG
# ═══════════════════════════════════════════════════════════════

auth_config = configparser.ConfigParser()
auth_config.read("..\\auth.txt")
CHANNEL = auth_config['auth']['CHANNEL']
CLIENT_ID = auth_config['auth']['CLIENT_ID']
CLIENT_SECRET = auth_config['auth']['CLIENT_SECRET']
OAUTH = None
BOT_NAME = "CrowdControlBot"
HTTP_PORT = 19030
UDP_PORT = 19029
CONFIG_FILE = "..\\cc_config.txt"

REWARD_MAP = {
    # "Friendly Reward Title": "effect_code",
}

EFFECTS = {
    # Buffs
    "heal_player":       {"name": "Heal Player"},
    "full_heal":         {"name": "Full Heal"},
    # HUD items
    "give_bombs":        {"name": "Give Bombs x4"},
    "give_ropes":        {"name": "Give Ropes x4"},
    "give_paste":        {"name": "Paste"},
    "give_climbgloves":  {"name": "Climb Gloves"},
    "give_spikeshoes":   {"name": "Spike Shoes"},
    "give_springshoes":  {"name": "Spring Shoes"},
    "give_kapala":       {"name": "Kapala"},
    "give_aliencompass": {"name": "Alien Compass"},
    "give_elixir":       {"name": "Elixir"},
    "give_truecrown":    {"name": "True Crown"},
    "give_royaljelly":   {"name": "Royal Jelly"},
    # Back items
    "give_jetpack":      {"name": "Jetpack"},
    "give_vladscape":    {"name": "Vlad's Cape"},
    "give_cape":         {"name": "Cape"},
    # Held items
    "give_shotgun":      {"name": "Shotgun"},
    "give_freezeray":    {"name": "Freeze Ray"},
    "give_teleporter":   {"name": "Teleporter"},
    "give_scepter":      {"name": "Scepter"},
    "give_plasma":       {"name": "Plasma Cannon"},
    # Debuffs
    "hurt_player":       {"name": "Damage Player"},
    "poison_player":     {"name": "Poison"},
    "curse_player":      {"name": "Curse"},
    "remove_bombs":      {"name": "Remove Bombs"},
    "remove_ropes":      {"name": "Remove Ropes"},
    "remove_helditem":   {"name": "Yoink Item"},
    "remove_backitem":   {"name": "Strip Back Item"},
    "stun_player":       {"name": "Stun", "duration": 3},
    "giant_head":        {"name": "Giant Head", "duration": 20},
    "random_teleport":   {"name": "Random TP"},
    "steal_item":        {"name": "Steal Item"},
    "punish":            {"name": "Ball and Chain"},
    # Spawn enemies
    "spawn_snake":       {"name": "Snake"},
    "spawn_spider":      {"name": "Spider"},
    "spawn_bat":         {"name": "Bat"},
    "spawn_skeleton":    {"name": "Skeleton"},
    "spawn_hornedlizard":{"name": "Horned Lizard"},
    "spawn_caveman":     {"name": "Caveman"},
    "spawn_scorpion":    {"name": "Scorpion"},
    "spawn_mantrap":     {"name": "Mantrap"},
    "spawn_witchdoctor": {"name": "Witch Doctor"},
    "spawn_vampire":     {"name": "Vampire"},
    "spawn_ufo":         {"name": "UFO"},
    "spawn_shopkeeper":  {"name": "Shopkeeper"},
    "spawn_hiredhand":   {"name": "Hired Hand"},
    "spawn_vlad":        {"name": "Vlad"},
    "spawn_anubis2":     {"name": "Anubis II"},
    "spawn_apep":        {"name": "Apep"},
    "spawn_jellyfish":   {"name": "Mega Jellyfish"},
    "spawn_olmec":       {"name": "Olmec"},
    "spawn_ghost":       {"name": "Ghost"},
    "anubis_coffin":     {"name": "Anubis Coffin"},
    # Hazards
    "spawn_arrowtrap":   {"name": "Arrow Trap"},
    "spawn_tnt":         {"name": "Powder Keg"},
    "spawn_boulder":     {"name": "Boulder"},
    "spawn_lavapot":     {"name": "Lava Pot"},
    "spawn_kali_altar":  {"name": "Spawn Altar"},
    "hadoken":           {"name": "Plasma Shot"},
    # Level mods
    "speed_up":          {"name": "Speed Up", "duration": 20},
    "slow_motion":       {"name": "Slow Motion", "duration": 15},
    "level_feeling":     {"name": "Level Feeling"},
    "force_dark":        {"name": "Force Dark Level"},
    "force_outpost":     {"name": "Force Outpost"},
    "forgive_player":    {"name": "Forgive Player"},
    # Chaos
    "kill_player":       {"name": "Kill Player"},
    "enemy_rain":        {"name": "Enemy Rain", "duration": 3},
    "bomb_rain":         {"name": "Bomb Rain", "duration": 1},
    "explode_all":       {"name": "Everybody Explodes"},
    "randomize_item":    {"name": "Randomize Item"},
    "destroy_altar":     {"name": "Destroy Altar"},
}

# ═══════════════════════════════════════════════════════════════

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("cc")

pending, plock = [], threading.Lock()
last_user = {}          # per-user last trigger time
last_trigger = {}       # per-effect last trigger time (for TRIGGER_COOLDOWN)
next_id, id_lock = 0, threading.Lock()
irc_ref = None
conf = {}               # loaded from config file

def get_id():
    global next_id
    with id_lock: next_id += 1; return next_id

def resolve(title):
    if title in REWARD_MAP: return REWARD_MAP[title]
    low = title.lower().strip().replace(" ", "_")
    if low in EFFECTS: return low
    return None

def queue(code, user, src="chat", text=""):
    e = EFFECTS[code]
    eid = get_id()
    dur = e.get("duration", 0)
    if callable(dur): dur = dur()
    with plock:
        pending.append({"id":eid,"code":code,"viewer":user,"duration":dur,
                         "type":"timed" if dur>0 else "instant","text":text})
    log.info("[%s] %s -> %s (id=%d)", src, user, code, eid)
    return eid

def get_category(cmd):
    """Return which config category an effect belongs to."""
    if cmd in conf.get("NO_EFFECT", []):
        return "disabled"
    if cmd in conf.get("VOTE_SYSTEM", []):
        return "vote"
    if cmd in conf.get("POINTS_ONLY", []):
        return "points"
    if cmd in conf.get("SUBSCRIBERS_ONLY", []):
        return "subs"
    if cmd in conf.get("EVERYBODY", []):
        return "everybody"
    # Not in any config list — allow for everybody by default
    return "everybody"

def get_cooldown_for_category(category):
    """Return the cooldown in seconds for a category."""
    if category == "everybody":
        return conf.get("EVERYBODY_TIMEOUT", 30)
    elif category == "subs":
        return conf.get("SUBSCRIBERS_TIMEOUT", 15)
    return 0


# ═══════════════════════════════════════════════════════════════
#  VOTE / POLL SYSTEM
# ═══════════════════════════════════════════════════════════════

class PollSystem:
    def __init__(self, effects_list, poll_duration, poll_gap, irc_fn):
        self.effects_list = effects_list
        self.poll_duration = poll_duration
        self.poll_gap = poll_gap
        self.irc_fn = irc_fn  # function to send chat messages

        self.active = False
        self.options = []       # list of effect codes (+ "no_effect")
        self.votes = {}         # user -> option index
        self.poll_end = 0
        self.last_poll_ended = 0

    def can_start_new_poll(self):
        if self.active:
            return False
        if not self.effects_list:
            return False
        return time.time() - self.last_poll_ended >= self.poll_gap

    def start_poll(self):
        if len(self.effects_list) < 2:
            return
        # Pick 2 random effects + "No effect"
        picks = random.sample(self.effects_list, min(2, len(self.effects_list)))
        self.options = picks + ["no_effect"]
        self.votes = {}
        self.active = True
        self.poll_end = time.time() + self.poll_duration

        lines = ["📊 VOTE NOW! Type !vote 1, !vote 2, or !vote 3:"]
        for i, opt in enumerate(self.options):
            if opt == "no_effect":
                name = "No Effect"
            else:
                name = EFFECTS.get(opt, {}).get("name", opt)
            lines.append(f"  {i+1}. {name}")
        lines.append(f"⏱ Voting ends in {self.poll_duration}s!")

        self.irc_fn(" | ".join(lines))
        log.info("Poll started: %s", self.options)

    def handle_vote(self, user, msg):
        """Returns True if the message was a vote command."""
        if not self.active:
            return False
        parts = msg.strip().split()
        if len(parts) < 2 or parts[0].lower() != "!vote":
            return False
        try:
            choice = int(parts[1])
        except ValueError:
            return True  # was a !vote but invalid number

        if choice < 1 or choice > len(self.options):
            self.irc_fn(f"@{user} Pick 1-{len(self.options)}!")
            return True

        old = self.votes.get(user)
        self.votes[user] = choice - 1
        if old is not None:
            self.irc_fn(f"@{user} Changed vote to {choice}!")
        else:
            self.irc_fn(f"@{user} Voted for {choice}!")
        return True

    def check_end(self):
        """Check if the poll should end. Returns winning effect code or None."""
        if not self.active:
            return None
        if time.time() < self.poll_end:
            return None

        # Tally votes
        tallies = [0] * len(self.options)
        for idx in self.votes.values():
            if 0 <= idx < len(tallies):
                tallies[idx] += 1

        max_votes = max(tallies)
        if max_votes == 0:
            self.irc_fn("📊 Poll ended — no votes cast!")
            self.active = False
            self.last_poll_ended = time.time()
            return None

        # Find winner (random tiebreak)
        winners = [i for i, v in enumerate(tallies) if v == max_votes]
        winner_idx = random.choice(winners)
        winner_code = self.options[winner_idx]
        winner_name = "No Effect" if winner_code == "no_effect" else EFFECTS.get(winner_code, {}).get("name", winner_code)

        # Announce results
        results = []
        for i, opt in enumerate(self.options):
            name = "No Effect" if opt == "no_effect" else EFFECTS.get(opt, {}).get("name", opt)
            marker = " 👑" if i == winner_idx else ""
            results.append(f"{name}: {tallies[i]}{marker}")

        self.irc_fn(f"📊 Poll results: {' | '.join(results)} — {winner_name} wins!")

        self.active = False
        self.last_poll_ended = time.time()

        if winner_code == "no_effect":
            return None
        return winner_code

poll_system = None


def poll_loop():
    """Background thread that manages poll lifecycle."""
    global poll_system
    while True:
        time.sleep(5)
        if not poll_system:
            continue

        # Check if current poll ended
        winner = poll_system.check_end()
        if winner:
            queue(winner, "Chat Vote", "vote")

        # Start new poll if enough time has passed
        if poll_system.can_start_new_poll():
            poll_system.start_poll()


# ═══════════════════════════════════════════════════════════════
#  OAUTH
# ═══════════════════════════════════════════════════════════════

def get_oauth_token(client_id, client_secret):
    import webbrowser
    from urllib.parse import urlparse, parse_qs
    import urllib.request

    auth_code = [None]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            params = parse_qs(urlparse(self.path).query)
            if "code" in params:
                auth_code[0] = params["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<h1>Done! Close this tab and go back to the game.</h1>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No code received")
        def log_message(self, *a): pass

    scopes = "channel:read:redemptions+chat:read+chat:edit"
    url = (f"https://id.twitch.tv/oauth2/authorize?client_id={client_id}"
           f"&redirect_uri=http://localhost:3000"
           f"&response_type=code&scope={scopes}")

    srv = HTTPServer(("localhost", 3000), Handler)
    print("Opening browser for Twitch login...")
    webbrowser.open(url)
    srv.handle_request()
    srv.server_close()

    if not auth_code[0]:
        print("ERROR: No auth code received")
        return None

    body = (f"client_id={client_id}&client_secret={client_secret}"
            f"&code={auth_code[0]}&grant_type=authorization_code"
            f"&redirect_uri=http://localhost:3000").encode()
    req = urllib.request.Request("https://id.twitch.tv/oauth2/token",
                                 data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        resp = json.loads(urllib.request.urlopen(req).read())
    except Exception as e:
        print(f"Token error: {e}")
        return None
    token = resp["access_token"]
    print(f"Token acquired! Expires in {resp.get('expires_in',0)//3600}h")
    return f"oauth:{token}"


# ═══════════════════════════════════════════════════════════════
#  HTTP SERVER
# ═══════════════════════════════════════════════════════════════

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_POST(self):
        if self.path == "/test":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode() if length else ""
            msg = json.loads(body)
            with plock: pending.append(msg)
            log.info("TEST: %s", body[:300])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Queued")
        else:
            self.send_response(404)
            self.end_headers()
    def do_GET(self):
        if self.path=="/poll":
            with plock:
                d=json.dumps(pending); pending.clear()
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.end_headers(); self.wfile.write(d.encode())
        elif self.path.startswith("/trigger/"):
            parts = self.path.split("/")
            if len(parts) >= 3 and parts[2] in EFFECTS:
                code = parts[2]
                viewer = parts[3] if len(parts) >= 4 else "Manual"
                text = "/".join(parts[4:]) if len(parts) >= 5 else ""
                text = text.replace("%20", " ").replace("+", " ")
                queue(code, viewer, "manual", text)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(f"Queued: {code}".encode())
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Unknown effect")
        elif self.path == "/config":
            # Show current config for debugging
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(conf, indent=2).encode())
        elif self.path == "/status":
            status = {
                "poll_active": poll_system.active if poll_system else False,
                "poll_options": poll_system.options if poll_system and poll_system.active else [],
                "poll_votes": len(poll_system.votes) if poll_system and poll_system.active else 0,
                "poll_time_left": max(0, int(poll_system.poll_end - time.time())) if poll_system and poll_system.active else 0,
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status, indent=2).encode())
        else:
            self.send_response(404)
            self.end_headers()


# ═══════════════════════════════════════════════════════════════
#  UDP
# ═══════════════════════════════════════════════════════════════

def udp_loop():
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.bind(("0.0.0.0",UDP_PORT)); s.settimeout(1)
    while True:
        try:
            d,_=s.recvfrom(4096); m=json.loads(d.decode().strip())
            log.info("Game: id=%s status=%s",m.get("id"),m.get("status"))
        except socket.timeout: pass
        except: pass


# ═══════════════════════════════════════════════════════════════
#  IRC (with subscriber detection + config-based access)
# ═══════════════════════════════════════════════════════════════

class IRC:
    def __init__(self, ch, oauth, name):
        self.ch = ch.lower().lstrip("#")
        self.oauth = oauth
        self.name = name
        self.sock = None

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect(("irc.chat.twitch.tv", 6667))
        self.sock.settimeout(1)
        for m in [f"PASS {self.oauth}", f"NICK {self.name}", f"JOIN #{self.ch}",
                   "CAP REQ :twitch.tv/tags twitch.tv/commands"]:
            self.sock.sendall((m + "\r\n").encode())
        log.info("IRC: #%s", self.ch)

    def say(self, msg):
        try:
            self.sock.sendall(f"PRIVMSG #{self.ch} :{msg}\r\n".encode())
        except:
            pass

    def parse_tags(self, tags_str):
        """Parse IRC tags into a dict."""
        tags = {}
        if not tags_str:
            return tags
        for part in tags_str.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                tags[k] = v
        return tags

    def is_subscriber(self, tags):
        """Check if user is a subscriber from IRC tags."""
        return tags.get("subscriber", "0") == "1"

    def is_mod(self, tags):
        """Check if user is a moderator from IRC tags."""
        return tags.get("mod", "0") == "1"

    def is_broadcaster(self, tags, user):
        """Check if user is the broadcaster."""
        badges = tags.get("badges", "")
        return "broadcaster" in badges or user.lower() == self.ch.lower()

    def run(self):
        buf = ""
        while True:
            try:
                d = self.sock.recv(4096)
                if not d:
                    time.sleep(5)
                    self.connect()
                    continue
                buf += d.decode("utf-8", "replace")
                while "\r\n" in buf:
                    line, buf = buf.split("\r\n", 1)
                    if line.startswith("PING"):
                        self.sock.sendall(("PONG" + line[4:] + "\r\n").encode())
                        continue

                    # Parse with tags
                    m = re.match(r"(?:@(\S+)\s+)?:(\w+)!\S+\s+PRIVMSG\s+#\w+\s+:(.*)", line)
                    if not m:
                        continue

                    tags_str, user, msg = m.groups()
                    msg = msg.strip()
                    tags = self.parse_tags(tags_str)

                    if not msg.startswith("!"):
                        continue

                    # Handle votes first
                    if poll_system and poll_system.handle_vote(user, msg):
                        continue

                    parts = msg.split(None, 1)
                    cmd = parts[0][1:].lower()
                    cmd_text = parts[1] if len(parts) > 1 else ""

                    # Help command
                    if cmd in ("effects", "help"):
                        categories = []
                        if conf.get("EVERYBODY"):
                            categories.append("Everyone: " + ", ".join(f"!{e}" for e in conf["EVERYBODY"][:10]))
                        if conf.get("SUBSCRIBERS_ONLY"):
                            categories.append("Subs: " + ", ".join(f"!{e}" for e in conf["SUBSCRIBERS_ONLY"][:10]))
                        if conf.get("POINTS_ONLY"):
                            categories.append("Points: " + ", ".join(f"!{e}" for e in conf["POINTS_ONLY"][:10]))
                        if conf.get("VOTE_SYSTEM"):
                            categories.append("Vote: " + ", ".join(f"{e}" for e in conf["VOTE_SYSTEM"][:10]))
                        self.say(" | ".join(categories) if categories else
                                 "Effects: " + ", ".join(f"!{k}" for k in sorted(EFFECTS.keys())))
                        continue

                    # Must be a known effect
                    if cmd not in EFFECTS:
                        continue

                    # Check category
                    category = get_category(cmd)

                    # Disabled
                    if category == "disabled":
                        continue  # silently ignore

                    # Vote-only effects can't be triggered directly
                    if category == "vote":
                        self.say(f"@{user} That effect is vote-only! Wait for a poll.")
                        continue

                    # Points-only
                    if category == "points":
                        self.say(f"@{user} That's a Channel Points reward!")
                        continue

                    # Subscriber check
                    is_sub = self.is_subscriber(tags)
                    is_privileged = (is_sub or self.is_mod(tags) or
                                    self.is_broadcaster(tags, user))

                    if category == "subs" and not is_privileged:
                        self.say(f"@{user} That effect is for subscribers only!")
                        continue

                    # Broadcaster/streamer bypass all cooldowns
                    if not self.is_broadcaster(tags, user):
                        # Per-effect trigger cooldown
                        if cmd in conf.get("TRIGGER_COOLDOWN", []):
                            cooldown_time = conf.get("COOLDOWN_TIME", 10)
                            last = last_trigger.get(cmd, 0)
                            if time.time() - last < cooldown_time:
                                remaining = cooldown_time - (time.time() - last)
                                self.say(f"@{user} {EFFECTS[cmd]['name']} on cooldown! {remaining:.0f}s")
                                continue

                        # Per-user category cooldown
                        cat_cooldown = get_cooldown_for_category(category)
                        user_key = f"{user}:{category}"
                        last = last_user.get(user_key, 0)
                        if time.time() - last < cat_cooldown:
                            remaining = cat_cooldown - (time.time() - last)
                            self.say(f"@{user} Cooldown! {remaining:.0f}s")
                            continue

                    # All checks passed — queue it
                    queue(cmd, user, "chat", cmd_text)
                    last_user[f"{user}:{category}"] = time.time()
                    if cmd in conf.get("TRIGGER_COOLDOWN", []):
                        last_trigger[cmd] = time.time()
                    self.say(f"@{user} triggered {EFFECTS[cmd]['name']}!")

            except socket.timeout:
                continue
            except Exception as e:
                log.error("IRC: %s", e)
                time.sleep(5)
                try:
                    self.connect()
                except:
                    pass


# ═══════════════════════════════════════════════════════════════
#  PUBSUB (Channel Points)
# ═══════════════════════════════════════════════════════════════

class PubSub:
    def __init__(self, oauth, chan_id, on_redeem):
        self.token = oauth.replace("oauth:", "")
        self.cid = chan_id
        self.on_redeem = on_redeem
        self.ws = None
    def connect(self):
        import websocket
        self.ws = websocket.WebSocket()
        self.ws.connect("wss://pubsub-edge.twitch.tv")
        self.ws.send(json.dumps({"type": "LISTEN", "data": {
            "topics": [f"channel-points-channel-v1.{self.cid}"],
            "auth_token": self.token}}))
        log.info("PubSub: listening for channel point redemptions")
    def run(self):
        while True:
            try:
                if not self.ws: self.connect()
                self.ws.settimeout(60)
                raw = self.ws.recv()
                if not raw: continue
                msg = json.loads(raw)
                if msg.get("type") == "RECONNECT":
                    self.ws.close(); self.ws = None; time.sleep(2); continue
                if msg.get("type") == "RESPONSE" and msg.get("error"):
                    log.error("PubSub: %s", msg["error"]); continue
                if msg.get("type") == "MESSAGE":
                    inner = json.loads(msg["data"]["message"])
                    if inner.get("type") == "reward-redeemed":
                        r = inner["data"]["redemption"]
                        self.on_redeem(
                            r["user"]["display_name"],
                            r["reward"]["title"],
                            r["reward"]["cost"])
            except Exception as e:
                if "timed out" in str(e):
                    try: self.ws.send(json.dumps({"type": "PING"}))
                    except: self.ws = None
                    continue
                log.error("PubSub: %s", e); self.ws = None; time.sleep(5)
    def ping_loop(self):
        while True:
            time.sleep(240)
            try:
                if self.ws: self.ws.send(json.dumps({"type": "PING"}))
            except: pass


def on_redeem(user, title, cost):
    code = resolve(title)
    if not code:
        log.warning("Unknown reward '%s'", title)
        return
    category = get_category(code)
    # Points-only and everybody effects can be redeemed via points
    # Vote-only and disabled cannot
    if category == "disabled":
        return
    if category == "vote":
        log.warning("'%s' is vote-only, skipping point redemption", code)
        return
    queue(code, user, f"points:{cost}")
    if irc_ref:
        irc_ref.say(f"@{user} redeemed {EFFECTS[code]['name']} ({cost} pts)!")


def get_channel_id(oauth):
    import urllib.request
    token = oauth.replace("oauth:", "")
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            "https://id.twitch.tv/oauth2/validate",
            headers={"Authorization": f"OAuth {token}"}))
        cid = json.loads(r.read()).get("client_id", "")
    except:
        return None
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            "https://api.twitch.tv/helix/users",
            headers={"Authorization": f"Bearer {token}", "Client-Id": cid}))
        d = json.loads(r.read())["data"][0]
        log.info("Channel: %s (id: %s)", d["login"], d["id"])
        return d["id"]
    except Exception as e:
        log.warning("Could not get channel ID: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    global irc_ref, conf, poll_system

    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=CHANNEL)
    ap.add_argument("--oauth", default=OAUTH)
    ap.add_argument("--http-port", type=int, default=HTTP_PORT)
    ap.add_argument("--udp-port", type=int, default=UDP_PORT)
    ap.add_argument("--config", default=CONFIG_FILE)
    ap.add_argument("--no-chat", action="store_true")
    ap.add_argument("--no-points", action="store_true")
    ap.add_argument("--no-polls", action="store_true")
    a = ap.parse_args()

    # Load config
    # Try config file next to the script first, then current directory
    config_path = a.config
    if not os.path.exists(config_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, a.config)
    conf = load_config(config_path)

    # HTTP + UDP
    threading.Thread(target=HTTPServer(("0.0.0.0", a.http_port), H).serve_forever, daemon=True).start()
    threading.Thread(target=udp_loop, daemon=True).start()

    # OAuth
    if not a.oauth or a.oauth == "oauth:your_token_here" or a.oauth is None:
        a.oauth = get_oauth_token(CLIENT_ID, CLIENT_SECRET)
        if not a.oauth:
            print("Failed to get token. Exiting.")
            return

    # IRC
    if not a.no_chat:
        irc_ref = IRC(a.channel, a.oauth, BOT_NAME)
        irc_ref.connect()
        threading.Thread(target=irc_ref.run, daemon=True).start()

    # Poll system
    if not a.no_polls and conf.get("VOTE_SYSTEM"):
        def say_fn(msg):
            if irc_ref: irc_ref.say(msg)
        poll_system = PollSystem(
            conf["VOTE_SYSTEM"],
            conf.get("POLL_LASTS", 120),
            conf.get("POLL_TIMEOUT", 300),
            say_fn,
        )
        threading.Thread(target=poll_loop, daemon=True).start()
        log.info("Poll system active: %d effects, %ds polls, %ds gap",
                 len(conf["VOTE_SYSTEM"]), conf["POLL_LASTS"], conf["POLL_TIMEOUT"])

    # PubSub
    if not a.no_points:
        cid = get_channel_id(a.oauth)
        if cid:
            try:
                import websocket
                ps = PubSub(a.oauth, cid, on_redeem)
                threading.Thread(target=ps.run, daemon=True).start()
                threading.Thread(target=ps.ping_loop, daemon=True).start()
            except ImportError:
                log.warning("pip install websocket-client  (for channel points)")

    print(f"\n  Spelunky 2 CC — #{a.channel}")
    print(f"  Chat: {'ON' if not a.no_chat else 'OFF'}  Points: {'ON' if not a.no_points else 'OFF'}  Polls: {'ON' if not a.no_polls and conf.get('VOTE_SYSTEM') else 'OFF'}")
    print(f"  Config: {config_path}")
    print(f"  Game polls: localhost:{a.http_port}/poll")
    print(f"  Debug: localhost:{a.http_port}/config  localhost:{a.http_port}/status\n")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()