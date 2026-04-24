#!/usr/bin/env python3
"""
amoCRM → Chiroyli HTML Dashboard (DataLens uslubida)

Ishga tushirish:
    python3 amocrm_dashboard.py

Natija: dashboard.html fayli yaratiladi — brauzerda oching.
"""

import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.parse
import urllib.request

# ============================================================
# SOZLAMALAR
# ============================================================
SUBDOMAIN = "salohiyatschool"

# TOKEN environment variable orqali o'qiladi (GitHub Secrets'da saqlanadi).
# Lokal sinov uchun:   export AMOCRM_TOKEN="eyJ..."
# GitHub Actions uchun: Repo Settings → Secrets → AMOCRM_TOKEN
TOKEN = os.environ.get("AMOCRM_TOKEN", "").strip()
if not TOKEN:
    sys.stderr.write(
        "\n❌ AMOCRM_TOKEN environment variable o'rnatilmagan.\n"
        "   Lokalda: export AMOCRM_TOKEN=\"eyJ...\"  keyin  python3 amocrm_dashboard.py\n"
        "   GitHub:  Repo Settings → Secrets and variables → Actions → New secret\n\n"
    )
    sys.exit(1)

DAYS_BACK_CALLS = 30
KECHKI_PIPELINE_ID = 10554058
APRIL_26_STATUS_ID = 84110942

# ----- Moi Zvonki (ixtiyoriy) -----
# Agar MOIZVONKI_API_KEY env var o'rnatilgan bo'lsa, qo'ng'iroqlar amoCRM call
# notes o'rniga to'g'ridan-to'g'ri PBX'dan olinadi (eng aniq ma'lumot).
# 'or' ishlatamiz — env var bo'sh string bo'lsa ham default kuchga kiradi.
MOIZVONKI_DOMAIN = (os.environ.get("MOIZVONKI_DOMAIN") or "salohiyatschool.moizvonki.ru").strip()
# Tasodifan https:// prefiks qo'shilgan bo'lsa olib tashlaymiz
if MOIZVONKI_DOMAIN.startswith("https://"):
    MOIZVONKI_DOMAIN = MOIZVONKI_DOMAIN[8:]
elif MOIZVONKI_DOMAIN.startswith("http://"):
    MOIZVONKI_DOMAIN = MOIZVONKI_DOMAIN[7:]
MOIZVONKI_DOMAIN = MOIZVONKI_DOMAIN.rstrip("/")  # oxiridagi / ni olib tashlaymiz

MOIZVONKI_USER_NAME = (os.environ.get("MOIZVONKI_USER_NAME") or "").strip()
MOIZVONKI_API_KEY = (os.environ.get("MOIZVONKI_API_KEY") or "").strip()
USE_MOIZVONKI = bool(MOIZVONKI_API_KEY and MOIZVONKI_USER_NAME and MOIZVONKI_DOMAIN)

# ----- Moi Zvonki ism override -----
# amoCRM'dagi user ism noto'g'ri bo'lsa (masalan, "Admin" deb yozilgan-u, aslida
# Begzod ishlatadi), bu yerda email orqali to'g'ri ismni majburlash mumkin.
# Email pastki registr (lowercase) bo'lishi shart.
# Misol:
#   MOIZVONKI_NAME_OVERRIDES = {
#       "begzod@salohiyat.uz": "Begzod",
#       "jamshid@salohiyat.uz": "Jamshid",
#   }
MOIZVONKI_NAME_OVERRIDES = {
    # Foydalanuvchining brauzerda qilgan tahririga muvofiq.
    # Email amoCRM'dagi user'ga moslanadi va dashboard'da chiqadigan ism
    # quyidagicha bo'ladi (hamma qurilmada — telefon, kompyuter):
    "salohiyatschool@gmail.com": "Begzod",
    "dilshodxaydarov1987@gmail.com": "Umar",
    "tulkinovabduvohid12@gmail.com": "Ruslan",
}

# Site voronka (Toshkent leadlari)
SITE_PIPELINE_ID = 10705250
SITE_TOSHKENT_STATUS_ID = 84347286          # 'Toshkent' statusi
# Hisobga olinmaydigan statuslar: filtrlanmagan (inbox) + boshqa viloyat
SITE_EXCLUDED_STATUS_IDS = [84347282, 84347290]  # Неразобранное, Sifatsiz lead

API_BASE = f"https://{SUBDOMAIN}.amocrm.ru/api/v4"
OUTPUT_FILE = "dashboard.html"

# ============================================================
# API YORDAMCHILAR
# ============================================================
def api_get(path, params=None):
    """GET so'rov, avtomatik qayta urinish bilan."""
    url = API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)

    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {TOKEN}",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 204:
                    return None
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except Exception as e:
            if attempt == 4:
                raise
            time.sleep(1 * (attempt + 1))
    return None


def paginate(path, params=None, max_items=None):
    """Avtomatik paginatsiya."""
    params = dict(params or {})
    params["limit"] = params.get("limit", 250)
    items = []
    page = 1
    while True:
        params["page"] = page
        d = api_get(path, params)
        if not d or "_embedded" not in d:
            break
        emb = d["_embedded"]
        arr = next((v for v in emb.values() if isinstance(v, list)), [])
        if not arr:
            break
        items.extend(arr)
        if max_items and len(items) >= max_items:
            items = items[:max_items]
            break
        if len(arr) < params["limit"]:
            break
        page += 1
        time.sleep(0.15)
    return items


# ============================================================
# MA'LUMOT YIG'ISH
# ============================================================
def fetch_all():
    print("1/4  Users yuklanmoqda...")
    users = paginate("/users")
    user_map = {u["id"]: u.get("name", f"User {u['id']}") for u in users}
    # Email → user_id mapping (Moi Zvonki bilan moslash uchun)
    email_to_user_id = {}
    for u in users:
        em = (u.get("email") or "").strip().lower()
        if em:
            email_to_user_id[em] = u["id"]
    print(f"     ✓ {len(users)} user")

    print("2/4  Pipelines yuklanmoqda...")
    pipes_data = api_get("/leads/pipelines")
    pipelines = (pipes_data or {}).get("_embedded", {}).get("pipelines", [])
    status_map = {}
    for p in pipelines:
        for s in p.get("_embedded", {}).get("statuses", []):
            status_map[s["id"]] = {
                "name": s["name"],
                "pipeline": p["name"],
                "sort": s.get("sort", 0),
                "color": s.get("color", ""),
            }
    print(f"     ✓ {len(pipelines)} voronka")

    print("3/5  Leadlar (Kechki guruhlar) yuklanmoqda...")
    leads = paginate(
        "/leads",
        {"filter[pipeline_id]": KECHKI_PIPELINE_ID, "order[created_at]": "desc"},
        max_items=2000,
    )
    print(f"     ✓ {len(leads)} lead")

    print("4/5  Leadlar (Site voronka — Toshkent) yuklanmoqda...")
    site_leads_all = paginate(
        "/leads",
        {"filter[pipeline_id]": SITE_PIPELINE_ID, "order[created_at]": "desc"},
        max_items=3000,
    )
    site_leads = [l for l in site_leads_all if l.get("status_id") not in SITE_EXCLUDED_STATUS_IDS]
    print(f"     ✓ jami Site: {len(site_leads_all)},  Toshkent (filtrlangan): {len(site_leads)}")

    end_ts = int(time.time())
    start_ts = end_ts - DAYS_BACK_CALLS * 86400

    if USE_MOIZVONKI:
        print(f"5/5  Qo'ng'iroqlar Moi Zvonki'dan ({DAYS_BACK_CALLS} kun)...")
        print(f"     Endpoint: https://{MOIZVONKI_DOMAIN}/api/v1")
        print(f"     User:     {MOIZVONKI_USER_NAME}")
        print(f"     API key:  {MOIZVONKI_API_KEY[:6]}...{MOIZVONKI_API_KEY[-4:]} (len={len(MOIZVONKI_API_KEY)})")
        try:
            from moizvonki_api import fetch_calls as mz_fetch, calls_to_dashboard_format
            # Avval supervised=1 (admin ko'rinishi — barcha foydalanuvchilar) bilan
            print(f"     ➜ supervised=1 (admin ko'rinishi) bilan urinib ko'ramiz...")
            mz_calls = mz_fetch(
                domain=MOIZVONKI_DOMAIN,
                user_name=MOIZVONKI_USER_NAME,
                api_key=MOIZVONKI_API_KEY,
                from_ts=start_ts,
                to_ts=end_ts,
                supervised=1,
            )
            # Agar 0 bo'lsa — supervised=0 bilan ham sinab ko'ramiz
            if not mz_calls:
                print(f"     ➜ supervised=1 → 0 qaytdi. supervised=0 bilan sinaymiz...")
                mz_calls = mz_fetch(
                    domain=MOIZVONKI_DOMAIN,
                    user_name=MOIZVONKI_USER_NAME,
                    api_key=MOIZVONKI_API_KEY,
                    from_ts=start_ts,
                    to_ts=end_ts,
                    supervised=0,
                )
            print(f"     ✓ Moi Zvonki: {len(mz_calls)} qo'ng'iroq")
            all_notes, user_map = calls_to_dashboard_format(
                mz_calls, email_to_user_id=email_to_user_id, user_map=user_map
            )
            # Yangi user_map — MoiZvonki email'lari ham ichida (agar amoCRM'da yo'q bo'lsa)
            calls_source = "moizvonki"

            # ----- Ism override (amoCRM'dagi nom Moi Zvonki nomidan farq qilsa) -----
            if MOIZVONKI_NAME_OVERRIDES:
                applied = 0
                for em, correct_name in MOIZVONKI_NAME_OVERRIDES.items():
                    em = em.strip().lower()
                    uid = email_to_user_id.get(em)
                    if uid is not None and uid in user_map:
                        old = user_map[uid]
                        if old != correct_name:
                            user_map[uid] = correct_name
                            print(f"     ↻ ism override: '{old}' → '{correct_name}' (email={em})")
                            applied += 1
                if applied:
                    print(f"     ✓ {applied} ism to'g'rilandi (override)")
        except Exception as e:
            print(f"     ⚠ Moi Zvonki xatosi: {e}")
            print(f"     ➜ AmoCRM call notes'larga qaytyapman (zaxira)")
            all_notes = []
            calls_source = "amocrm_fallback"
            USE_AMOCRM_NOTES = True
        else:
            USE_AMOCRM_NOTES = False
    else:
        USE_AMOCRM_NOTES = True
        calls_source = "amocrm"

    if USE_AMOCRM_NOTES:
        print(f"5/5  Qo'ng'iroqlar amoCRM notes'dan ({DAYS_BACK_CALLS} kun)...")
        # Qo'ng'iroqlar ikkita joyda bo'lishi mumkin: leads/notes VA contacts/notes
        lead_notes = paginate(
            "/leads/notes",
            {
                "filter[note_type][]": ["call_in", "call_out"],
                "filter[created_at][from]": start_ts,
                "filter[created_at][to]": end_ts,
            },
            max_items=5000,
        )
        contact_notes = paginate(
            "/contacts/notes",
            {
                "filter[note_type][]": ["call_in", "call_out"],
                "filter[created_at][from]": start_ts,
                "filter[created_at][to]": end_ts,
            },
            max_items=5000,
        )
        # Id bo'yicha dublikatlarni olib tashlaymiz
        seen = set()
        all_notes = []
        for n in lead_notes + contact_notes:
            nid = n.get("id")
            if nid and nid not in seen:
                seen.add(nid)
                all_notes.append(n)
        print(f"     ✓ leads/notes: {len(lead_notes)}, contacts/notes: {len(contact_notes)}, jami (noyob): {len(all_notes)}")

    return {
        "users": users,
        "user_map": user_map,
        "pipelines": pipelines,
        "status_map": status_map,
        "leads": leads,
        "site_leads": site_leads,
        "calls": all_notes,
        "calls_source": calls_source,
        "generated_at": datetime.now(timezone(timedelta(hours=5))).strftime("%d.%m.%Y %H:%M"),
    }


