// ═══════════════════════════════════════════════════════════════════════════
//  TikTok Bridge — мод GTA 5 для программы TikTok-Minecraft-Bridge
//  Подарки и чат TikTok → события в GTA 5: машины, взрывы, враги, погода…
//
//  УСТАНОВКА:
//   1. Поставь Script Hook V и ScriptHookVDotNet Enhanced
//      (Enhanced-версия подходит и для обычной GTA 5, и для GTA 5 Enhanced)
//   2. Положи этот файл в папку игры → scripts (создай папку, если её нет)
//   3. Запусти программу TikTok Bridge, потом GTA 5 → сюжетный режим
//   4. В игре появится «TikTok Bridge подключён»
//
//  ТОЛЬКО СЮЖЕТНЫЙ РЕЖИМ! В GTA Online моды = бан.
//  Если мод не запустился — пришли файл ScriptHookVDotNet.log из папки игры.
// ═══════════════════════════════════════════════════════════════════════════
using System;
using System.Collections.Concurrent;
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

public class TikTokBridge : Script
{
    readonly BridgeLink link = new BridgeLink();
    readonly Random rnd = new Random();
    readonly DateTime started = DateTime.Now;
    bool announced, hinted;
    DateTime slowmoUntil = DateTime.MinValue;

    static readonly string[] Cars = { "adder", "zentorno", "t20", "kuruma", "insurgent", "rhino", "bmx",
        "faggio", "dump", "bus", "monster", "panto", "caddy", "tractor", "journey", "blista", "voodoo" };

    public TikTokBridge()
    {
        Tick += OnTick;
        Aborted += OnAborted;
        Interval = 0;
        link.Start();
    }

    void OnAborted(object sender, EventArgs e)
    {
        link.Stop();
        Function.Call(Hash.SET_TIME_SCALE, 1f);
    }

    void OnTick(object sender, EventArgs e)
    {
        if (link.Connected != announced)
        {
            announced = link.Connected;
            hinted = true;
            Notify(announced ? "~g~TikTok Bridge~s~ подключён" : "~r~TikTok Bridge~s~: нет связи с программой");
        }
        if (!hinted && (DateTime.Now - started).TotalSeconds > 10)
        {
            hinted = true;
            Notify("~y~TikTok Bridge~s~ ждёт программу — запусти её");
        }
        if (slowmoUntil != DateTime.MinValue && DateTime.Now >= slowmoUntil)
        {
            Function.Call(Hash.SET_TIME_SCALE, 1f);
            slowmoUntil = DateTime.MinValue;
        }
        string[] item;
        int done = 0;
        while (done < 4 && link.Queue.TryDequeue(out item))   // не больше 4 команд за кадр — без лагов
        {
            done++;
            try { Run(item[0], item[1]); }
            catch (Exception ex) { link.Report("ошибка в команде «" + item[1] + "»: " + ex.Message); }
        }
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

        switch (c)
        {
            case "vehicle":        SpawnVehicle(Arg(a, 1, RandomCar()), front, me.Heading + 90f, true, false); break;
            case "random_vehicle": SpawnVehicle(RandomCar(), front, me.Heading + 90f, true, false); break;
            case "vehicle_in":     SpawnVehicle(Arg(a, 1, RandomCar()), me.Position, me.Heading, true, true); break;
            case "rain_cars":
                for (int i = 0, n = Clamp(Int(a, 1, 5), 1, 15); i < n; i++)
                    SpawnVehicle(RandomCar(), me.Position + new Vector3(Rnd(-14f, 14f), Rnd(-14f, 14f), 25f + i * 5f),
                                 Rnd(0f, 360f), false, false);
                break;
            case "explode": Explosion(me.Position + me.ForwardVector * Float(a, 1, 6f), 4, 1f); break;
            case "fire":    Explosion(front, 3, 0.3f); break;
            case "wanted":  Game.Player.WantedLevel = Clamp(Int(a, 1, 3), 0, 5); break;
            case "clear_wanted": Game.Player.WantedLevel = 0; break;
            case "heal":    me.Health = me.MaxHealth; me.Armor = 100; break;
            case "armor":   me.Armor = 100; break;
            case "kill":    me.Health = 0; break;
            case "peds":
                for (int i = 0, n = Clamp(Int(a, 1, 5), 1, 20); i < n; i++) SpawnPed(Arg(a, 2, ""), Around(me.Position, 3f, 7f));
                break;
            case "enemies":
                for (int i = 0, n = Clamp(Int(a, 1, 3), 1, 15); i < n; i++)
                {
                    Ped p = SpawnPed(Arg(a, 3, ""), Around(me.Position, 10f, 18f));
                    if (p == null) continue;
                    Give(p, Arg(a, 2, "weapon_pistol"), 250);
                    Function.Call(Hash.TASK_COMBAT_PED, p, me, 0, 16);
                }
                break;
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
            case "animal":  SpawnPed(Arg(a, 1, "a_c_chimp"), Around(me.Position, 3f, 6f)); break;
            case "weapon":  Give(me, Arg(a, 1, "weapon_pistol"), Int(a, 2, 250)); break;
            case "remove_weapons": Function.Call(Hash.REMOVE_ALL_PED_WEAPONS, me, true); break;
            case "weather": Function.Call(Hash.SET_WEATHER_TYPE_NOW_PERSIST, Arg(a, 1, "THUNDER").ToUpperInvariant()); break;
            case "time":    Function.Call(Hash.SET_CLOCK_TIME, Clamp(Int(a, 1, 0), 0, 23), 0, 0); break;
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
            case "slowmo":
                Function.Call(Hash.SET_TIME_SCALE, 0.35f);
                slowmoUntil = DateTime.Now.AddSeconds(Clamp(Int(a, 1, 5), 1, 30));
                break;
            case "shake":   Function.Call(Hash.SHAKE_GAMEPLAY_CAM, "LARGE_EXPLOSION_SHAKE", Float(a, 1, 0.6f)); break;
            case "boost":
            {
                Vehicle v = me.CurrentVehicle;
                if (v != null) v.Velocity = v.ForwardVector * Float(a, 1, 60f);
                break;
            }
            case "flip":
            {
                Vehicle v = me.CurrentVehicle;
                if (v != null) v.Rotation = new Vector3(0f, 180f, v.Heading);
                break;
            }
            case "pop_tires":
            {
                Vehicle v = me.CurrentVehicle;
                if (v != null) for (int i = 0; i < 8; i++) Function.Call(Hash.SET_VEHICLE_TYRE_BURST, v, i, true, 1000f);
                break;
            }
            case "notify":  Notify(rest.Length > 0 ? rest : "Привет от " + user); break;
            default:
                link.Report("неизвестная команда: " + c);
                Notify("~y~TikTok:~s~ неизвестная команда ~b~" + c);
                break;
        }
    }

    Vehicle SpawnVehicle(string name, Vector3 pos, float heading, bool onGround, bool warpIn)
    {
        Model m = new Model(name);
        if (!m.IsInCdImage || !m.IsVehicle)
        {
            link.Report("нет такой машины: " + name);
            Notify("~y~TikTok:~s~ нет машины ~b~" + name);
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
