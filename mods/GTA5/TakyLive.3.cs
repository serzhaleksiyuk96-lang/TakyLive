// ═══════════════════════════════════════════════════════════════════════════
//  TakyLive — мод GTA 5: подарки и чат TikTok управляют игрой
//  Машины, враги, зомби, взрывы, метеориты, погода, гравитация, эффекты…
//
//  УСТАНОВКА: в программе TakyLive → вкладка GTA 5 → «🧩 Мод для игры» → «Установить».
//  Вручную: нужны Script Hook V и ScriptHookVDotNet; этот файл — в папку игры → scripts.
//  Старый файл TikTokBridge.3.cs удали, если он там есть.
//
//  ТОЛЬКО СЮЖЕТНЫЙ РЕЖИМ! В GTA Online моды = бан.
//  Если мод не запустился — пришли файл ScriptHookVDotNet.log из папки игры.
// ═══════════════════════════════════════════════════════════════════════════
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using GTA;
using GTA.Math;
using GTA.Native;

// ═══ СВЯЗЬ С ПРОГРАММОЙ ═══ (без функций игры — эту часть можно проверить отдельно)
public class BridgeLink
{
    public string Server = "http://127.0.0.1:8765";
    public string Game = "gta5";
    public readonly ConcurrentQueue<string[]> Queue = new ConcurrentQueue<string[]>();
    public volatile bool Connected;
    public volatile bool Running = true;
    long lastId = -1;

    public void Start()
    {
        Thread t = new Thread(Loop);
        t.IsBackground = true;
        t.Start();
    }

    public void Stop() { Running = false; }

    void Loop()
    {
        while (Running)
        {
            try { PollOnce(); Connected = true; }
            catch { Connected = false; }
            Thread.Sleep(Connected ? 250 : 2000);
        }
    }

    // Забирает новые команды из программы (простой текст: «last=N», затем «id|кто|команда»)
    public void PollOnce()
    {
        string url = Server + "/api/mod/poll?fmt=text&game=" + Game + "&since=" + lastId.ToString(CultureInfo.InvariantCulture);
        HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
        req.Timeout = 2000;
        req.ReadWriteTimeout = 2000;
        req.Proxy = null;
        using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
        using (StreamReader sr = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
        {
            Parse(sr.ReadToEnd());
        }
    }

    public void Parse(string body)
    {
        foreach (string raw in body.Split('\n'))
        {
            string line = raw.TrimEnd('\r');
            if (line.Length == 0) continue;
            if (line.StartsWith("last="))
            {
                long v;
                if (long.TryParse(line.Substring(5), NumberStyles.Integer, CultureInfo.InvariantCulture, out v)) lastId = v;
                continue;
            }
            string[] p = line.Split(new char[] { '|' }, 3);
            if (p.Length == 3) Queue.Enqueue(new string[] { p[1], p[2] });
        }
    }

    // Сообщение в «Лог событий» программы (ошибки видно, не заглядывая в игру)
    public void Report(string text)
    {
        string msg = text;
        ThreadPool.QueueUserWorkItem(delegate
        {
            try
            {
                byte[] data = Encoding.UTF8.GetBytes("game=" + Uri.EscapeDataString(Game) + "&text=" + Uri.EscapeDataString(msg));
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(Server + "/api/mod/log");
                req.Method = "POST";
                req.ContentType = "application/x-www-form-urlencoded";
                req.ContentLength = data.Length;
                req.Timeout = 2000;
                req.Proxy = null;
                using (Stream s = req.GetRequestStream()) s.Write(data, 0, data.Length);
                using (WebResponse r = req.GetResponse()) { }
            }
            catch { }
        });
    }
}
// ═══ КОНЕЦ СВЯЗИ ═══

public class TakyLive : Script
{
    readonly BridgeLink link = new BridgeLink();
    readonly Random rnd = new Random();
    readonly DateTime started = DateTime.Now;
    bool announced, hinted;

    // эффекты на время: имя → когда закончится
    readonly Dictionary<string, DateTime> timed = new Dictionary<string, DateTime>();
    // отложенные действия (серии взрывов, метеориты): когда → что
    readonly List<KeyValuePair<DateTime, Action>> later = new List<KeyValuePair<DateTime, Action>>();