# ============================================================
# STATISTIKA HISOBLASH
# ============================================================
def compute_stats(data):
    calls = data["calls"]
    leads = data["leads"]
    user_map = data["user_map"]
    status_map = data["status_map"]

    # Bugun
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_ts = int(today.timestamp())

    # Umumiy KPI
    total_calls = len(calls)
    answered = sum(1 for c in calls if (c.get("params") or {}).get("duration", 0) > 0)
    missed = total_calls - answered
    answer_rate = answered / total_calls if total_calls else 0

    today_calls = sum(1 for c in calls if c.get("created_at", 0) >= today_ts)
    today_answered = sum(
        1 for c in calls
        if c.get("created_at", 0) >= today_ts
        and (c.get("params") or {}).get("duration", 0) > 0
    )

    # Yo'nalish
    call_in = sum(1 for c in calls if c.get("note_type") == "call_in")
    call_out = sum(1 for c in calls if c.get("note_type") == "call_out")

    # Leadlar
    total_leads = len(leads)
    apr26 = sum(1 for l in leads if l.get("status_id") == APRIL_26_STATUS_ID)
    sold = sum(1 for l in leads if l.get("status_id") in (142, 84218386))
    lost = sum(1 for l in leads if l.get("status_id") in (143, 83259162))
    in_progress = total_leads - sold - lost
    conv = apr26 / total_leads if total_leads else 0

    # Menejer statistikasi
    mgr_stats = defaultdict(lambda: {
        "calls": 0, "answered": 0, "duration": 0,
        "leads": 0, "apr26": 0, "sold": 0
    })
    for c in calls:
        name = user_map.get(c.get("created_by"), "Noma'lum")
        mgr_stats[name]["calls"] += 1
        dur = (c.get("params") or {}).get("duration", 0)
        if dur > 0:
            mgr_stats[name]["answered"] += 1
            mgr_stats[name]["duration"] += dur
    for l in leads:
        name = user_map.get(l.get("responsible_user_id"), "Noma'lum")
        mgr_stats[name]["leads"] += 1
        if l.get("status_id") == APRIL_26_STATUS_ID:
            mgr_stats[name]["apr26"] += 1
        if l.get("status_id") in (142, 84218386):
            mgr_stats[name]["sold"] += 1

    # Reyting — ball
    mgr_rows = []
    for name, s in mgr_stats.items():
        score = int(
            s["calls"] * 0.3 + s["answered"] * 0.5
            + s["leads"] * 2 + s["apr26"] * 5 + s["sold"] * 20
        )
        ans_rate = s["answered"] / s["calls"] if s["calls"] else 0
        mgr_rows.append({
            "name": name,
            "calls": s["calls"],
            "answered": s["answered"],
            "answer_rate": ans_rate,
            "duration_min": round(s["duration"] / 60, 1),
            "leads": s["leads"],
            "apr26": s["apr26"],
            "sold": s["sold"],
            "score": score,
        })
    mgr_rows.sort(key=lambda x: -x["score"])

    # Voronka bosqichlari
    kechki = next((p for p in data["pipelines"] if p["id"] == KECHKI_PIPELINE_ID), None)
    funnel = []
    if kechki:
        statuses = sorted(
            kechki.get("_embedded", {}).get("statuses", []),
            key=lambda s: s.get("sort", 0),
        )
        status_counts = defaultdict(int)
        for l in leads:
            status_counts[l.get("status_id")] += 1
        for s in statuses:
            cnt = status_counts.get(s["id"], 0)
            if cnt > 0:
                funnel.append({
                    "name": s["name"],
                    "count": cnt,
                    "pct": cnt / total_leads if total_leads else 0,
                })

    # Kunlik dinamika — leadlar
    daily_leads = defaultdict(int)
    for l in leads:
        d = datetime.fromtimestamp(l.get("created_at", 0)).strftime("%d.%m")
        daily_leads[d] += 1
    daily_leads_sorted = sorted(daily_leads.items(), key=lambda x: datetime.strptime(x[0], "%d.%m"))[-14:]

    # Kunlik qo'ng'iroqlar
    daily_calls = defaultdict(lambda: {"total": 0, "answered": 0})
    for c in calls:
        d = datetime.fromtimestamp(c.get("created_at", 0)).strftime("%d.%m")
        daily_calls[d]["total"] += 1
        if (c.get("params") or {}).get("duration", 0) > 0:
            daily_calls[d]["answered"] += 1
    daily_calls_sorted = sorted(daily_calls.items(), key=lambda x: datetime.strptime(x[0], "%d.%m"))[-14:]

    return {
        "kpi": {
            "total_calls": total_calls,
            "answered": answered,
            "missed": missed,
            "answer_rate": answer_rate,
            "today_calls": today_calls,
            "today_answered": today_answered,
            "call_in": call_in,
            "call_out": call_out,
            "total_leads": total_leads,
            "apr26": apr26,
            "sold": sold,
            "lost": lost,
            "in_progress": in_progress,
            "conv": conv,
        },
        "managers": mgr_rows,
        "funnel": funnel,
        "daily_leads": daily_leads_sorted,
        "daily_calls": daily_calls_sorted,
    }


