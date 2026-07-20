--[[
  Spelunky 2 Crowd Control Playlunky Script Mod
  Drop this folder into Mods/Packs/CrowdControl/
  Toggle on in Modlunky2 Playlunky tab Play.
]]

meta = {
    name        = "Crowd Control",
    version     = "1.0.0",
    author      = "CrowdControl Community",
    description = "Twitch viewers control the game via chat",
    unsafe      = true,
}

local POLL_URL       = "http://127.0.0.1:19030/poll"  -- HTTP poll for effects
local RESP_HOST      = "127.0.0.1"
local RESP_PORT      = 19029   -- udp_send responses back to bridge
local ANN_DUR        = 3.0
local POLL_INTERVAL  = 6       -- poll every N frames (~10Hz at 60fps)

local timed_fx, anns = {}, {}
local bridge_pid = nil
local poll_counter = 0
local effect_queue = {}

local spawn_pos = nil
local safe_to_spawn_above = false

-- ── AUTO-LAUNCH BRIDGE ─────────────────────────────────────
local function find_bridge()
    local dirs = {
        "Mods/Packs/CrowdControl/bridge/",
        "Mods\\Packs\\CrowdControl\\bridge\\",
        "bridge/",
    }
    for _, d in ipairs(dirs) do
        for _, name in ipairs({"bridge.exe", "bridge.py"}) do
            local f = io.open(d .. name, "r")
            if f then f:close(); return d .. name, name:match("%.py$") end
        end
    end
    return nil, false
end

local function launch_bridge()
    if bridge_pid then return end
    local path, is_py = find_bridge()
    if not path then
        print("[CC] bridge.exe/bridge.py not found — start bridge manually.")
        return
    end
    if is_py then
        print("[CC] Launching bridge via Python: " .. path)
        os.execute('start "Spelunky 2 Crowd Control" python "' .. path .. '"')
    else
        print("[CC] Launching bridge: " .. path)
        os.execute('start "Spelunky 2 Crowd Control" "' .. path .. '"')
    end
    bridge_pid = true
end

local function stop_bridge()
    if not bridge_pid then return end
    os.execute('taskkill /f /im bridge.exe >nul 2>&1')
    bridge_pid = nil
    print("[CC] Bridge stopped.")
end

-- ── JSON ────────────────────────────────────────────────────
local function jdec(s)
    if not s or s == "" then return nil end
    local o = {}
    for k, v in s:gmatch('"([^"]+)"%s*:%s*"([^"]*)"') do o[k] = v end
    for k, v in s:gmatch('"([^"]+)"%s*:%s*(%d+%.?%d*)') do o[k] = tonumber(v) end
    for k, v in s:gmatch('"([^"]+)"%s*:%s*(true)') do o[k] = true end
    for k, v in s:gmatch('"([^"]+)"%s*:%s*(false)') do o[k] = false end
    return next(o) and o or nil
end