    static readonly string[] Cars = { "adder", "zentorno", "t20", "kuruma", "insurgent", "rhino", "bmx",
        "faggio", "dump", "bus", "monster", "panto", "caddy", "tractor", "journey", "blista", "voodoo",
        "infernus", "bati", "sanchez", "phantom", "firetruk", "ambulance", "police", "stretch", "taco", "mower" };
    static readonly string[] Weapons = { "weapon_pistol", "weapon_microsmg", "weapon_assaultrifle", "weapon_pumpshotgun",
        "weapon_sniperrifle", "weapon_rpg", "weapon_minigun", "weapon_grenade", "weapon_molotov", "weapon_bat",
        "weapon_knife", "weapon_stungun", "weapon_flaregun", "weapon_firework", "weapon_railgun", "weapon_snowball" };
    static readonly string[] TripFx = { "DrugsMichaelAliensFight", "DrugsTrevorClownsFight", "ChopVision", "Rampage", "DMT_flight" };
    // команды для «random_chaos» — безопасные, без смерти и розыска
    static readonly string[] Chaos = { "rain_cars 4", "launch 20", "zombies 4", "clowns 3", "meteors 6", "drunk 15", "moon_gravity 15",
        "fireworks 6", "slippery 15", "superjump 20", "random_vehicle", "animal a_c_chimp", "trip 12", "geyser", "random_outfit",
        "fast_run 15", "explosive_punch 15", "poop 6", "airstrike", "paint" };

    public TakyLive()
    {
        Tick += OnTick;
        Aborted += OnAborted;
        Interval = 0;
        link.Start();
    }

    void OnAborted(object sender, EventArgs e)
    {
        link.Stop();
        ResetAll();
    }

    void OnTick(object sender, EventArgs e)
    {
        if (link.Connected != announced)
        {
            announced = link.Connected;
            hinted = true;
            Notify(announced ? "~g~TakyLive~s~ подключён" : "~r~TakyLive~s~: нет связи с программой");
        }
        if (!hinted && (DateTime.Now - started).TotalSeconds > 10)
        {
            hinted = true;
            Notify("~y~TakyLive~s~ ждёт программу — запусти её");
        }
        PerFrame();
        string[] item;
        int done = 0;
        while (done < 4 && link.Queue.TryDequeue(out item))   // не больше 4 команд за кадр — без лагов
        {
            done++;
            try { Run(item[0], item[1]); }
            catch (Exception ex) { link.Report("ошибка в команде «" + item[1] + "»: " + ex.Message); }
        }
    }

    // ── эффекты, которые нужно включать каждый кадр, и окончание эффектов на время ──
    void PerFrame()
    {
        if (Active("superjump")) Function.Call(Hash.SET_SUPER_JUMP_THIS_FRAME, Game.Player);
        if (Active("explosive_ammo")) Function.Call(Hash.SET_EXPLOSIVE_AMMO_THIS_FRAME, Game.Player);
        if (Active("fire_ammo")) Function.Call(Hash.SET_FIRE_AMMO_THIS_FRAME, Game.Player);
        if (Active("explosive_punch")) Function.Call(Hash.SET_EXPLOSIVE_MELEE_THIS_FRAME, Game.Player);
        if (timed.Count > 0)
        {
            List<string> ended = new List<string>();
            foreach (KeyValuePair<string, DateTime> kv in timed) if (DateTime.Now >= kv.Value) ended.Add(kv.Key);
            foreach (string k in ended) { timed.Remove(k); End(k); }
        }
        if (later.Count > 0)
        {
            List<KeyValuePair<DateTime, Action>> due = later.FindAll(x => DateTime.Now >= x.Key);
            later.RemoveAll(x => DateTime.Now >= x.Key);
            foreach (KeyValuePair<DateTime, Action> x in due)
            {
                try { x.Value(); } catch (Exception ex) { link.Report("отложенное действие: " + ex.Message); }
            }
        }
    }