# ============================================================
# HTML YARATISH
# ============================================================
def build_html(stats, data):
    # Raw data — JavaScript client-side filtering uchun
    leads_raw = [
        {
            "s": l.get("status_id"),
            "u": l.get("responsible_user_id"),
            "t": l.get("created_at", 0),
        }
        for l in data["leads"]
    ]
    site_leads_raw = [
        {
            "s": l.get("status_id"),
            "u": l.get("responsible_user_id"),
            "t": l.get("created_at", 0),
        }
        for l in data.get("site_leads", [])
    ]
    calls_raw = [
        {
            "t": c.get("created_at", 0),
            "nt": c.get("note_type", ""),
            "u": c.get("created_by"),
            "d": (c.get("params") or {}).get("duration", 0),
        }
        for c in data["calls"]
    ]
    user_map = {str(uid): name for uid, name in data["user_map"].items()}

    kechki = next((p for p in data["pipelines"] if p["id"] == KECHKI_PIPELINE_ID), None)
    funnel_statuses = []
    qayta_aloqa_id = None
    oylab_koradi_id = None
    if kechki:
        fs = sorted(
            kechki.get("_embedded", {}).get("statuses", []),
            key=lambda s: s.get("sort", 0),
        )
        funnel_statuses = [{"id": s["id"], "name": s["name"]} for s in fs]
        # "Qayta aloqa" va "O'ylab ko'radi" statuslarini nom bo'yicha topamiz
        # (nomi o'zgarsa ham kichik o'zgarish bilan ishlayveradi)
        for s in fs:
            nm = (s.get("name") or "").strip().lower()
            # "qayta aloqa", "qaytaaloqa", "qayta_aloqa" — barchasini qamraydi
            if "qayta" in nm and "aloqa" in nm:
                qayta_aloqa_id = s["id"]
            # "o'ylab ko'radi", "oylab koradi", "o'ylaydi" — turli yozuvlar
            if ("o'ylab" in nm or "oylab" in nm or "o`ylab" in nm) and \
               ("ko'rad" in nm or "korad" in nm or "ko`rad" in nm):
                oylab_koradi_id = s["id"]

    site_pipe = next((p for p in data["pipelines"] if p["id"] == SITE_PIPELINE_ID), None)
    site_funnel_statuses = []
    if site_pipe:
        fs = sorted(
            site_pipe.get("_embedded", {}).get("statuses", []),
            key=lambda s: s.get("sort", 0),
        )
        # Faqat Toshkent bilan bog'liq statuslarni qoldiramiz (excluded'larni olib tashlaymiz)
        site_funnel_statuses = [
            {"id": s["id"], "name": s["name"]}
            for s in fs
            if s["id"] not in SITE_EXCLUDED_STATUS_IDS
        ]

    raw_payload = {
        "leads": leads_raw,
        "site_leads": site_leads_raw,
        "calls": calls_raw,
        "users": user_map,
        "funnel": funnel_statuses,
        "site_funnel": site_funnel_statuses,
        "site_toshkent_id": SITE_TOSHKENT_STATUS_ID,
        "sold_ids": [142, 84218386],
        "lost_ids": [143, 83259162],
        "apr26_id": APRIL_26_STATUS_ID,
        "qayta_aloqa_id": qayta_aloqa_id,
        "oylab_koradi_id": oylab_koradi_id,
        "days_back": DAYS_BACK_CALLS,
    }
    data_json = json.dumps(raw_payload, ensure_ascii=False)
    generated_at = data["generated_at"]

    html_template = """<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- Kesh ishlatma — har safar yangi versiyasini olamiz -->
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate, max-age=0">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<meta name="robots" content="noindex, nofollow, noarchive, nosnippet">
<meta name="googlebot" content="noindex, nofollow">
<title>amoCRM Dashboard — Salohiyat</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f5f7fa;
    color: #1f2937;
    padding: 24px;
  }
  .container { max-width: 1400px; margin: 0 auto; }

  header {
    background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
    color: white;
    padding: 32px;
    border-radius: 16px;
    margin-bottom: 20px;
    box-shadow: 0 4px 20px rgba(30,58,138,0.15);
  }
  header h1 { font-size: 28px; font-weight: 700; margin-bottom: 6px; }
  header .sub { opacity: 0.85; font-size: 14px; }

  .filter-bar {
    background: white;
    border-radius: 12px;
    padding: 16px 20px;
    margin-bottom: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
  }
  .filter-bar .label { font-size: 13px; color: #6b7280; font-weight: 600; margin-right: 6px; }
  .preset-btn {
    background: #f3f4f6;
    border: none;
    padding: 8px 14px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    color: #374151;
    cursor: pointer;
    transition: all 0.15s;
  }
  .preset-btn:hover { background: #e5e7eb; }
  .preset-btn.active {
    background: #3b82f6;
    color: white;
    box-shadow: 0 2px 6px rgba(59,130,246,0.3);
  }
  .filter-bar input[type="date"] {
    padding: 7px 10px;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    font-size: 14px;
    font-family: inherit;
  }
  .filter-bar .apply-btn {
    background: #10b981;
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
  }
  .filter-bar .apply-btn:hover { background: #059669; }
  .filter-bar .range-info {
    margin-left: auto;
    font-size: 13px;
    color: #6b7280;
    font-weight: 500;
  }

  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }
  .kpi {
    background: white;
    padding: 20px;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    border-top: 4px solid var(--accent);
  }
  .kpi .label { font-size: 13px; color: #6b7280; margin-bottom: 8px; font-weight: 500; }
  .kpi .value { font-size: 32px; font-weight: 700; color: var(--accent); }
  .kpi .sub { font-size: 12px; color: #9ca3af; margin-top: 4px; }

  .kpi.blue { --accent: #3b82f6; }
  .kpi.green { --accent: #10b981; }
  .kpi.orange { --accent: #f59e0b; }
  .kpi.red { --accent: #ef4444; }
  .kpi.purple { --accent: #8b5cf6; }
  .kpi.teal { --accent: #14b8a6; }
  .kpi.indigo { --accent: #6366f1; }
  .kpi.pink { --accent: #ec4899; }

  .mgr-detail {
    background: linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%);
    padding: 24px;
    border-radius: 14px;
    margin: 16px 0;
    border: 1px solid #e9d5ff;
  }
  .mgr-detail h3 {
    font-size: 15px; font-weight: 600; color: #6b21a8;
    margin-bottom: 14px;
  }

  .section-title {
    font-size: 18px;
    font-weight: 600;
    color: #1f2937;
    margin: 32px 0 16px 0;
    padding-left: 12px;
    border-left: 4px solid #3b82f6;
  }

  .chart-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
    gap: 20px;
    margin-bottom: 24px;
  }
  .chart-card {
    background: white;
    padding: 20px;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }
  .chart-card h3 {
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 16px;
    color: #374151;
  }
  .chart-card canvas { max-height: 280px; }

  table {
    width: 100%;
    background: white;
    border-collapse: collapse;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }
  th {
    background: #1f2937;
    color: white;
    padding: 12px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
  }
  td {
    padding: 12px 14px;
    border-bottom: 1px solid #f3f4f6;
    font-size: 14px;
  }
  tr:last-child td { border-bottom: none; }
  tr:hover { background: #f9fafb; }
  td.rank { font-weight: 700; text-align: center; width: 50px; }
  td.name { font-weight: 600; }
  td.score { font-weight: 700; color: #3b82f6; }
  .bar {
    height: 20px;
    background: linear-gradient(90deg, #3b82f6, #60a5fa);
    border-radius: 4px;
    min-width: 4px;
  }

  /* ============ Konversiya (LIVE) ============ */
  .conv-card {
    background: white;
    border-radius: 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    overflow: hidden;
    margin-bottom: 28px;
  }
  .conv-summary {
    background: linear-gradient(135deg, #1e3a8a 0%, #6366f1 100%);
    color: white;
    padding: 22px 26px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }
  .conv-summary .total-block .total-lbl {
    font-size: 13px;
    opacity: 0.9;
    margin-bottom: 4px;
  }
  .conv-summary .total-block .total-num {
    font-size: 38px;
    font-weight: 800;
    line-height: 1;
  }
  .conv-summary .total-block .total-sub {
    font-size: 12px;
    opacity: 0.85;
    margin-top: 6px;
  }
  .conv-summary .note {
    font-size: 12px;
    line-height: 1.5;
    opacity: 0.95;
    max-width: 360px;
    text-align: right;
    background: rgba(255,255,255,0.12);
    padding: 10px 14px;
    border-radius: 10px;
  }
  .conv-summary .note .live-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #4ade80;
    border-radius: 50%;
    margin-right: 6px;
    box-shadow: 0 0 0 0 rgba(74,222,128,0.7);
    animation: livePulse 2s infinite;
    vertical-align: middle;
  }
  @keyframes livePulse {
    0% { box-shadow: 0 0 0 0 rgba(74,222,128,0.7); }
    70% { box-shadow: 0 0 0 8px rgba(74,222,128,0); }
    100% { box-shadow: 0 0 0 0 rgba(74,222,128,0); }
  }
  .funnel-list { padding: 8px 0; }
  .funnel-row {
    padding: 12px 22px 14px;
    border-bottom: 1px solid #f3f4f6;
    transition: background 0.15s;
  }
  .funnel-row:last-child { border-bottom: none; }
  .funnel-row:hover { background: #f9fafb; }
  .funnel-row .top {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 8px;
  }
  .funnel-row .name {
    font-weight: 600;
    font-size: 14.5px;
    color: #1f2937;
    flex: 1;
    min-width: 0;
  }
  .funnel-row .count {
    font-weight: 700;
    font-size: 18px;
    color: #1f2937;
    white-space: nowrap;
  }
  .funnel-row .pct {
    font-weight: 600;
    font-size: 14px;
    color: #6b7280;
    min-width: 56px;
    text-align: right;
    white-space: nowrap;
  }
  .funnel-row .progress {
    height: 10px;
    background: #f3f4f6;
    border-radius: 6px;
    overflow: hidden;
  }
  .funnel-row .progress-fill {
    height: 100%;
    border-radius: 6px;
    transition: width 0.4s ease;
    background: linear-gradient(90deg, #6366f1, #818cf8);
  }
  .funnel-row.bad .count { color: #dc2626; }
  .funnel-row.bad .progress-fill { background: linear-gradient(90deg, #ef4444, #f87171); }
  .funnel-row.warn .count { color: #d97706; }
  .funnel-row.warn .progress-fill { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
  .funnel-row.info .count { color: #2563eb; }
  .funnel-row.info .progress-fill { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
  .funnel-row.good .count { color: #059669; }
  .funnel-row.good .progress-fill { background: linear-gradient(90deg, #10b981, #34d399); }
  .funnel-row.success .count { color: #0d9488; }
  .funnel-row.success .progress-fill { background: linear-gradient(90deg, #14b8a6, #2dd4bf); }
  .funnel-row.purple .count { color: #7c3aed; }
  .funnel-row.purple .progress-fill { background: linear-gradient(90deg, #8b5cf6, #a78bfa); }
  /* "Sifatli lead" — yig'indi qatori, ajratib ko'rsatiladi */
  .funnel-row.highlight {
    background: linear-gradient(90deg, #ecfdf5 0%, #f0fdf4 100%);
    border-left: 4px solid #10b981;
    padding-left: 18px;
  }
  .funnel-row.highlight .name {
    font-weight: 700;
    font-size: 15px;
    color: #065f46;
  }
  .funnel-row.highlight .name::before {
    content: "\2728  ";
    margin-right: 2px;
  }
  .funnel-row.highlight .count { font-size: 20px; }
  .funnel-row.highlight .progress { height: 12px; }
  .funnel-empty {
    padding: 28px 22px;
    text-align: center;
    color: #9ca3af;
    font-size: 14px;
  }

  footer {
    text-align: center;
    color: #9ca3af;
    font-size: 13px;
    margin-top: 40px;
    padding: 20px;
  }

  /* ============ Mobil ekranlar uchun ============ */
  @media (max-width: 768px) {
    body { padding: 12px; }
    .container { padding: 0; }
    header { padding: 18px 16px; border-radius: 12px; margin-bottom: 14px; }
    header h1 { font-size: 20px; line-height: 1.25; }
    header .sub { font-size: 12px; }
    .filter-bar { padding: 12px 14px; gap: 8px; margin-bottom: 16px; border-radius: 10px; }
    .filter-bar .label { font-size: 12px; margin-right: 0; }
    .preset-btn, .apply-btn { padding: 7px 12px; font-size: 13px; }
    input[type="date"] { padding: 6px 8px; font-size: 13px; }
    .section-title { font-size: 15px; margin: 18px 0 10px; }
    .kpi-grid { grid-template-columns: repeat(2, 1fr) !important; gap: 10px; }
    .kpi { padding: 12px 14px; }
    .kpi .label { font-size: 12px; }
    .kpi .value { font-size: 26px; }
    .kpi .sub { font-size: 11px; }
    table { font-size: 12px; }
    th, td { padding: 8px 6px; }
    /* Modal ham qulay bo'lsin */
    #nameEditOverlay > div { padding: 16px !important; }
    /* Yangilash tugmasi */
    #hardRefreshBtn { font-size: 12px; padding: 6px 10px; }
    /* Konversiya kartasi mobil uchun */
    .conv-summary { padding: 16px 18px; }
    .conv-summary .total-block .total-num { font-size: 30px; }
    .conv-summary .note {
      max-width: 100%;
      text-align: left;
      font-size: 11.5px;
      padding: 8px 12px;
    }
    .funnel-row { padding: 10px 16px 12px; }
    .funnel-row .name { font-size: 13px; }
    .funnel-row .count { font-size: 16px; }
    .funnel-row .pct { font-size: 12.5px; min-width: 48px; }
  }

  @media (max-width: 480px) {
    .kpi-grid { grid-template-columns: 1fr !important; }
    header h1 { font-size: 18px; }
    .filter-bar { flex-direction: column; align-items: stretch; }
    .filter-bar > * { width: 100%; }
    select#mgrFilter { min-width: 0 !important; width: 100%; }
  }
</style>
</head>
<body>
<div class="container">
  <header>
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;flex-wrap:wrap">
      <div style="flex:1;min-width:0">
        <h1>📊 amoCRM Dashboard — Salohiyat</h1>
        <div class="sub">Yangilangan: __GENERATED_AT__ · Ma'lumotlar: oxirgi __DAYS_BACK__ kun · Qo'ng'iroqlar manbai: <b>__CALLS_SOURCE__</b></div>
      </div>
      <button id="hardRefreshBtn" title="Eng yangi versiyasini olish (kesh tozalanadi)"
              style="background:rgba(255,255,255,0.18);border:1px solid rgba(255,255,255,0.3);color:white;padding:8px 14px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap">
        🔄 Yangilash
      </button>
    </div>
  </header>

  <div class="filter-bar">
    <span class="label">📅 Davr:</span>
    <button class="preset-btn" data-preset="today">Bugun</button>
    <button class="preset-btn" data-preset="yesterday">Kecha</button>
    <button class="preset-btn" data-preset="7">Oxirgi 7 kun</button>
    <button class="preset-btn active" data-preset="30">Oxirgi 30 kun</button>
    <span style="color:#d1d5db">|</span>
    <input type="date" id="dateFrom"> –
    <input type="date" id="dateTo">
    <button class="apply-btn" id="applyBtn">Qo'llash</button>
    <span class="range-info" id="rangeInfo"></span>
  </div>
  <div class="filter-bar" style="margin-top:-10px">
    <span class="label">👤 Sotuvchi:</span>
    <select id="mgrFilter" style="padding:7px 10px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;font-family:inherit;min-width:200px">
      <option value="">Barchasi</option>
    </select>
    <button id="editNamesBtn" style="background:#eef2ff;border:1px solid #c7d2fe;color:#3730a3;padding:7px 12px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer">✏️ Ismlarni tahrirlash</button>
    <span class="range-info" id="mgrInfo"></span>
  </div>

  <!-- Ism tahrirlash modal -->
  <div id="nameEditOverlay" style="display:none;position:fixed;inset:0;background:rgba(15,23,42,0.5);z-index:1000;align-items:center;justify-content:center">
    <div style="background:white;border-radius:14px;padding:24px;max-width:520px;width:92%;max-height:80vh;overflow-y:auto;box-shadow:0 20px 50px rgba(0,0,0,0.25)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <h3 style="margin:0;font-size:18px;color:#111827">✏️ Sotuvchi ismlarini tahrirlash</h3>
        <button id="nameEditClose" style="background:none;border:none;font-size:22px;cursor:pointer;color:#6b7280;line-height:1">×</button>
      </div>
      <p style="color:#6b7280;font-size:13px;margin:0 0 14px 0">
        Quyida har bir sotuvchining hozirgi raqamlari ko'rsatilgan. Ismlarni o'zgartiring va saqlang.
        O'zgarishlar shu brauzerda saqlanadi va dashboard yangilanganda ham qoladi.
      </p>
      <div id="nameEditList" style="display:flex;flex-direction:column;gap:10px;margin-bottom:18px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="nameEditReset" style="background:#fef2f2;border:1px solid #fecaca;color:#991b1b;padding:8px 14px;border-radius:8px;font-size:13px;cursor:pointer">Asl holatga qaytarish</button>
        <button id="nameEditSave" style="background:#1d4ed8;border:none;color:white;padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer">Saqlash</button>
      </div>
    </div>
  </div>

  <div class="section-title">🔹 Asosiy ko'rsatkichlar</div>
  <div class="kpi-grid">
    <div class="kpi blue">
      <div class="label">Qo'ng'iroqlar</div>
      <div class="value" id="kpi-total-calls">–</div>
      <div class="sub" id="kpi-total-calls-sub"></div>
    </div>
    <div class="kpi green">
      <div class="label">Javob berilgan</div>
      <div class="value" id="kpi-answered">–</div>
      <div class="sub" id="kpi-answer-rate"></div>
    </div>
    <div class="kpi red">
      <div class="label">Javobsiz</div>
      <div class="value" id="kpi-missed">–</div>
    </div>
    <div class="kpi purple">
      <div class="label">Kiruvchi / Chiquvchi</div>
      <div class="value" id="kpi-in-out">–</div>
    </div>
    <div class="kpi teal">
      <div class="label">O'rtacha gaplashish</div>
      <div class="value" id="kpi-avg-duration">–</div>
      <div class="sub">javob berilganlar bo'yicha</div>
    </div>
    <div class="kpi orange">
      <div class="label">Umumiy gaplashish</div>
      <div class="value" id="kpi-total-duration">–</div>
      <div class="sub" id="kpi-total-duration-sub"></div>
    </div>
    <div class="kpi blue">
      <div class="label">Kunlik o'rtacha</div>
      <div class="value" id="kpi-avg-daily-duration">–</div>
      <div class="sub" id="kpi-avg-daily-duration-sub"></div>
    </div>
  </div>

  <div class="section-title">🔹 Leadlar (Kechki guruhlar)</div>
  <div class="kpi-grid">
    <div class="kpi blue">
      <div class="label">Yangi leadlar</div>
      <div class="value" id="kpi-total-leads">–</div>
      <div class="sub">Tanlangan davrda</div>
    </div>
    <div class="kpi green">
      <div class="label">26-aprelga yozilgan</div>
      <div class="value" id="kpi-apr26">–</div>
      <div class="sub" id="kpi-conv"></div>
    </div>
    <div class="kpi indigo">
      <div class="label">🔁 Qayta aloqa</div>
      <div class="value" id="kpi-qayta-aloqa">–</div>
      <div class="sub" id="kpi-qayta-aloqa-sub"></div>
    </div>
    <div class="kpi teal">
      <div class="label">💭 O'ylab ko'radi</div>
      <div class="value" id="kpi-oylab-koradi">–</div>
      <div class="sub" id="kpi-oylab-koradi-sub"></div>
    </div>
    <div class="kpi orange">
      <div class="label">Sotilgan</div>
      <div class="value" id="kpi-sold">–</div>
    </div>
    <div class="kpi red">
      <div class="label">Yo'qotilgan</div>
      <div class="value" id="kpi-lost">–</div>
    </div>
  </div>

  <div class="section-title">🔹 Leadlar (Site — faqat Toshkent)</div>
  <div class="kpi-grid">
    <div class="kpi blue">
      <div class="label">Yangi Toshkent leadlar</div>
      <div class="value" id="kpi-site-total">–</div>
      <div class="sub" id="kpi-site-total-sub"></div>
    </div>
    <div class="kpi purple">
      <div class="label">Toshkent bosqichida</div>
      <div class="value" id="kpi-site-toshkent">–</div>
      <div class="sub">filtrlangan, keyingi bosqichga o'tmagan</div>
    </div>
    <div class="kpi teal">
      <div class="label">Jarayonda</div>
      <div class="value" id="kpi-site-in-progress">–</div>
    </div>
    <div class="kpi orange">
      <div class="label">Sotilgan</div>
      <div class="value" id="kpi-site-sold">–</div>
    </div>
    <div class="kpi red">
      <div class="label">Yo'qotilgan</div>
      <div class="value" id="kpi-site-lost">–</div>
    </div>
  </div>

  <div class="section-title">👤 Sotuvchi bo'yicha batafsil hisobot <span id="mgr-detail-title" style="color:#9ca3af;font-weight:500;font-size:14px"></span></div>
  <div class="kpi-grid">
    <div class="kpi blue">
      <div class="label">Kunlik o'rtacha</div>
      <div class="value" id="mgr-calls-per-day">–</div>
      <div class="sub">qo'ng'iroq / kun</div>
    </div>
    <div class="kpi indigo">
      <div class="label">Kiruvchi vs Chiquvchi</div>
      <div class="value" id="mgr-in-out-pct">–</div>
      <div class="sub" id="mgr-in-out-count">–</div>
    </div>
    <div class="kpi teal">
      <div class="label">O'rt qo'ng'iroq davomi</div>
      <div class="value" id="mgr-avg-dur">–</div>
      <div class="sub">javob berilganlar bo'yicha</div>
    </div>
    <div class="kpi orange">
      <div class="label">Kunlik gaplashish</div>
      <div class="value" id="mgr-daily-dur">–</div>
      <div class="sub" id="mgr-daily-dur-sub"></div>
    </div>
  </div>

  <div class="chart-grid">
    <div class="chart-card" style="grid-column: 1/-1">
      <h3>📞 Soatlar bo'yicha qo'ng'iroqlar soni (00:00 – 23:00)</h3>
      <canvas id="chart9" style="max-height: 280px"></canvas>
    </div>
    <div class="chart-card" style="grid-column: 1/-1">
      <h3>⏱️ Soatlar bo'yicha gaplashish vaqti (daqiqa)</h3>
      <canvas id="chart10" style="max-height: 280px"></canvas>
    </div>
  </div>

  <div class="kpi-grid">
    <div class="kpi green">
      <div class="label">Kiruvchi qo'ng'iroqlar</div>
      <div class="value" id="mgr-in-total">–</div>
      <div class="sub" id="mgr-in-breakdown"></div>
    </div>
    <div class="kpi purple">
      <div class="label">Chiquvchi qo'ng'iroqlar</div>
      <div class="value" id="mgr-out-total">–</div>
      <div class="sub" id="mgr-out-breakdown"></div>
    </div>
    <div class="kpi pink">
      <div class="label">Javob olish darajasi</div>
      <div class="value" id="mgr-answer-rate">–</div>
      <div class="sub" id="mgr-answer-breakdown"></div>
    </div>
  </div>

  <div class="section-title">📈 Grafiklar</div>
  <div class="chart-grid">
    <div class="chart-card">
      <h3>Qo'ng'iroqlar javob darajasi</h3>
      <canvas id="chart1"></canvas>
    </div>
    <div class="chart-card">
      <h3>Yo'nalish: Kiruvchi vs Chiquvchi</h3>
      <canvas id="chart2"></canvas>
    </div>
    <div class="chart-card">
      <h3>Leadlar holati</h3>
      <canvas id="chart3"></canvas>
    </div>
    <div class="chart-card">
      <h3>Kunlik lead oqimi</h3>
      <canvas id="chart4"></canvas>
    </div>
    <div class="chart-card" style="grid-column: 1/-1">
      <h3>Kunlik qo'ng'iroqlar dinamikasi</h3>
      <canvas id="chart5" style="max-height: 300px"></canvas>
    </div>
    <div class="chart-card" style="grid-column: 1/-1">
      <h3>TOP menejerlar — qo'ng'iroqlar</h3>
      <canvas id="chart6" style="max-height: 400px"></canvas>
    </div>
    <div class="chart-card" style="grid-column: 1/-1">
      <h3>⏱️ Menejerlar bo'yicha o'rtacha gaplashish vaqti (daqiqa)</h3>
      <canvas id="chart7" style="max-height: 400px"></canvas>
    </div>
    <div class="chart-card" style="grid-column: 1/-1">
      <h3>📈 Kunlik gaplashish vaqti — umumiy vs o'rtacha</h3>
      <canvas id="chart8" style="max-height: 320px"></canvas>
    </div>
  </div>

  <div class="section-title">🏆 Menejerlar reytingi</div>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Menejer</th><th>Qo'ng'iroqlar</th><th>Javob</th>
        <th>Javob %</th><th>O'rtacha vaqt</th><th>Umumiy vaqt</th>
        <th>Leadlar</th><th>26-apr</th><th>Sotuv</th><th>Ball</th>
      </tr>
    </thead>
    <tbody id="mgr-tbody"></tbody>
  </table>

  <div class="section-title">🎯 Konversiya — Kechki guruhlar (LIVE holat)</div>
  <div class="conv-card">
    <div class="conv-summary">
      <div class="total-block">
        <div class="total-lbl">Tanlangan davrda umumiy lead</div>
        <div class="total-num" id="conv-total">0</div>
        <div class="total-sub" id="conv-period">—</div>
      </div>
      <div class="note">
        <span class="live-dot"></span>
        <b>Sifatli lead</b> = O'ylab ko'radi + 26-aprel keladi.
        Har bir leadning <b>HOZIRGI</b> statusi — manager bosqichni o'zgartirsa, darhol yangilanadi.
      </div>
    </div>
    <div class="funnel-list" id="funnel-list"></div>
  </div>

  <div class="section-title">🔄 Voronka — Site (Toshkent)</div>
  <table>
    <thead>
      <tr>
        <th>Bosqich</th><th>Leadlar</th><th>%</th><th style="width: 40%">Ulush</th>
      </tr>
    </thead>
    <tbody id="site-funnel-tbody"></tbody>
  </table>

  <footer>
    📞 Salohiyat maktab · __GENERATED_AT__<br>
    Dashboard har 15 minutda avtomatik yangilanadi
  </footer>
</div>

<script>
const RAW = __DATA_JSON__;
const charts = {};
let activePreset = '30';
let activeManager = '';
let lastFrom = 0, lastTo = 0, lastLabel = '';

// ---------- Helpers ----------
function fmtDuration(sec) {
  sec = Math.round(sec || 0);
  if (sec <= 0) return '0:00';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return h + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
  return m + ':' + String(s).padStart(2,'0');
}

function fmtDurationMin(sec) {
  const min = (sec || 0) / 60;
  if (min >= 60) return (min / 60).toFixed(1) + ' soat';
  return min.toFixed(1) + ' min';
}

// ---------- Ism override (foydalanuvchi tahriri, localStorage'da) ----------
const NAME_OVERRIDE_KEY = 'amocrm_dashboard_name_overrides_v1';
function getNameOverrides() {
  try { return JSON.parse(localStorage.getItem(NAME_OVERRIDE_KEY) || '{}') || {}; }
  catch (e) { return {}; }
}
function setNameOverrides(map) {
  try { localStorage.setItem(NAME_OVERRIDE_KEY, JSON.stringify(map)); } catch (e) {}
}
let _nameOverrides = getNameOverrides();

function uname(uid) {
  const key = String(uid);
  if (_nameOverrides[key]) return _nameOverrides[key];
  return RAW.users[key] || "Noma'lum";
}

// Status nomiga qarab rang kategoriyasini aniqlaydi (funnel uchun)
function funnelCategory(name, id) {
  const n = (name || '').toString().toLowerCase();
  // sotilgan / muvaffaqiyatli — yashil-teal
  if (n.includes('sotilgan') || n.includes('muvaffaq') || n.includes('successful') ||
      id === 142 || (RAW.sold_ids && RAW.sold_ids.includes(id))) return 'success';
  // sifatsiz / yo'qotilgan / spam / chiqmadi — qizil
  if (n.includes('sifatsiz') || n.includes("yo'qot") || n.includes('yoqot') ||
      n.includes("yo`qot") || n.includes('spam') || n.includes('lost') ||
      n.includes('bekor') || n.includes('rad etil') ||
      id === 143 || (RAW.lost_ids && RAW.lost_ids.includes(id))) return 'bad';
  // 26-aprel keladi / kelad / tayyor — yashil
  if (id === RAW.apr26_id) return 'good';
  if (n.includes('kelad') || n.includes('tayyor') || n.includes('shartnoma')) return 'good';
  // qayta aloqa / kutmoq — sariq
  if (n.includes('qayta') || n.includes('kut') || id === RAW.qayta_aloqa_id) return 'warn';
  // o'ylab ko'radi / o'ylaydi — binafsha
  if (n.includes("o'ylab") || n.includes('oylab') || n.includes("o`ylab") ||
      id === RAW.oylab_koradi_id) return 'purple';
  // yangi / qabul qilingan / jarayon — ko'k
  return 'info';
}

// ---------- Filter compute ----------
function filterByRange(fromTs, toTs) {
  let leads = RAW.leads.filter(l => l.t >= fromTs && l.t < toTs);
  let calls = RAW.calls.filter(c => c.t >= fromTs && c.t < toTs);
  let site_leads = (RAW.site_leads || []).filter(l => l.t >= fromTs && l.t < toTs);
  if (activeManager) {
    leads = leads.filter(l => uname(l.u) === activeManager);
    calls = calls.filter(c => uname(c.u) === activeManager);
    site_leads = site_leads.filter(l => uname(l.u) === activeManager);
  }
  return { leads, calls, site_leads };
}

function computeSiteStats(site_leads) {
  const total = site_leads.length;
  let at_toshkent = 0, sold = 0, lost = 0;
  const statusCounts = {};
  for (const l of site_leads) {
    statusCounts[l.s] = (statusCounts[l.s] || 0) + 1;
    if (l.s === RAW.site_toshkent_id) at_toshkent++;
    if (RAW.sold_ids.includes(l.s)) sold++;
    if (RAW.lost_ids.includes(l.s)) lost++;
  }
  const in_progress = total - sold - lost;
  const site_funnel = (RAW.site_funnel || []).map(f => ({
    name: f.name, count: statusCounts[f.id] || 0,
    pct: total ? (statusCounts[f.id] || 0) / total : 0,
  })).filter(f => f.count > 0);
  return { total, at_toshkent, sold, lost, in_progress, site_funnel };
}

function computeStats(leads, calls) {
  const total_calls = calls.length;
  let answered = 0, call_in = 0, call_out = 0;
  let total_duration = 0;
  const mgr = {};
  for (const c of calls) {
    const dur = c.d || 0;
    if (dur > 0) { answered++; total_duration += dur; }
    if (c.nt === 'call_in') call_in++;
    else if (c.nt === 'call_out') call_out++;
    const nm = uname(c.u);
    if (!mgr[nm]) mgr[nm] = { calls: 0, answered: 0, duration: 0, leads: 0, apr26: 0, sold: 0 };
    mgr[nm].calls++;
    if (dur > 0) { mgr[nm].answered++; mgr[nm].duration += dur; }
  }
  const missed = total_calls - answered;
  const answer_rate = total_calls ? answered / total_calls : 0;
  const avg_duration = answered ? total_duration / answered : 0;

  const total_leads = leads.length;
  let apr26 = 0, sold = 0, lost = 0;
  let qayta_aloqa = 0, oylab_koradi = 0;
  const statusCounts = {};
  for (const l of leads) {
    statusCounts[l.s] = (statusCounts[l.s] || 0) + 1;
    if (l.s === RAW.apr26_id) apr26++;
    if (RAW.qayta_aloqa_id && l.s === RAW.qayta_aloqa_id) qayta_aloqa++;
    if (RAW.oylab_koradi_id && l.s === RAW.oylab_koradi_id) oylab_koradi++;
    if (RAW.sold_ids.includes(l.s)) sold++;
    if (RAW.lost_ids.includes(l.s)) lost++;
    const nm = uname(l.u);
    if (!mgr[nm]) mgr[nm] = { calls: 0, answered: 0, duration: 0, leads: 0, apr26: 0, sold: 0 };
    mgr[nm].leads++;
    if (l.s === RAW.apr26_id) mgr[nm].apr26++;
    if (RAW.sold_ids.includes(l.s)) mgr[nm].sold++;
  }
  const in_progress = total_leads - sold - lost;
  const conv = total_leads ? apr26 / total_leads : 0;
  const qayta_aloqa_conv = total_leads ? qayta_aloqa / total_leads : 0;
  const oylab_koradi_conv = total_leads ? oylab_koradi / total_leads : 0;

  const mgr_rows = Object.entries(mgr).map(([name, s]) => {
    const score = Math.round(s.calls * 0.3 + s.answered * 0.5 + s.leads * 2 + s.apr26 * 5 + s.sold * 20);
    const ar = s.calls ? s.answered / s.calls : 0;
    const avg_dur = s.answered ? s.duration / s.answered : 0;
    return { name, calls: s.calls, answered: s.answered, answer_rate: ar,
             duration: s.duration, avg_duration: avg_dur,
             duration_min: Math.round(s.duration / 6) / 10,
             leads: s.leads, apr26: s.apr26, sold: s.sold, score };
  }).sort((a, b) => b.score - a.score);

  // Konversiya funnel — yangi struktura (foydalanuvchi xohlagan tartib):
  //   1. Umumiy lead (yuqorida — funnelTotal)
  //   2. Sifatli lead = O'ylab ko'radi + 26-aprel keladi
  //   3. O'ylab ko'radi
  //   4. 26-aprel keladi
  // Umumiy = Sifatsiz + Qayta aloqa + O'ylab + 26-aprel (4 ta asosiy statusning yig'indisi)
  const findStatusName = (id, fallback) => {
    const s = RAW.funnel.find(f => f.id === id);
    return s ? s.name : fallback;
  };
  const isCoreFunnelStatus = (name, id) => {
    const n = (name || '').toLowerCase();
    if (n.includes('sifatsiz')) return true;
    if (RAW.qayta_aloqa_id && id === RAW.qayta_aloqa_id) return true;
    if (RAW.oylab_koradi_id && id === RAW.oylab_koradi_id) return true;
    if (RAW.apr26_id && id === RAW.apr26_id) return true;
    return false;
  };
  const coreFunnel = RAW.funnel
    .filter(f => isCoreFunnelStatus(f.name, f.id))
    .map(f => ({ id: f.id, name: f.name, count: statusCounts[f.id] || 0 }));
  const funnelTotal = coreFunnel.reduce((sum, f) => sum + f.count, 0);

  const oylabCount = RAW.oylab_koradi_id ? (statusCounts[RAW.oylab_koradi_id] || 0) : 0;
  const apr26Count = RAW.apr26_id ? (statusCounts[RAW.apr26_id] || 0) : 0;
  const sifatliCount = oylabCount + apr26Count;
  const pctOf = (n) => funnelTotal ? n / funnelTotal : 0;

  const funnel = [
    { id: '_sifatli', name: 'Sifatli lead', count: sifatliCount,
      pct: pctOf(sifatliCount), category: 'success', isHighlight: true },
    { id: RAW.oylab_koradi_id, name: findStatusName(RAW.oylab_koradi_id, "O\u2018ylab ko\u2018radi"),
      count: oylabCount, pct: pctOf(oylabCount), category: 'purple' },
    { id: RAW.apr26_id, name: findStatusName(RAW.apr26_id, '26-aprel keladi'),
      count: apr26Count, pct: pctOf(apr26Count), category: 'good' },
  ];

  // Kunlik dinamika (Tashkent kuni bo'yicha)
  const TZ_MS = 5 * 3600 * 1000;
  const tashkentKey = ts => {
    const d = new Date(ts * 1000 + TZ_MS);
    return String(d.getUTCDate()).padStart(2,'0') + '.' + String(d.getUTCMonth()+1).padStart(2,'0');
  };
  const daysMap = new Map();
  const callsMap = new Map();
  const durMap = new Map();
  for (const l of leads) {
    const key = tashkentKey(l.t);
    daysMap.set(key, (daysMap.get(key) || 0) + 1);
  }
  for (const c of calls) {
    const key = tashkentKey(c.t);
    if (!callsMap.has(key)) callsMap.set(key, { total: 0, answered: 0 });
    callsMap.get(key).total++;
    const dur = c.d || 0;
    if (dur > 0) callsMap.get(key).answered++;
    if (!durMap.has(key)) durMap.set(key, { total_sec: 0, answered: 0 });
    if (dur > 0) {
      durMap.get(key).total_sec += dur;
      durMap.get(key).answered++;
    }
  }
  const sortKeys = arr => arr.sort((a,b) => {
    const [da,ma] = a[0].split('.').map(Number);
    const [db,mb] = b[0].split('.').map(Number);
    return (ma - mb) || (da - db);
  });
  const daily_leads = sortKeys(Array.from(daysMap.entries()));
  const daily_calls = sortKeys(Array.from(callsMap.entries()));
  const daily_duration = sortKeys(Array.from(durMap.entries()));

  // Soatlar bo'yicha (Tashkent TZ)
  const hourly = [];
  for (let h = 0; h < 24; h++) {
    hourly.push({ h, in_tot:0, in_ans:0, out_tot:0, out_ans:0, dur_in:0, dur_out:0 });
  }
  let in_answered = 0, out_answered = 0;
  for (const c of calls) {
    const d = new Date(c.t * 1000 + TZ_MS);
    const h = d.getUTCHours();
    const dur = c.d || 0;
    if (c.nt === 'call_in') {
      hourly[h].in_tot++;
      if (dur > 0) { hourly[h].in_ans++; hourly[h].dur_in += dur; in_answered++; }
    } else if (c.nt === 'call_out') {
      hourly[h].out_tot++;
      if (dur > 0) { hourly[h].out_ans++; hourly[h].dur_out += dur; out_answered++; }
    }
  }

  return { total_calls, answered, missed, answer_rate, call_in, call_out,
           in_answered, out_answered,
           total_duration, avg_duration,
           total_leads, apr26, sold, lost, in_progress, conv,
           qayta_aloqa, qayta_aloqa_conv,
           oylab_koradi, oylab_koradi_conv,
           mgr_rows, funnel, funnelTotal, daily_leads, daily_calls, daily_duration,
           hourly };
}

// ---------- Rendering ----------
function $(id) { return document.getElementById(id); }

function render(fromTs, toTs, label) {
  lastFrom = fromTs; lastTo = toTs; lastLabel = label;
  const { leads, calls, site_leads } = filterByRange(fromTs, toTs);
  const s = computeStats(leads, calls);
  const ss = computeSiteStats(site_leads);

  $('kpi-total-calls').textContent = s.total_calls;
  $('kpi-total-calls-sub').textContent = s.total_calls + ' ta';
  $('kpi-answered').textContent = s.answered;
  $('kpi-answer-rate').textContent = (s.answer_rate * 100).toFixed(1) + '%';
  $('kpi-missed').textContent = s.missed;
  $('kpi-in-out').textContent = s.call_in + ' / ' + s.call_out;
  $('kpi-avg-duration').textContent = fmtDuration(s.avg_duration);
  $('kpi-total-duration').textContent = fmtDurationMin(s.total_duration);
  $('kpi-total-duration-sub').textContent = fmtDuration(s.total_duration);

  // Kunlik o'rtacha — umumiy / davrdagi kunlar soni
  const days_in_range = Math.max(1, Math.round((toTs - fromTs) / 86400));
  const avg_daily = s.total_duration / days_in_range;
  $('kpi-avg-daily-duration').textContent = fmtDurationMin(avg_daily);
  $('kpi-avg-daily-duration-sub').textContent = days_in_range + ' kun · ' + fmtDuration(avg_daily);

  $('kpi-total-leads').textContent = s.total_leads;
  $('kpi-apr26').textContent = s.apr26;
  $('kpi-conv').textContent = 'Konversiya: ' + (s.conv * 100).toFixed(1) + '%';
  $('kpi-qayta-aloqa').textContent = s.qayta_aloqa;
  $('kpi-qayta-aloqa-sub').textContent = 'Konversiya: ' + (s.qayta_aloqa_conv * 100).toFixed(1) + '%';
  $('kpi-oylab-koradi').textContent = s.oylab_koradi;
  $('kpi-oylab-koradi-sub').textContent = 'Konversiya: ' + (s.oylab_koradi_conv * 100).toFixed(1) + '%';
  $('kpi-sold').textContent = s.sold;
  $('kpi-lost').textContent = s.lost;

  // Site — Toshkent
  $('kpi-site-total').textContent = ss.total;
  $('kpi-site-total-sub').textContent = 'Toshkent sifatli';
  $('kpi-site-toshkent').textContent = ss.at_toshkent;
  $('kpi-site-in-progress').textContent = ss.in_progress;
  $('kpi-site-sold').textContent = ss.sold;
  $('kpi-site-lost').textContent = ss.lost;

  // ---------- Per-sotuvchi batafsil hisobot ----------
  $('mgr-detail-title').textContent = activeManager
    ? '— ' + activeManager
    : '— Barcha sotuvchilar bo\u2019yicha umumiy';

  $('mgr-calls-per-day').textContent = (s.total_calls / days_in_range).toFixed(1);

  const tt = s.total_calls || 1;
  const in_pct = Math.round(s.call_in / tt * 100);
  const out_pct = Math.round(s.call_out / tt * 100);
  $('mgr-in-out-pct').textContent = in_pct + '% / ' + out_pct + '%';
  $('mgr-in-out-count').textContent = s.call_in + ' kiruvchi · ' + s.call_out + ' chiquvchi';

  $('mgr-avg-dur').textContent = fmtDuration(s.avg_duration);
  $('mgr-daily-dur').textContent = fmtDurationMin(avg_daily);
  $('mgr-daily-dur-sub').textContent = days_in_range + ' kun · ' + fmtDuration(avg_daily);

  const in_miss = s.call_in - s.in_answered;
  const out_miss = s.call_out - s.out_answered;
  $('mgr-in-total').textContent = s.call_in;
  $('mgr-in-breakdown').textContent = '✅ ' + s.in_answered + ' javob · ❌ ' + in_miss + ' javobsiz';
  $('mgr-out-total').textContent = s.call_out;
  $('mgr-out-breakdown').textContent = '✅ ' + s.out_answered + ' javob · ❌ ' + out_miss + ' javobsiz';
  $('mgr-answer-rate').textContent = (s.answer_rate * 100).toFixed(1) + '%';
  $('mgr-answer-breakdown').textContent = s.answered + ' javob / ' + s.total_calls + ' jami';

  $('rangeInfo').textContent = label;
  $('mgrInfo').textContent = activeManager
    ? '→ ' + activeManager + ' bo\u2019yicha'
    : 'Barcha menejerlar';

  // Manager table
  const medals = ['🥇','🥈','🥉'];
  $('mgr-tbody').innerHTML = s.mgr_rows.slice(0, 15).map((m, i) => `
    <tr>
      <td class="rank">${i < 3 ? medals[i] : i+1}</td>
      <td class="name">${m.name}</td>
      <td>${m.calls}</td>
      <td>${m.answered}</td>
      <td>${(m.answer_rate*100).toFixed(1)}%</td>
      <td>${fmtDuration(m.avg_duration)}</td>
      <td>${fmtDurationMin(m.duration)}</td>
      <td>${m.leads}</td>
      <td>${m.apr26}</td>
      <td>${m.sold}</td>
      <td class="score">${m.score}</td>
    </tr>`).join('');

  // Konversiya (LIVE) — Umumiy + Sifatli + O'ylab + 26-aprel
  $('conv-total').textContent = s.funnelTotal + ' ta';
  $('conv-period').textContent = label ? ('Davr: ' + label) : '';
  if (s.funnelTotal === 0) {
    $('funnel-list').innerHTML = '<div class="funnel-empty">Bu davrda asosiy statuslarda leadlar yo\u2018q</div>';
  } else {
    $('funnel-list').innerHTML = s.funnel.map(f => {
      const cat = f.category || funnelCategory(f.name, f.id);
      const highlightCls = f.isHighlight ? ' highlight' : '';
      return `
      <div class="funnel-row ${cat}${highlightCls}">
        <div class="top">
          <div class="name">${f.name}</div>
          <div class="count">${f.count} ta</div>
          <div class="pct">${(f.pct*100).toFixed(1)}%</div>
        </div>
        <div class="progress"><div class="progress-fill" style="width:${Math.max(2, f.pct*100)}%"></div></div>
      </div>`;
    }).join('');
  }

  // Site funnel table
  $('site-funnel-tbody').innerHTML = ss.site_funnel.map(f => `
    <tr>
      <td class="name">${f.name}</td>
      <td>${f.count}</td>
      <td>${(f.pct*100).toFixed(1)}%</td>
      <td><div class="bar" style="width:${Math.max(2, f.pct*100)}%"></div></td>
    </tr>`).join('');

  // Charts
  drawCharts(s);
}

function drawCharts(s) {
  const dl_labels = s.daily_leads.map(d => d[0]);
  const dl_data = s.daily_leads.map(d => d[1]);
  const dc_labels = s.daily_calls.map(d => d[0]);
  const dc_total = s.daily_calls.map(d => d[1].total);
  const dc_answered = s.daily_calls.map(d => d[1].answered);
  const topMgr = s.mgr_rows.slice(0, 10);

  // O'rtacha gaplashish vaqti (min) — faqat javob bergan menejerlar
  const mgrByAvg = s.mgr_rows
    .filter(m => m.answered > 0)
    .slice()
    .sort((a,b) => b.avg_duration - a.avg_duration)
    .slice(0, 15);
  const mgr_names = mgrByAvg.map(m => m.name);
  const mgr_avg_min = mgrByAvg.map(m => +(m.avg_duration / 60).toFixed(2));
  const mgr_total_min = mgrByAvg.map(m => +(m.duration / 60).toFixed(1));

  // Kunlik gaplashish vaqti (minutda)
  const dd_labels = s.daily_duration.map(d => d[0]);
  const dd_total_min = s.daily_duration.map(d => +(d[1].total_sec / 60).toFixed(1));
  const dd_avg_min = s.daily_duration.map(d => {
    const a = d[1].answered;
    return a ? +((d[1].total_sec / a) / 60).toFixed(2) : 0;
  });

  const specs = {
    chart1: { type: 'doughnut',
      data: { labels: ['Javob berilgan', 'Javobsiz'],
        datasets: [{ data: [s.answered, s.missed], backgroundColor: ['#10b981', '#ef4444'], borderWidth: 0 }] },
      options: { plugins: { legend: { position: 'bottom' } }, cutout: '60%' } },
    chart2: { type: 'doughnut',
      data: { labels: ['Kiruvchi', 'Chiquvchi'],
        datasets: [{ data: [s.call_in, s.call_out], backgroundColor: ['#6366f1', '#f59e0b'], borderWidth: 0 }] },
      options: { plugins: { legend: { position: 'bottom' } }, cutout: '60%' } },
    chart3: { type: 'doughnut',
      data: { labels: ['Jarayonda', 'Sotilgan', "Yo'qotilgan"],
        datasets: [{ data: [s.in_progress, s.sold, s.lost], backgroundColor: ['#3b82f6', '#10b981', '#ef4444'], borderWidth: 0 }] },
      options: { plugins: { legend: { position: 'bottom' } }, cutout: '60%' } },
    chart4: { type: 'line',
      data: { labels: dl_labels,
        datasets: [{ label: 'Yangi leadlar', data: dl_data, borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,0.12)', fill: true, tension: 0.3,
          pointRadius: 4, pointBackgroundColor: '#3b82f6' }] },
      options: { plugins: { legend: { display: false } } } },
    chart5: { type: 'bar',
      data: { labels: dc_labels,
        datasets: [
          { label: 'Jami', data: dc_total, backgroundColor: '#c7d2fe' },
          { label: 'Javob', data: dc_answered, backgroundColor: '#10b981' }
        ] },
      options: { plugins: { legend: { position: 'bottom' } } } },
    chart6: { type: 'bar',
      data: { labels: topMgr.map(m => m.name),
        datasets: [{ label: "Qo'ng'iroqlar", data: topMgr.map(m => m.calls), backgroundColor: '#3b82f6' }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false } } } },
    chart7: { type: 'bar',
      data: { labels: mgr_names,
        datasets: [
          { label: "O'rtacha vaqt (min)", data: mgr_avg_min, backgroundColor: '#14b8a6' },
          { label: "Umumiy vaqt (min)", data: mgr_total_min, backgroundColor: '#f59e0b' },
        ] },
      options: { indexAxis: 'y',
        plugins: { legend: { position: 'bottom' },
          tooltip: { callbacks: { label: ctx => {
            const v = ctx.parsed.x;
            return ctx.dataset.label + ': ' + (v >= 60
              ? (v/60).toFixed(1) + ' soat'
              : v.toFixed(1) + ' min');
          } } } },
        scales: { x: { title: { display: true, text: 'Daqiqa' } } } } },
    chart8: { type: 'bar',
      data: { labels: dd_labels,
        datasets: [
          { type: 'bar', label: 'Umumiy gaplashish (min)', data: dd_total_min,
            backgroundColor: '#a5b4fc', yAxisID: 'y' },
          { type: 'line', label: "O'rtacha vaqt (min)", data: dd_avg_min,
            borderColor: '#10b981', backgroundColor: '#10b981',
            fill: false, tension: 0.3, pointRadius: 4, yAxisID: 'y1' },
        ] },
      options: { plugins: { legend: { position: 'bottom' } },
        scales: {
          y: { position: 'left', title: { display: true, text: 'Umumiy (min)' } },
          y1: { position: 'right', title: { display: true, text: "O'rtacha (min)" },
                grid: { drawOnChartArea: false } },
        } } },
    chart9: { type: 'line',
      data: {
        labels: s.hourly.map(h => String(h.h).padStart(2,'0') + ':00'),
        datasets: [
          { label: 'Kiruvchi', data: s.hourly.map(h => h.in_tot),
            borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.15)',
            fill: true, tension: 0.3, pointRadius: 3 },
          { label: 'Chiquvchi', data: s.hourly.map(h => h.out_tot),
            borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.12)',
            fill: true, tension: 0.3, pointRadius: 3 },
        ] },
      options: { plugins: { legend: { position: 'bottom' } },
        scales: { y: { beginAtZero: true, title: { display: true, text: "Qo'ng'iroqlar soni" } } } } },
    chart10: { type: 'bar',
      data: {
        labels: s.hourly.map(h => String(h.h).padStart(2,'0') + ':00'),
        datasets: [
          { label: 'Kiruvchi (min)',
            data: s.hourly.map(h => +(h.dur_in / 60).toFixed(1)),
            backgroundColor: '#10b981', stack: 'd' },
          { label: 'Chiquvchi (min)',
            data: s.hourly.map(h => +(h.dur_out / 60).toFixed(1)),
            backgroundColor: '#8b5cf6', stack: 'd' },
        ] },
      options: { plugins: { legend: { position: 'bottom' } },
        scales: {
          x: { stacked: true },
          y: { stacked: true, beginAtZero: true, title: { display: true, text: 'Daqiqa' } }
        } } },
  };

  for (const id of Object.keys(specs)) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(document.getElementById(id), specs[id]);
  }
}

// ---------- Preset handlers (Tashkent TZ: UTC+5) ----------
const TZ_OFFSET_MS = 5 * 3600 * 1000;

// Tashkent'dagi "bugun" boshlanishini UTC Date sifatida qaytaradi.
// dayOffset=0 → bugun, -1 → kecha, +1 → ertaga.
function tashkentDayStart(dayOffset) {
  const now = new Date();
  const shifted = new Date(now.getTime() + TZ_OFFSET_MS);
  const y = shifted.getUTCFullYear();
  const m = shifted.getUTCMonth();
  const d = shifted.getUTCDate() + (dayOffset || 0);
  // Tashkent midnight = UTC midnight shu kuni, 5 soat ayrilgan
  return new Date(Date.UTC(y, m, d) - TZ_OFFSET_MS);
}

// Tashkent kun raqamini olish (display uchun)
function fmtTashkent(d) {
  const shifted = new Date(d.getTime() + TZ_OFFSET_MS);
  return String(shifted.getUTCDate()).padStart(2,'0') + '.' +
         String(shifted.getUTCMonth()+1).padStart(2,'0') + '.' + shifted.getUTCFullYear();
}

function applyPreset(key) {
  activePreset = key;
  document.querySelectorAll('.preset-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.preset === key);
  });

  let from, to, label;

  if (key === 'today') {
    from = tashkentDayStart(0);
    to = tashkentDayStart(1);
    label = 'Bugun: ' + fmtTashkent(from);
  } else if (key === 'yesterday') {
    from = tashkentDayStart(-1);
    to = tashkentDayStart(0);
    label = 'Kecha: ' + fmtTashkent(from);
  } else if (key === '7') {
    from = tashkentDayStart(-6);
    to = tashkentDayStart(1);
    label = "Oxirgi 7 kun";
  } else {
    from = tashkentDayStart(-(RAW.days_back - 1));
    to = tashkentDayStart(1);
    label = 'Oxirgi ' + RAW.days_back + ' kun';
  }

  // Update date inputs (Tashkent kunini ko'rsatamiz)
  $('dateFrom').value = toDateInputTashkent(from);
  $('dateTo').value = toDateInputTashkent(new Date(to.getTime() - 86400000));

  render(Math.floor(from.getTime()/1000), Math.floor(to.getTime()/1000), label);
}

function toDateInputTashkent(d) {
  const s = new Date(d.getTime() + TZ_OFFSET_MS);
  return s.getUTCFullYear() + '-' +
         String(s.getUTCMonth()+1).padStart(2,'0') + '-' +
         String(s.getUTCDate()).padStart(2,'0');
}

function applyCustom() {
  const fromStr = $('dateFrom').value;
  const toStr = $('dateTo').value;
  if (!fromStr || !toStr) return;
  // Tashkent midnight uchun: 'YYYY-MM-DDT00:00:00+05:00'
  const from = new Date(fromStr + 'T00:00:00+05:00');
  const to = new Date(toStr + 'T00:00:00+05:00');
  to.setTime(to.getTime() + 86400000); // inclusive
  document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
  const label = fmtTashkent(from) + ' – ' + fmtTashkent(new Date(to.getTime() - 86400000));
  render(Math.floor(from.getTime()/1000), Math.floor(to.getTime()/1000), label);
}

function populateManagerDropdown() {
  // Faol menejerlarni (qo'ng'iroq yoki lead'i bor) chiqaramiz
  const active = new Set();
  for (const c of RAW.calls) active.add(uname(c.u));
  for (const l of RAW.leads) active.add(uname(l.u));
  for (const l of (RAW.site_leads || [])) active.add(uname(l.u));
  active.delete("Noma'lum");
  const sel = $('mgrFilter');
  const names = Array.from(active).sort((a,b) => a.localeCompare(b, 'uz'));
  for (const nm of names) {
    const o = document.createElement('option');
    o.value = nm; o.textContent = nm;
    sel.appendChild(o);
  }
  sel.addEventListener('change', () => {
    activeManager = sel.value;
    if (lastFrom && lastTo) render(lastFrom, lastTo, lastLabel);
  });
}

document.querySelectorAll('.preset-btn').forEach(btn => {
  btn.addEventListener('click', () => applyPreset(btn.dataset.preset));
});
$('applyBtn').addEventListener('click', applyCustom);

populateManagerDropdown();

// ---------- Ism tahrirlash modal ----------
function fmtSecsShort(s) {
  s = s || 0;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  if (h > 0) return h + 'soat ' + m + 'min';
  return m + 'min';
}

function openNameEditor() {
  // Har bir user_id uchun: hozirgi ism, qo'ng'iroqlar soni, javob berilgan, gaplashish vaqti
  // Kontekst: 30 kunlik ma'lumot bilan ko'rsatamiz
  const userStats = {};
  for (const c of RAW.calls) {
    const k = String(c.u);
    if (!userStats[k]) userStats[k] = { total: 0, answered: 0, dur: 0 };
    userStats[k].total += 1;
    if ((c.d || 0) > 0) {
      userStats[k].answered += 1;
      userStats[k].dur += c.d;
    }
  }
  // Lead'lar bo'yicha ham (qo'ng'iroq qilmagan, lekin lead'lar bor menejer)
  for (const l of RAW.leads) {
    const k = String(l.u);
    if (!userStats[k]) userStats[k] = { total: 0, answered: 0, dur: 0 };
  }

  // Faqat aktiv user'lar (ma'lumoti borlari)
  const activeIds = Object.keys(userStats).filter(k => k && k !== 'undefined' && k !== 'null');
  // Qo'ng'iroqlar bo'yicha kamayish tartibida
  activeIds.sort((a, b) => (userStats[b].total - userStats[a].total));

  const list = $('nameEditList');
  list.innerHTML = '';

  if (activeIds.length === 0) {
    list.innerHTML = '<div style="color:#9ca3af;font-size:13px">Hech qanday sotuvchi topilmadi.</div>';
  }

  for (const uid of activeIds) {
    const st = userStats[uid];
    const origName = RAW.users[uid] || ('User ' + uid);
    const curName = _nameOverrides[uid] || origName;
    const row = document.createElement('div');
    row.style.cssText = 'border:1px solid #e5e7eb;border-radius:10px;padding:10px 12px;background:#f9fafb';
    row.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <input data-uid="${uid}" class="name-edit-input" type="text" value="${curName.replace(/"/g, '&quot;')}"
               style="flex:1;min-width:160px;padding:7px 10px;border:1px solid #d1d5db;border-radius:7px;font-size:14px;font-family:inherit"/>
        <span style="font-size:12px;color:#6b7280;white-space:nowrap">
          📞 <b style="color:#1d4ed8">${st.total}</b>
          · ✓ <b style="color:#059669">${st.answered}</b>
          · ⏱ <b>${fmtSecsShort(st.dur)}</b>
        </span>
      </div>
      <div style="font-size:11px;color:#9ca3af;margin-top:4px">
        Asl: ${origName}${_nameOverrides[uid] ? ' (override)' : ''}
      </div>
    `;
    list.appendChild(row);
  }

  $('nameEditOverlay').style.display = 'flex';
}

function closeNameEditor() {
  $('nameEditOverlay').style.display = 'none';
}

function saveNameEdits() {
  const inputs = document.querySelectorAll('.name-edit-input');
  const newOverrides = {};
  for (const inp of inputs) {
    const uid = inp.dataset.uid;
    const newName = (inp.value || '').trim();
    const origName = RAW.users[uid] || ('User ' + uid);
    // Faqat asl ismdan farq qilsa override saqlaymiz
    if (newName && newName !== origName) {
      newOverrides[uid] = newName;
    }
  }
  _nameOverrides = newOverrides;
  setNameOverrides(newOverrides);
  closeNameEditor();

  // Dropdown'ni qaytadan to'ldiramiz va render qaytadan
  const sel = $('mgrFilter');
  // Eski activeManager nomi yangilangan bo'lishi mumkin — bo'shatamiz
  activeManager = '';
  while (sel.options.length > 1) sel.remove(1);
  populateManagerDropdown();
  if (lastFrom && lastTo) render(lastFrom, lastTo, lastLabel);
}

function resetNameEdits() {
  if (!confirm("Barcha ism o'zgarishlarini o'chirib, asl holatga qaytarmoqchimisiz?")) return;
  _nameOverrides = {};
  setNameOverrides({});
  closeNameEditor();
  const sel = $('mgrFilter');
  activeManager = '';
  while (sel.options.length > 1) sel.remove(1);
  populateManagerDropdown();
  if (lastFrom && lastTo) render(lastFrom, lastTo, lastLabel);
}

$('editNamesBtn').addEventListener('click', openNameEditor);
$('nameEditClose').addEventListener('click', closeNameEditor);
$('nameEditSave').addEventListener('click', saveNameEdits);
$('nameEditReset').addEventListener('click', resetNameEdits);
$('nameEditOverlay').addEventListener('click', (e) => {
  if (e.target.id === 'nameEditOverlay') closeNameEditor();
});

// Manual yangilash tugmasi (header'da)
const _hardRefreshBtn = document.getElementById('hardRefreshBtn');
if (_hardRefreshBtn) {
  _hardRefreshBtn.addEventListener('click', function () {
    const url = new URL(window.location.href);
    url.searchParams.set('v', Date.now());
    window.location.replace(url.toString());
  });
}

// Dastlabki render — oxirgi 30 kun
applyPreset('30');

// ---------- Avtomatik yangilanish (kesh-buster bilan) ----------
// Har 10 daqiqada sahifa o'zini qayta yuklaydi va URL'ga ?v=timestamp qo'shadi —
// shunda telefon/brauzer/CDN eski keshlangan versiyani ishlatmaydi.
function reloadWithCacheBust() {
  const url = new URL(window.location.href);
  url.searchParams.set('v', Date.now());
  window.location.replace(url.toString());
}
setTimeout(reloadWithCacheBust, 10 * 60 * 1000);

// Telefon ekranini ochganda (har safar) — agar 1+ daqiqa o'tgan bo'lsa, yangilaymiz
let _pageLoadedAt = Date.now();
document.addEventListener('visibilitychange', function () {
  if (document.visibilityState === 'visible') {
    const ageMin = (Date.now() - _pageLoadedAt) / 60000;
    if (ageMin > 1) {
      reloadWithCacheBust();
    }
  }
});

// Ma'lumot eskirib qolganini foydalanuvchiga ko'rsatamiz (15+ daqiqa)
function checkDataFreshness() {
  const subEl = document.querySelector('header .sub');
  if (!subEl) return;
  const m = subEl.textContent.match(/Yangilangan:\s*(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})/);
  if (!m) return;
  // UTC+5 (Toshkent) zonasi
  const dataTime = new Date(Date.UTC(
    parseInt(m[3]), parseInt(m[2]) - 1, parseInt(m[1]),
    parseInt(m[4]) - 5, parseInt(m[5])  // -5 to convert to UTC
  ));
  const ageMin = (Date.now() - dataTime.getTime()) / 60000;
  if (ageMin > 25 && !document.getElementById('staleWarning')) {
    const warn = document.createElement('div');
    warn.id = 'staleWarning';
    warn.style.cssText = 'background:#fef3c7;border:1px solid #fcd34d;color:#92400e;padding:10px 14px;border-radius:8px;margin-bottom:14px;font-size:13px;text-align:center';
    warn.innerHTML = `\u26A0\uFE0F Ma\u2019lumot eskirgan (${Math.floor(ageMin)} daqiqa avval) \u2014 <b style="cursor:pointer;text-decoration:underline" onclick="reloadWithCacheBust()">Yangilash</b>`;
    const container = document.querySelector('.container');
    const header = document.querySelector('header');
    if (container && header) container.insertBefore(warn, header.nextSibling);
  }
}
setTimeout(checkDataFreshness, 1000);
setInterval(checkDataFreshness, 60 * 1000);
</script>
</body>
</html>"""

    calls_source = data.get("calls_source", "amocrm")
    source_label = {
        "moizvonki": "Moi Zvonki (PBX)",
        "amocrm": "amoCRM call notes",
        "amocrm_fallback": "amoCRM (zaxira — Moi Zvonki ishlamadi)",
    }.get(calls_source, calls_source)

    html = (html_template
            .replace("__GENERATED_AT__", generated_at)
            .replace("__DAYS_BACK__", str(DAYS_BACK_CALLS))
            .replace("__CALLS_SOURCE__", source_label)
            .replace("__DATA_JSON__", data_json))
    return html


# ============================================================
# ASOSIY
# ============================================================
def main():
    print("🚀 amoCRM Dashboard generator boshlandi\n")

    data = fetch_all()
    print("\n📊 Statistika hisoblanmoqda...")
    stats = compute_stats(data)

    print("🎨 HTML yaratilmoqda...")
    html = build_html(stats, data)

    out = Path(OUTPUT_FILE)
    out.write_text(html, encoding="utf-8")

    print(f"\n✅ Tayyor!")
    print(f"📁 Fayl: {out.resolve()}")
    print(f"🌐 Brauzerda ochish: open {out.resolve()}")
    print(f"\n📈 Asosiy ko'rsatkichlar:")
    k = stats["kpi"]
    print(f"   • Leadlar: {k['total_leads']} (26-apr: {k['apr26']}, sotuv: {k['sold']})")
    print(f"   • Qo'ng'iroqlar: {k['total_calls']} (javob: {k['answered']}, {k['answer_rate']*100:.1f}%)")
    print(f"   • Menejerlar: {len(stats['managers'])}")


if __name__ == "__main__":
    main()