local function jenc(t)
    local p = {}
    for k,v in pairs(t) do
        local s = type(v)=="string" and ('"'..v..'"') or type(v)=="number" and tostring(v) or type(v)=="boolean" and (v and "true" or "false") or "null"
        p[#p+1] = '"'..k..'":'..s
    end
    return "{"..table.concat(p, ",").."}"
end

-- ── HELPERS ─────────────────────────────────────────────────
local function P() local p=players; return p and #p>0 and p[1] or nil end
local function IL() local s=state.screen; return s==SCREEN.LEVEL or s==SCREEN.CAMP end

local function snp(et, ox, oy)
    local p=P(); if not p then return nil end
    -- Check distance from level entrance
    if spawn_pos and not safe_to_spawn_above then
        local dx = math.abs(p.x - spawn_pos.x)
        local dy = math.abs(p.y - spawn_pos.y)
        if dx + dy >= 3 then
            safe_to_spawn_above = true
        end
    end
    -- Clamp vertical offset if still near spawn
    if not safe_to_spawn_above and oy and oy > 0 then
        oy = 0
    end
    return spawn(et, p.x+(ox or 2), p.y+(oy or 0), p.layer, 0, 0)
end

local function resp(id, st) udp_send(RESP_HOST, RESP_PORT, jenc({id=id, status=st})) end

local function ann(viewer, code)
    anns[#anns+1] = {text=viewer.." triggered: "..code, expire=get_frame()+math.floor(ANN_DUR*60)}
    message(viewer.." triggered: "..code)
end

local function reg_timed(id, code, dur, cleanup)
    timed_fx[#timed_fx+1] = {id=id, code=code, end_frame=get_frame()+math.floor(dur*60), fn=cleanup}
    resp(id, "timedBegin")
end

local function tick_timed()
    local now, keep = get_frame(), {}
    for _, t in ipairs(timed_fx) do
        if now >= t.end_frame then
            if t.fn then pcall(t.fn) end; resp(t.id, "timedEnd")
        else keep[#keep+1] = t end
    end
    timed_fx = keep
end

local function drop_held(p)
    if p.holding_uid and p.holding_uid > 0 then
        drop(p.uid, p.holding_uid)
    end
end

local function silent_remove_held(p)
    if not p.holding_uid or p.holding_uid <= 0 then return end
    local held = p.holding_uid
    p.holding_uid = -1
    local e = get_entity(held)
    e.flags = set_flag(e.flags, 1)
    move_entity(held, 0, -1000, 0, 0)
end

-- ── ENTITY IDS ──────────────────────────────────────────────
local E = {
    snake=ENT_TYPE.MONS_SNAKE, spider=ENT_TYPE.MONS_SPIDER, bat=ENT_TYPE.MONS_BAT,
    skeleton=ENT_TYPE.MONS_SKELETON, hornedlizard=ENT_TYPE.MONS_HORNEDLIZARD,
    caveman=ENT_TYPE.MONS_CAVEMAN, scorpion=ENT_TYPE.MONS_SCORPION,
    mantrap=ENT_TYPE.MONS_MANTRAP, witchdoctor=ENT_TYPE.MONS_WITCHDOCTOR,
    vampire=ENT_TYPE.MONS_VAMPIRE, ufo=ENT_TYPE.MONS_UFO,
    shopkeeper=ENT_TYPE.MONS_SHOPKEEPER, hiredhand=ENT_TYPE.CHAR_HIREDHAND,
    jetpack=ENT_TYPE.ITEM_JETPACK, shotgun=ENT_TYPE.ITEM_SHOTGUN,
    freezeray=ENT_TYPE.ITEM_FREEZERAY, cape=ENT_TYPE.ITEM_CAPE,
    teleporter=ENT_TYPE.ITEM_TELEPORTER, arrowtrap=ENT_TYPE.FLOOR_ARROW_TRAP,
    tnt=ENT_TYPE.ACTIVEFLOOR_POWDERKEG, boulder=ENT_TYPE.ACTIVEFLOOR_BOULDER,
    ghost=ENT_TYPE.MONS_GHOST, olmec=ENT_TYPE.ACTIVEFLOOR_OLMEC,
    vlad=ENT_TYPE.MONS_VLAD, vladscape=ENT_TYPE.ITEM_VLADS_CAPE,
    scepter=ENT_TYPE.ITEM_SCEPTER, plasma=ENT_TYPE.ITEM_PLASMACANNON
}

-- ── EFFECTS ─────────────────────────────────────────────────
local fx = {}

-- Buffs
fx.heal_player     = function(r) local p=P(); if not p then return false end; p.health=p.health+1; return true end
fx.full_heal       = function(r) local p=P(); if not p then return false end; p.health=99; return true end

-- HUD items
fx.give_bombs      = function(r) local p=P(); if not p then return false end; p.inventory.bombs=p.inventory.bombs+4; return true end
fx.give_ropes      = function(r) local p=P(); if not p then return false end; p.inventory.ropes=p.inventory.ropes+4; return true end
fx.give_paste      = function(r) local p=P(); if not p then return false end; return spawn_entity_over(ENT_TYPE.ITEM_PICKUP_PASTE,p.uid,0,0)~=nil end
fx.give_climbgloves= function(r) local p=P(); if not p then return false end; return spawn_entity_over(ENT_TYPE.ITEM_PICKUP_CLIMBINGGLOVES,p.uid,0,0)~=nil end
fx.give_spikeshoes = function(r) local p=P(); if not p then return false end; return spawn_entity_over(ENT_TYPE.ITEM_PICKUP_SPIKESHOES,p.uid,0,0)~=nil end
fx.give_springshoes= function(r) local p=P(); if not p then return false end; return spawn_entity_over(ENT_TYPE.ITEM_PICKUP_SPRINGSHOES,p.uid,0,0)~=nil end
fx.give_kapala     = function(r) local p=P(); if not p then return false end; return spawn_entity_over(ENT_TYPE.ITEM_PICKUP_KAPALA,p.uid,0,0)~=nil end
fx.give_aliencompass     = function(r) local p=P(); if not p then return false end; return spawn_entity_over(ENT_TYPE.ITEM_PICKUP_SPECIALCOMPASS,p.uid,0,0)~=nil end
fx.give_elixir     = function(r) local p=P(); if not p then return false end; return spawn_entity_over(ENT_TYPE.ITEM_PICKUP_ELIXIR,p.uid,0,0)~=nil end
fx.give_truecrown     = function(r) local p=P(); if not p then return false end; return spawn_entity_over(ENT_TYPE.ITEM_PICKUP_TRUECROWN,p.uid,0,0)~=nil end
fx.give_royaljelly     = function(r) local p=P(); if not p then return false end; return spawn_entity_over(ENT_TYPE.ITEM_PICKUP_ROYALJELLY,p.uid,0,0)~=nil end

-- Back Items
fx.give_jetpack    = function(r) local p=P(); if not p then return false end; local u=spawn_entity_over(E.jetpack,p.uid,0,0.5); if u then pick_up(p.uid,u) end; return u~=nil end
fx.give_vladscape    = function(r) local p=P(); if not p then return false end; local u=spawn_entity_over(E.vladscape,p.uid,0,0.5); if u then pick_up(p.uid,u) end; return u~=nil end
fx.give_cape       = function(r) local p=P(); if not p then return false end; local u=spawn_entity_over(E.cape,p.uid,0,0.5); if u then pick_up(p.uid,u) end; return u~=nil end

-- Items
fx.give_shotgun    = function(r) local p=P(); if not p then return false end; drop_held(p); local u=spawn_entity_over(E.shotgun,p.uid,0,0); if u then pick_up(p.uid,u) end; return u~=nil end
fx.give_freezeray  = function(r) local p=P(); if not p then return false end; drop_held(p); local u=spawn_entity_over(E.freezeray,p.uid,0,0); if u then pick_up(p.uid,u) end; return u~=nil end
fx.give_teleporter = function(r) local p=P(); if not p then return false end; drop_held(p); local u=spawn_entity_over(E.teleporter,p.uid,0,0); if u then pick_up(p.uid,u) end; return u~=nil end
fx.give_scepter = function(r) local p=P(); if not p then return false end; drop_held(p); local u=spawn_entity_over(E.scepter,p.uid,0,0); if u then pick_up(p.uid,u) end; return u~=nil end
fx.give_plasma = function(r) local p=P(); if not p then return false end; drop_held(p); local u=spawn_entity_over(E.plasma,p.uid,0,0); if u then pick_up(p.uid,u) end; return u~=nil end

-- Debuffs
fx.hurt_player     = function(r) local p=P(); if not p or p.health<=0 then return false end; p.health=math.max(p.health-1,1); p.stun_timer=30; return true end
fx.poison_player   = function(r) local p=P(); if not p then return false end; poison_entity(p.uid); return true end
fx.curse_player    = function(r) local p=P(); if not p then return false end; p.more_flags=set_flag(p.more_flags, 15); p.health=1 return true end
fx.remove_bombs    = function(r) local p=P(); if not p or p.inventory.bombs<=0 then return false end; p.inventory.bombs=0; return true end
fx.remove_ropes    = function(r) local p=P(); if not p or p.inventory.ropes<=0 then return false end; p.inventory.ropes=0; return true end
fx.remove_helditem = function(r) local p=P(); if not p or not p.holding_uid or p.holding_uid<=0 then return false end; drop(p.uid,p.holding_uid); kill_entity(p.holding_uid); return true end
fx.remove_backitem = function(r) local p=P(); if not p then return false end; local b=worn_backitem(p.uid); if b==-1 then return false end; unequip_backitem(p.uid); kill_entity(b); return true end
fx.stun_player     = function(r) local p=P(); if not p then return false end; p.stun_timer=r.duration*60; reg_timed(r.id,r.code,r.duration,function() local q=P(); if q then q.stun_timer=0 end end); return "timed" end
fx.giant_head      = function(r) local p=P(); if not p then return false end; local ow,oh=p.width,p.height; p.width,p.height=ow*2.5,oh*2.5; reg_timed(r.id,r.code,r.duration,function() local q=P(); if q then q.width,q.height=ow,oh end end); return "timed" end
fx.random_teleport = function(r) local p=P(); if not p then return false end; local x,y=get_position(p.uid); move_entity(p.uid,x+math.random(-8,8),y+math.random(-4,4),0,0); return true end
local protected_items = {
    ENT_TYPE.ITEM_HOUYIBOW,
    ENT_TYPE.ITEM_LIGHT_ARROW,
}

fx.steal_item = function(r)
    local p=P(); if not p or not p.holding_uid or p.holding_uid<=0 then return false end
    local held = get_entity(p.holding_uid)
    if held then
        for _, prot in ipairs(protected_items) do
            if held.type.id == prot then return false end
        end
    end
    silent_remove_held(p)
    return true
end

fx.randomize_item = function(r)
    local p=P(); if not p then return false end
    silent_remove_held(p)
    local pool={ENT_TYPE.ITEM_SHOTGUN,ENT_TYPE.ITEM_FREEZERAY,ENT_TYPE.ITEM_WEBGUN,ENT_TYPE.ITEM_CAMERA,ENT_TYPE.ITEM_TELEPORTER,ENT_TYPE.ITEM_BOOMERANG,ENT_TYPE.ITEM_MACHETE,ENT_TYPE.ITEM_MATTOCK}
    local u=spawn_entity_over(pool[math.random(#pool)],p.uid,0,0.5)
    if u then pick_up(p.uid,u) end
    return true
end

-- Spawn enemies
for _,n in ipairs({"snake","spider","bat","skeleton","hornedlizard","caveman","scorpion","mantrap","witchdoctor","vampire","ufo","shopkeeper","vlad"}) do
    fx["spawn_"..n] = function(r) if not IL() then return false end; return snp(E[n])~=nil end
end
fx.spawn_hiredhand = function(r) if not IL() then return false end; local p=P(); if not p then return false end; spawn_companion(ENT_TYPE.CHAR_HIREDHAND, p.x+2, p.y, p.layer); return true end

fx.anubis_coffin = function(r) local p=P(); if not p then return false end; return spawn(ENT_TYPE.ITEM_ANUBIS_COFFIN, p.x+4, p.y+3, p.layer, 0, 0)~=nil end

-- Hazards
fx.spawn_arrowtrap  = function(r) local p=P(); if not p then return false end; local x,y,l=get_position(p.uid); return spawn_grid_entity(E.arrowtrap,math.floor(x+(math.random()>0.5 and 3 or -3)),math.floor(y),l)~=nil end
fx.spawn_tnt        = function(r) return snp(E.tnt,0,1)~=nil end
fx.spawn_boulder    = function(r) return snp(E.boulder,0,3)~=nil end
fx.spawn_lavapot    = function(r) local p=P(); if not p then return false end; local x,y,l=get_position(p.uid); return spawn_entity(ENT_TYPE.ITEM_LAVAPOT,x,y+2,l,0,0)~=nil end
fx.spawn_kali_altar = function(r) local p=P(); if not p then return false end; return spawn(ENT_TYPE.FLOOR_ALTAR, p.x+2, p.y, p.layer, 0, 0)~=nil end

-- Level mods
-- fx.level_dark        = function(r) if not IL() then return false end; local o=state.level_flags; state.level_flags=set_flag(state.level_flags,18); reg_timed(r.id,r.code,r.duration,function() state.level_flags=o end); return "timed" end
fx.speed_up          = function(r) local o=get_speedhack(); set_speedhack(o*1.5); reg_timed(r.id,r.code,r.duration,function() set_speedhack(o) end); return "timed" end
fx.slow_motion       = function(r) local o=get_speedhack(); set_speedhack(o*0.5); reg_timed(r.id,r.code,r.duration,function() set_speedhack(o) end); return "timed" end
fx.spawn_ghost = function(r) if not IL() then return false end; local p=P(); if not p then return false end; spawn(ENT_TYPE.MONS_GHOST, p.x+3, p.y+2, p.layer, 0, 0); return true end
fx.level_feeling = function(r)
    if not IL() then return false end
    local text = r.text or ""
    if text == "" then
        local msgs = {"I hear rushing water...","The ground is shaking!","You feel uneasy...","My skin is crawling..."}
        text = msgs[math.random(#msgs)]
    end
    toast(r.viewer..": "..text)
    return true
end

-- Chaos
fx.kill_player    = function(r) local p=P(); if not p then return false end; kill_entity(p.uid); return true end
fx.enemy_rain = function(r) if not IL() then return false end; local pool={"snake","spider","bat","skeleton","caveman","scorpion"}; local c=set_callback(function() if math.random()<0.3 then snp(E[pool[math.random(#pool)]],math.random(-5,5),3) end end,ON.FRAME); reg_timed(r.id,r.code,r.duration,function() clear_callback(c) end); return "timed" end
fx.bomb_rain = function(r) if not IL() then return false end; local c=set_callback(function() if math.random()<0.2 then local p=P(); if p then spawn(ENT_TYPE.ITEM_BOMB,p.x+math.random(-4,4),p.y+3,p.layer,0,0) end end end,ON.FRAME); reg_timed(r.id,r.code,r.duration,function() clear_callback(c) end); return "timed" end
fx.explode_all    = function(r) if not IL() then return false end; local p=P(); if not p then return false end; local px,py,l=get_position(p.uid); local n=0; for _,u in ipairs(get_entities_by(0,MASK.MONSTER,l)) do if distance(p.uid,u)<10 then local x,y=get_position(u); spawn_entity(ENT_TYPE.FX_EXPLOSION,x,y,l,0,0); kill_entity(u); n=n+1 end end; return n>0 end
fx.destroy_altar = function(r) local a=get_entities_by_type(ENT_TYPE.FLOOR_ALTAR); if #a==0 then return false end; kill_entity(a[1]); return true end
fx.punish = function(r) local p=P(); if not p then return false end; attach_ball_and_chain(p.uid, 0, 0); return true end

fx.hadoken = function(r)
    local p=P(); if not p then return false end
    local facing_left = test_flag(p.flags, 17)
    local dir = facing_left and -1 or 1
    return spawn(ENT_TYPE.ITEM_PLASMACANNON_SHOT, p.x+(dir*2), p.y, p.layer, dir*0.5, 0) ~= nil
end

fx.spawn_olmec = function(r)
    if not IL() then return false end
    local p=P(); if not p then return false end
    local dir = math.random() > 0.5 and 5 or -5
    return spawn(E.olmec, p.x+dir, p.y+5, p.layer, 0, 0) ~= nil
end

fx.spawn_anubis2 = function(r)
    if not IL() then return false end
    local p=P(); if not p then return false end
    local dir = math.random() > 0.5 and 5 or -5
    return spawn(ENT_TYPE.MONS_ANUBIS2, p.x+dir, p.y-5, p.layer, 0, 0) ~= nil
end

fx.spawn_apep = function(r)
    local p=P(); if not p then return false end
    local oy = math.random() > 0.5 and 4 or -4
    return spawn(ENT_TYPE.MONS_APEP_HEAD, p.x+12, p.y+oy, p.layer, 0, 0) ~= nil
end
fx.spawn_jellyfish = function(r)
    local p=P(); if not p then return false end
    local oy = math.random() > 0.5 and 4 or -4
    return spawn(ENT_TYPE.MONS_MEGAJELLYFISH, p.x+12, p.y+oy, p.layer, 0, 0) ~= nil
end

fx.force_outpost = function(r)
    local s = get_local_state()
    s.shoppie_aggro_next = 20
    toast(r.viewer.." angered the Shopkeeper's Association!")
    return true
end

fx.forgive_player = function(r)
    local s = get_local_state()
    s.shoppie_aggro_next = 0
    s.shoppie_aggro = 0
    toast(r.viewer.." bribed the Shopkeeper's Association!")
    return true
end

fx.force_dark = function(r)
    local cb
    cb = set_callback(function()
        get_local_state().level_flags = set_flag(get_local_state().level_flags, 18)
        clear_callback(cb)
    end, ON.POST_ROOM_GENERATION)
    toast(r.viewer.." cursed the next level with darkness!")
    return true
end

-- ── DISPATCHER ──────────────────────────────────────────────
local function handle(msg)
    local id   = tonumber(msg.id) or 0
    local code = msg.code or ""
    if not IL() or not P() then resp(id,"retry"); return end
    local h = fx[code]
    if not h then resp(id,"failure"); return end
    message("text="..tostring(msg.text))
    local ok,res = pcall(h, {id=id,code=code,viewer=msg.viewer or "Anon",duration=tonumber(msg.duration) or 0,text=msg.text or ""})
    if not ok then resp(id,"retry"); return end
    if res=="timed" then ann(msg.viewer or "Anon",code)
    elseif res then resp(id,"success"); ann(msg.viewer or "Anon",code)
    else resp(id,"retry") end
end

-- ── HUD ─────────────────────────────────────────────────────
local function hud(ctx)
    local now = get_frame(); local keep = {}
    for _,a in ipairs(anns) do
        if now < a.expire then
            ctx:draw_text(-0.95, -0.85+#keep*0.05, 0.0015, a.text, rgba(255,220,50,math.floor(math.min(1,(a.expire-now)/30)*255)))
            keep[#keep+1] = a
        end
    end; anns = keep
    if #timed_fx > 0 then
        local y = 0.9
        ctx:draw_text(0.65,y,0.0012,"ACTIVE EFFECTS:",rgba(200,200,255,200)); y=y-0.04
        for _,t in ipairs(timed_fx) do
            ctx:draw_text(0.65,y,0.001,string.format("  %s %.1fs",t.code,math.max(0,(t.end_frame-now)/60)),rgba(255,255,100,180)); y=y-0.035
        end
    end
end

-- ── HTTP POLLING ────────────────────────────────────────────
-- Overlunky has no way to receive UDP/TCP. We poll the bridge's
-- HTTP server for pending effects using http_get_async (requires
-- unsafe mode). Responses go back via udp_send.

local function on_poll_response(response)
    if not response or response == "" or response == "[]" then return end
    for obj_str in response:gmatch("{[^}]+}") do
        local msg = jdec(obj_str)
        if msg and msg.code then
            effect_queue[#effect_queue+1] = msg
        end
    end
end

local function poll_bridge()
    poll_counter = poll_counter + 1
    if poll_counter % POLL_INTERVAL ~= 0 then return end
    http_get_async(POLL_URL, on_poll_response)
end

-- ── HOOKS ───────────────────────────────────────────────────
set_callback(function() launch_bridge() end, ON.LOAD)
set_callback(function()
    poll_bridge()
    local q = effect_queue
    effect_queue = {}
    for _, msg in ipairs(q) do
        handle(msg)
    end
    tick_timed()
end, ON.FRAME)
set_callback(function(ctx) hud(ctx) end, ON.GUIFRAME)
set_callback(function()
    for _,t in ipairs(timed_fx) do if t.fn then pcall(t.fn) end end
    timed_fx = {}; stop_bridge()
    print("[CC] Crowd Control unloaded.")
end, ON.SCRIPT_DISABLE)

set_callback(function()
    local p = P()
    if p then
        local x, y = p.x, p.y
        spawn_pos = {x=x, y=y}
        safe_to_spawn_above = false
    end
end, ON.LEVEL)



print("[CC] Crowd Control loaded. Bridge auto-starts on level load.")
print("[CC] Polling " .. POLL_URL .. " for effects.")