    bool Active(string k) { return timed.ContainsKey(k); }
    void For(string k, int sec) { timed[k] = DateTime.Now.AddSeconds(Clamp(sec, 1, 600)); }
    void After(int ms, Action a) { later.Add(new KeyValuePair<DateTime, Action>(DateTime.Now.AddMilliseconds(ms), a)); }

    void End(string k)
    {
        Ped me = Game.Player.Character;
        switch (k)
        {
            case "god":           if (me != null) me.IsInvincible = false; break;
            case "invisible":     if (me != null) me.IsVisible = true; break;
            case "fast_run":      Function.Call(Hash.SET_RUN_SPRINT_MULTIPLIER_FOR_PLAYER, Game.Player, 1.0f);
                                  Function.Call(Hash.SET_SWIM_MULTIPLIER_FOR_PLAYER, Game.Player, 1.0f); break;
            case "infinite_ammo": if (me != null) Function.Call(Hash.SET_PED_INFINITE_AMMO_CLIP, me, false); break;
            case "moon_gravity":  Function.Call(Hash.SET_GRAVITY_LEVEL, 0); break;
            case "riot":          Function.Call(Hash.SET_RIOT_MODE_ENABLED, false); break;
            case "blackout":      Function.Call(Hash.SET_ARTIFICIAL_LIGHTS_STATE, false); break;
            case "drunk":
                if (me != null) Function.Call(Hash.RESET_PED_MOVEMENT_CLIPSET, me, 1.0f);
                Function.Call(Hash.STOP_GAMEPLAY_CAM_SHAKING, true); break;
            case "screen_fx":     Function.Call(Hash.ANIMPOSTFX_STOP_ALL); break;
            case "slowmo":        Function.Call(Hash.SET_TIME_SCALE, 1f); break;
            case "slippery":
                if (me != null && me.CurrentVehicle != null) Function.Call(Hash.SET_VEHICLE_REDUCE_GRIP, me.CurrentVehicle, false); break;
            case "engine_off":
                if (me != null && me.CurrentVehicle != null) Function.Call(Hash.SET_VEHICLE_ENGINE_ON, me.CurrentVehicle, true, true, false); break;
            case "fade":          Function.Call(Hash.DO_SCREEN_FADE_IN, 800); break;
        }
    }

    void ResetAll()
    {
        foreach (string k in new List<string>(timed.Keys)) End(k);
        timed.Clear();
        later.Clear();
        Function.Call(Hash.SET_TIME_SCALE, 1f);
        Function.Call(Hash.SET_GRAVITY_LEVEL, 0);
    }

