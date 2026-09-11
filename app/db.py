"""طبقة Supabase Postgres — اتصالات قصيرة (صديقة للـ pooler)."""
import contextlib
import json
import psycopg2
import psycopg2.extras
from . import config


@contextlib.contextmanager
def conn():
    c = psycopg2.connect(config.DATABASE_URL, connect_timeout=10)
    try:
        c.autocommit = True
        yield c
    finally:
        c.close()


def q_all(sql, params=()):
    with conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def q_one(sql, params=()):
    rows = q_all(sql, params)
    return rows[0] if rows else None


def exec(sql, params=()):
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def health():
    r = q_one("SELECT 1 AS ok")
    return bool(r and r["ok"] == 1)


# ── الصفقات ──
def open_trade(system, symbol, side, entry, qty, tp, sl, leg="", trail_atr=0.0,
               atr0=0.0, hold_hours=24.0, day=None, reason_ar="", signal_key=""):
    try:
        r = q_one(
            """INSERT INTO trades (system,symbol,side,entry,qty,tp,sl,leg,trail_atr,atr0,
                                   hold_hours,day,reason_ar,status,signal_key)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'OPEN',%s)
               RETURNING id""",
            (system, symbol, side, entry, qty, tp or 0, sl, leg, trail_atr, atr0,
             hold_hours, day, reason_ar, signal_key))
        return r["id"] if r else None
    except psycopg2.errors.UniqueViolation:
        # Race-safe deduplication: another cycle already inserted this position.
        return None


def open_positions(system=None):
    if system:
        return q_all("SELECT * FROM trades WHERE status='OPEN' AND system=%s ORDER BY id", (system,))
    return q_all("SELECT * FROM trades WHERE status='OPEN' ORDER BY id")


def close_trade(tid, exit_price, reason, net, r, fee):
    exec("""UPDATE trades SET status='CLOSED', exit_time=now(), exit_price=%s,
            reason=%s, net=%s, r=%s, fee=%s WHERE id=%s""",
         (exit_price, reason, net, r, fee, tid))


def recent_closed(limit=10):
    return q_all("SELECT * FROM trades WHERE status='CLOSED' ORDER BY id DESC LIMIT %s", (limit,))


def get_stats(system=None):
    where = "status='CLOSED'" + (" AND system=%s" if system else "")
    p = (system,) if system else ()
    rows = q_all("SELECT net FROM trades WHERE " + where, p)
    n = len(rows)
    if n == 0:
        return dict(n=0, wins=0, losses=0, wr=0.0, pf=0.0, net=0.0)
    wins = [x["net"] for x in rows if x["net"] > 0]
    loss = [-x["net"] for x in rows if x["net"] <= 0]
    g, l = sum(wins), sum(loss)
    return dict(n=n, wins=len(wins), losses=len(loss), wr=round(len(wins) / n * 100, 1),
                pf=round(g / l, 2) if l > 0 else 0.0,
                net=round(sum(x["net"] for x in rows), 2))


# ── حدود اليوم ──
def day_count(day, system, symbol):
    r = q_one("SELECT n FROM day_counts WHERE day=%s AND system=%s AND symbol=%s",
              (day, system, symbol))
    return r["n"] if r else 0


def bump_day(day, system, symbol):
    exec("""INSERT INTO day_counts (day,system,symbol,n) VALUES (%s,%s,%s,1)
            ON CONFLICT (day,system,symbol) DO UPDATE SET n = day_counts.n + 1""",
         (day, system, symbol))


# ── الرصيد ──
def realized_equity():
    r = q_one("SELECT COALESCE(SUM(net),0) AS s FROM trades WHERE status='CLOSED'")
    return config.PAPER_EQUITY + float(r["s"] or 0)


def mark_equity(equity):
    exec("INSERT INTO equity_marks (equity) VALUES (%s)", (equity,))
    r = q_one("SELECT MAX(equity) AS peak FROM equity_marks")
    return float(r["peak"]) if r and r["peak"] else equity


# ── الأحداث ──
def log_event(level, msg):
    try:
        exec("INSERT INTO events (level,msg) VALUES (%s,%s)", (level, msg[:2000]))
    except Exception:
        pass


# ── الدورات ──
def save_cycle(c):
    exec("""INSERT INTO ct_cycles (started_at,ended_at,duration_ms,scanned_day,scanned_falcon,
            reject_day,reject_falcon,signals,opened,closed,health,errors,equity,note)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
         (c["started_at"], c["ended_at"], c["duration_ms"], c["scanned_day"],
          c["scanned_falcon"], json.dumps(c["reject_day"]), json.dumps(c["reject_falcon"]),
          c["signals"], c["opened"], c["closed"], json.dumps(c["health"]),
          json.dumps(c["errors"]), c["equity"], c.get("note", "")))


def last_cycle():
    return q_one("SELECT * FROM ct_cycles ORDER BY id DESC LIMIT 1")


def recent_errors(n=5):
    return q_all("SELECT ts, msg FROM events WHERE level='ERR' ORDER BY id DESC LIMIT %s", (n,))


def system_totals(today):
    row = q_one("""SELECT
        (SELECT COUNT(*) FROM ct_cycles) AS cycles,
        (SELECT COUNT(*) FROM trades WHERE status='OPEN') AS open_n,
        (SELECT COUNT(*) FROM trades WHERE day=%s) AS today_n,
        (SELECT COUNT(*) FROM trades WHERE status='CLOSED') AS closed_n""", (today,))
    return dict(cycles=row["cycles"], open_n=row["open_n"],
                today_n=row["today_n"], closed_n=row["closed_n"])


# ── حالة عامة ──
def get_state(key, default=None):
    r = q_one("SELECT value FROM state WHERE key=%s", (key,))
    return r["value"] if r else default


def set_state(key, value):
    exec("INSERT INTO state (key,value) VALUES (%s,%s) "
         "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (key, str(value)))