    void Run(string user, string cmd)
    {
        string line = (cmd ?? "").Trim();
        string[] a = line.Split(new char[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
        if (a.Length == 0) return;
        string c = a[0].ToLowerInvariant();
        string rest = line.Substring(a[0].Length).Trim();
        Ped me = Game.Player.Character;
        if (me == null || !me.Exists()) return;
        Vector3 front = me.Position + me.ForwardVector * 6f;
        Vehicle car = me.CurrentVehicle;

        switch (c)
        {
            // ═══ ТРАНСПОРТ ═══
            case "vehicle":        SpawnVehicle(Arg(a, 1, RandomCar()), front, me.Heading + 90f, true, false); break;
            case "random_vehicle": SpawnVehicle(RandomCar(), front, me.Heading + 90f, true, false); break;
            case "vehicle_in":     SpawnVehicle(Arg(a, 1, RandomCar()), me.Position, me.Heading, true, true); break;
            case "rain_cars":
                for (int i = 0, n = Clamp(Int(a, 1, 5), 1, 15); i < n; i++)
                    SpawnVehicle(RandomCar(), me.Position + new Vector3(Rnd(-14f, 14f), Rnd(-14f, 14f), 25f + i * 5f),
                                 Rnd(0f, 360f), false, false);
                break;
            case "boost":   if (car != null) car.Velocity = car.ForwardVector * Float(a, 1, 60f); break;
            case "jump_car": if (car != null) car.Velocity = car.Velocity + new Vector3(0f, 0f, Float(a, 1, 15f)); break;
            case "flip":    if (car != null) car.Rotation = new Vector3(0f, 180f, car.Heading); break;
            case "pop_tires":
                if (car != null) for (int i = 0; i < 8; i++) Function.Call(Hash.SET_VEHICLE_TYRE_BURST, car, i, true, 1000f);
                break;
            case "repair":
                if (car != null) { Function.Call(Hash.SET_VEHICLE_FIXED, car); Function.Call(Hash.SET_VEHICLE_DEFORMATION_FIXED, car); }
                break;
            case "upgrade":
                if (car != null)
                {
                    Function.Call(Hash.SET_VEHICLE_MOD_KIT, car, 0);
                    for (int t = 0; t < 50; t++)
                    {
                        int n = Function.Call<int>(Hash.GET_NUM_VEHICLE_MODS, car, t);
                        if (n > 0) Function.Call(Hash.SET_VEHICLE_MOD, car, t, n - 1, false);
                    }
                }
                break;
            case "paint":
                if (car != null)
                {
                    Function.Call(Hash.SET_VEHICLE_CUSTOM_PRIMARY_COLOUR, car, rnd.Next(256), rnd.Next(256), rnd.Next(256));
                    Function.Call(Hash.SET_VEHICLE_CUSTOM_SECONDARY_COLOUR, car, rnd.Next(256), rnd.Next(256), rnd.Next(256));
                }
                break;
            case "explode_car": if (car != null) Function.Call(Hash.EXPLODE_VEHICLE, car, true, false); break;
            case "eject":       if (car != null) Function.Call(Hash.TASK_LEAVE_VEHICLE, me, car, 4160); break;
            case "delete_car":
                if (car != null) { Function.Call(Hash.TASK_LEAVE_VEHICLE, me, car, 16); After(600, delegate { if (car.Exists()) car.Delete(); }); }
                break;
            case "engine_off":
                if (car != null) { Function.Call(Hash.SET_VEHICLE_ENGINE_ON, car, false, true, true); For("engine_off", Int(a, 1, 10)); }
                break;
            case "slippery":
                if (car != null) { Function.Call(Hash.SET_VEHICLE_REDUCE_GRIP, car, true); For("slippery", Int(a, 1, 20)); }
                break;
            case "car_power":
                if (car != null) Function.Call(Hash.SET_VEHICLE_CHEAT_POWER_INCREASE, car, Float(a, 1, 3f));
                break;

            // ═══ ИГРОК ═══
            case "heal":          me.Health = me.MaxHealth; me.Armor = 100; break;
            case "armor":         me.Armor = 100; break;
            case "kill":          me.Health = 0; break;
            case "wanted":        Game.Player.WantedLevel = Clamp(Int(a, 1, 3), 0, 5); break;
            case "clear_wanted":  Game.Player.WantedLevel = 0; break;
            case "god":           me.IsInvincible = true; For("god", Int(a, 1, 30)); break;
            case "invisible":     me.IsVisible = false; For("invisible", Int(a, 1, 20)); break;
            case "superjump":     For("superjump", Int(a, 1, 30)); break;
            case "fast_run":
                Function.Call(Hash.SET_RUN_SPRINT_MULTIPLIER_FOR_PLAYER, Game.Player, 1.49f);
                Function.Call(Hash.SET_SWIM_MULTIPLIER_FOR_PLAYER, Game.Player, 1.49f);
                For("fast_run", Int(a, 1, 30));
                break;
            case "drunk":
            {
                Function.Call(Hash.REQUEST_ANIM_SET, "move_m@drunk@verydrunk");
                for (int i = 0; i < 50 && !Function.Call<bool>(Hash.HAS_ANIM_SET_LOADED, "move_m@drunk@verydrunk"); i++) Wait(10);
                Function.Call(Hash.SET_PED_MOVEMENT_CLIPSET, me, "move_m@drunk@verydrunk", 1.0f);
                Function.Call(Hash.SHAKE_GAMEPLAY_CAM, "DRUNK_SHAKE", 1.5f);
                For("drunk", Int(a, 1, 20));
                break;
            }
            case "ragdoll":
            {
                int ms = (int)(Float(a, 1, 3f) * 1000f);
                Function.Call(Hash.SET_PED_TO_RAGDOLL, me, ms, ms, 0, false, false, false);
                break;
            }
            case "launch":
                Function.Call(Hash.SET_PED_TO_RAGDOLL, me, 3000, 3000, 0, false, false, false);
                Function.Call(Hash.SET_ENTITY_VELOCITY, me, Rnd(-6f, 6f), Rnd(-6f, 6f), Float(a, 1, 25f));
                break;
            case "skydive":
                Give(me, "gadget_parachute", 1);
                me.Position = me.Position + new Vector3(0f, 0f, Float(a, 1, 400f));
                break;
            case "fire_player":   Function.Call<int>(Hash.START_ENTITY_FIRE, me); break;
            case "teleport":      Teleport(Arg(a, 1, "random")); break;
            case "teleport_waypoint":
            {
                int blip = Function.Call<int>(Hash.GET_FIRST_BLIP_INFO_ID, 8);
                if (blip == 0) { Notify("~y~TakyLive:~s~ поставь метку на карте"); break; }
                Vector3 p = Function.Call<Vector3>(Hash.GET_BLIP_INFO_ID_COORD, blip);
                TeleportTo(p.X, p.Y, Ground(p.X, p.Y));
                break;
            }
            case "money":         AddMoney(Int(a, 1, 1000)); break;
            case "take_money":    AddMoney(-Int(a, 1, 1000)); break;
            case "random_outfit": Function.Call(Hash.SET_PED_RANDOM_COMPONENT_VARIATION, me, 0); break;

            // ═══ ОРУЖИЕ ═══
            case "weapon":         Give(me, Arg(a, 1, "weapon_pistol"), Int(a, 2, 250)); break;
            case "random_weapon":  Give(me, Weapons[rnd.Next(Weapons.Length)], 250); break;
            case "all_weapons":    foreach (string w in Weapons) Give(me, w, 250); break;
            case "remove_weapons": Function.Call(Hash.REMOVE_ALL_PED_WEAPONS, me, true); break;
            case "infinite_ammo":  Function.Call(Hash.SET_PED_INFINITE_AMMO_CLIP, me, true); For("infinite_ammo", Int(a, 1, 30)); break;
            case "explosive_ammo": For("explosive_ammo", Int(a, 1, 20)); break;
            case "fire_ammo":      For("fire_ammo", Int(a, 1, 20)); break;
            case "explosive_punch": For("explosive_punch", Int(a, 1, 20)); break;

            // ═══ ЛЮДИ И ЗВЕРИ ═══
            case "peds":
                for (int i = 0, n = Clamp(Int(a, 1, 5), 1, 20); i < n; i++) SpawnPed(Arg(a, 2, ""), Around(me.Position, 3f, 7f));
                break;
            case "enemies":   Attackers(Int(a, 1, 3), Arg(a, 3, ""), Arg(a, 2, "weapon_pistol"), 10f, 18f); break;
            case "zombies":   Attackers(Int(a, 1, 5), "u_m_y_zombie_01", "weapon_unarmed", 6f, 14f); break;
            case "clowns":    Attackers(Int(a, 1, 4), "s_m_y_clown_01", "weapon_bat", 8f, 15f); break;
            case "army":      Attackers(Int(a, 1, 3), "s_m_y_marine_03", "weapon_carbinerifle", 15f, 25f); break;
            case "aliens":    Attackers(Int(a, 1, 2), "s_m_m_movalien_01", "weapon_raypistol", 10f, 18f); break;
            case "cops":      Attackers(Int(a, 1, 3), "s_m_y_cop_01", "weapon_pistol", 12f, 20f); Game.Player.WantedLevel = 2; break;
            case "juggernaut": Attackers(Int(a, 1, 1), "u_m_y_juggernaut_01", "weapon_minigun", 15f, 22f); break;
            case "cougar":    Attackers(Int(a, 1, 1), "a_c_mtlion", "weapon_unarmed", 8f, 14f); break;
            case "bodyguards":
            {
                int grp = Function.Call<int>(Hash.GET_PED_GROUP_INDEX, me);
                for (int i = 0, n = Clamp(Int(a, 1, 2), 1, 7); i < n; i++)
                {
                    Ped p = SpawnPed("s_m_m_highsec_01", Around(me.Position, 2f, 4f));
                    if (p == null) continue;
                    Give(p, Arg(a, 2, "weapon_carbinerifle"), 500);
                    Function.Call(Hash.SET_PED_AS_GROUP_MEMBER, p, grp);
                }
                break;
            }
            case "animal":    SpawnPed(Arg(a, 1, "a_c_chimp"), Around(me.Position, 3f, 6f)); break;
            case "angry_peds":
                foreach (Ped p in World.GetNearbyPeds(me, Float(a, 1, 40f)))
                {
                    if (p == null || p == me || p.IsDead) continue;
                    Give(p, "weapon_bat", 1);
                    Function.Call(Hash.TASK_COMBAT_PED, p, me, 0, 16);
                }
                break;
            case "panic":
                foreach (Ped p in World.GetNearbyPeds(me, Float(a, 1, 50f)))
                    if (p != null && p != me && !p.IsDead) Function.Call(Hash.TASK_SMART_FLEE_PED, p, me, 200f, -1, false, false);
                break;
            case "clear_area":
                Function.Call(Hash.CLEAR_AREA, me.Position.X, me.Position.Y, me.Position.Z, Float(a, 1, 60f), true, false, false, false);
                break;

            // ═══ МИР ═══
            case "weather":   Function.Call(Hash.SET_WEATHER_TYPE_NOW_PERSIST, Arg(a, 1, "THUNDER").ToUpperInvariant()); break;
            case "time":      Function.Call(Hash.SET_CLOCK_TIME, Clamp(Int(a, 1, 0), 0, 23), 0, 0); break;
            case "add_hours": Function.Call(Hash.ADD_TO_CLOCK_TIME, Clamp(Int(a, 1, 6), 1, 23), 0, 0); break;
            case "slowmo":    Function.Call(Hash.SET_TIME_SCALE, 0.35f); For("slowmo", Int(a, 1, 5)); break;
            case "moon_gravity": Function.Call(Hash.SET_GRAVITY_LEVEL, 1); For("moon_gravity", Int(a, 1, 20)); break;
            case "riot":      Function.Call(Hash.SET_RIOT_MODE_ENABLED, true); For("riot", Int(a, 1, 30)); break;
            case "blackout":  Function.Call(Hash.SET_ARTIFICIAL_LIGHTS_STATE, true); For("blackout", Int(a, 1, 30)); break;
            case "explode":   Explosion(me.Position + me.ForwardVector * Float(a, 1, 6f), 4, 1f); break;
            case "fire":      Explosion(front, 3, 0.3f); break;
            case "meteors":
                for (int i = 0, n = Clamp(Int(a, 1, 8), 1, 25); i < n; i++)
                    After(i * 450, delegate { Ped m = Game.Player.Character; if (m != null) Explosion(Around(m.Position, 6f, 22f), 4, 0.4f); });
                break;
            case "airstrike":
                for (int i = 0; i < 6; i++)
                {
                    int k = i;
                    After(i * 300, delegate
                    {
                        Ped m = Game.Player.Character;
                        if (m == null) return;
                        Explosion(m.Position + m.ForwardVector * (30f - k * 4f) + m.RightVector * Rnd(-3f, 3f), 4, 0.6f);
                    });
                }
                break;
            case "fireworks":
                for (int i = 0, n = Clamp(Int(a, 1, 6), 1, 20); i < n; i++)
                    After(i * 350, delegate { Ped m = Game.Player.Character; if (m != null) Explosion(Around(m.Position, 4f, 12f) + new Vector3(0f, 0f, 6f), 38, 0f); });
                break;
            case "geyser":    Explosion(me.Position - new Vector3(0f, 0f, 0.8f), 13, 0f); break;
            case "poop":
                for (int i = 0, n = Clamp(Int(a, 1, 5), 1, 20); i < n; i++)
                    After(i * 250, delegate { Ped m = Game.Player.Character; if (m != null) Explosion(Around(m.Position, 0f, 3f) + new Vector3(0f, 0f, 1.5f), 35, 0f); });
                break;

            // ═══ ЭКРАН ═══
            case "shake":     Function.Call(Hash.SHAKE_GAMEPLAY_CAM, "LARGE_EXPLOSION_SHAKE", Float(a, 1, 0.6f)); break;
            case "screen_fx": Function.Call(Hash.ANIMPOSTFX_PLAY, Arg(a, 1, "DrugsMichaelAliensFight"), 0, true); For("screen_fx", Int(a, 2, 10)); break;
            case "trip":      Function.Call(Hash.ANIMPOSTFX_PLAY, TripFx[rnd.Next(TripFx.Length)], 0, true); For("screen_fx", Int(a, 1, 10)); break;
            case "fade":      Function.Call(Hash.DO_SCREEN_FADE_OUT, 600); For("fade", Int(a, 1, 3)); break;
            case "notify":    Notify(rest.Length > 0 ? rest : "Привет от " + user); break;
            case "big_text":  GTA.UI.Screen.ShowSubtitle(rest.Length > 0 ? rest : user, 4000); break;

            // ═══ ХАОС И СБРОС ═══
            case "random_chaos":
            {
                string pick = Chaos[rnd.Next(Chaos.Length)];
                Notify("~p~Хаос:~s~ " + pick);
                Run(user, pick);
                break;
            }
            case "reset":
                ResetAll();
                me.IsInvincible = false; me.IsVisible = true;
                Notify("~g~TakyLive:~s~ все эффекты сброшены");
                break;

            default:
                link.Report("неизвестная команда: " + c);
                Notify("~y~TakyLive:~s~ неизвестная команда ~b~" + c);
                break;
        }
    }

    // ── помощники ──
    void Attackers(int count, string model, string weapon, float min, float max)
    {
        Ped me = Game.Player.Character;
        for (int i = 0, n = Clamp(count, 1, 15); i < n; i++)
        {
            Ped p = SpawnPed(model, Around(me.Position, min, max));
            if (p == null) continue;
            if (weapon != "weapon_unarmed") Give(p, weapon, 300);
            Function.Call(Hash.SET_PED_COMBAT_ATTRIBUTES, p, 46, true);     // дерётся до конца
            Function.Call(Hash.TASK_COMBAT_PED, p, me, 0, 16);
        }
    }

    void Teleport(string place)
    {
        string[] names = { "airport", "chiliad", "maze_bank", "beach", "vinewood_sign", "sandy", "docks", "zancudo", "paleto", "prison" };
        float[][] pos = {
            new float[] { -1336f, -3044f, 13.9f }, new float[] { 501.8f, 5604.5f, 797.9f }, new float[] { -75f, -818f, 326.2f },
            new float[] { -1600f, -1040f, 13f }, new float[] { 711f, 1198f, 348f }, new float[] { 1747f, 3273f, 41f },
            new float[] { 1000f, -2900f, 5.9f }, new float[] { -2047f, 3132f, 32.8f }, new float[] { -275f, 6635f, 7.4f },
            new float[] { 1855f, 2600f, 45.7f } };
        int idx = Array.IndexOf(names, place.ToLowerInvariant());
        if (idx < 0) idx = rnd.Next(names.Length);
        TeleportTo(pos[idx][0], pos[idx][1], pos[idx][2]);
    }

    void TeleportTo(float x, float y, float z)
    {
        Ped me = Game.Player.Character;
        Entity e = (me.CurrentVehicle != null) ? (Entity)me.CurrentVehicle : me;
        Function.Call(Hash.SET_ENTITY_COORDS, e, x, y, z, false, false, false, true);
    }

    float Ground(float x, float y)
    {
        OutputArgument gz = new OutputArgument();
        for (float h = 1000f; h > 0f; h -= 100f)
        {
            Function.Call(Hash.SET_ENTITY_COORDS, Game.Player.Character, x, y, h, false, false, false, true);
            Wait(50);
            if (Function.Call<bool>(Hash.GET_GROUND_Z_FOR_3D_COORD, x, y, h, gz, false, false)) return gz.GetResult<float>() + 1f;
        }
        return 100f;
    }

    // деньги в сюжете: у Майкла, Франклина и Тревора свои кошельки
    void AddMoney(int delta)
    {
        int model = Game.Player.Character.Model.Hash;
        string stat = model == Game.GenerateHash("player_one") ? "SP1_TOTAL_CASH"
                    : model == Game.GenerateHash("player_two") ? "SP2_TOTAL_CASH" : "SP0_TOTAL_CASH";
        int hash = Game.GenerateHash(stat);
        OutputArgument cur = new OutputArgument();
        Function.Call<bool>(Hash.STAT_GET_INT, hash, cur, -1);
        int now = cur.GetResult<int>();
        Function.Call(Hash.STAT_SET_INT, hash, System.Math.Max(0, now + delta), true);
        Notify((delta >= 0 ? "~g~+$" : "~r~-$") + System.Math.Abs(delta));
    }

    Vehicle SpawnVehicle(string name, Vector3 pos, float heading, bool onGround, bool warpIn)
    {
        Model m = new Model(name);
        if (!m.IsInCdImage || !m.IsVehicle)
        {
            link.Report("нет такой машины: " + name);
            Notify("~y~TakyLive:~s~ нет машины ~b~" + name);
            return null;
        }
        if (!m.Request(2000)) { link.Report("машина не загрузилась: " + name); return null; }
        Vehicle v = World.CreateVehicle(m, pos, heading);
        m.MarkAsNoLongerNeeded();
        if (v == null) return null;
        if (onGround) Function.Call(Hash.SET_VEHICLE_ON_GROUND_PROPERLY, v);
        if (warpIn) Function.Call(Hash.SET_PED_INTO_VEHICLE, Game.Player.Character, v, -1);
        v.MarkAsNoLongerNeeded();
        return v;
    }

    Ped SpawnPed(string name, Vector3 pos)
    {
        Ped p;
        if (string.IsNullOrEmpty(name))
        {
            p = World.CreateRandomPed(pos);
        }
        else
        {
            Model m = new Model(name);
            if (!m.IsInCdImage || !m.IsPed) { link.Report("нет такого персонажа: " + name); return null; }
            if (!m.Request(2000)) return null;
            p = World.CreatePed(m, pos, Rnd(0f, 360f));
            m.MarkAsNoLongerNeeded();
        }
        if (p != null) p.MarkAsNoLongerNeeded();
        return p;
    }

    void Give(Ped p, string weapon, int ammo)
    {
        Function.Call(Hash.GIVE_WEAPON_TO_PED, p, Game.GenerateHash(weapon.ToLowerInvariant()), ammo, false, true);
    }

    void Explosion(Vector3 p, int type, float shake)
    {
        Function.Call(Hash.ADD_EXPLOSION, p.X, p.Y, p.Z, type, 1f, true, false, shake);
    }

    void Notify(string text) { GTA.UI.Notification.Show(text, false); }

    Vector3 Around(Vector3 c, float min, float max)
    {
        double ang = rnd.NextDouble() * System.Math.PI * 2.0;
        float d = Rnd(min, max);
        return c + new Vector3((float)System.Math.Cos(ang) * d, (float)System.Math.Sin(ang) * d, 0.5f);
    }

    string RandomCar() { return Cars[rnd.Next(Cars.Length)]; }
    float Rnd(float a, float b) { return a + (float)rnd.NextDouble() * (b - a); }
    static int Clamp(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }
    static string Arg(string[] a, int i, string def) { return a.Length > i ? a[i] : def; }

    static int Int(string[] a, int i, int def)
    {
        int v;
        return a.Length > i && int.TryParse(a[i], NumberStyles.Integer, CultureInfo.InvariantCulture, out v) ? v : def;
    }

    static float Float(string[] a, int i, float def)
    {
        float v;
        return a.Length > i && float.TryParse(a[i].Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out v) ? v : def;
    }
}
