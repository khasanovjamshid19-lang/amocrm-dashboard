#!/usr/bin/env python3
"""
Moi Zvonki (moizvonki.ru) API integration — qo'ng'iroqlar tarixini olish.

API hujjati: kabinet → Sozlamalar → Integratsiyalar → "Документация по API"
Endpoint:    POST https://{subdomain}.moizvonki.ru/api/v1
Body:        request_data=<URL-encoded JSON>
Auth:        user_name (email) + api_key JSON ichida

Foydalanish:
    from moizvonki_api import fetch_calls
    calls = fetch_calls(
        domain="salohiyatschool.moizvonki.ru",
        user_name="autocrmuz@gmail.com",
        api_key=os.environ["MOIZVONKI_API_KEY"],
        from_ts=int(time.time()) - 30 * 86400,
        to_ts=int(time.time()),
    )
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request


def fetch_calls(domain, user_name, api_key, from_ts, to_ts,
                page_size=1000, supervised=1, max_pages=500):
    """
    Belgilangan davrdagi (from_ts ... to_ts, unix timestamp) qo'ng'iroqlarni qaytaradi.

    Har bir qo'ng'iroq dict:
      - direction:    1 = kiruvchi, 2 = chiquvchi (umumiy konventsiya)
      - user_account: menejer emaili
      - user_id:      Moi Zvonki ichidagi user_id
      - client_number: mijozning raqami
      - src_number:   manba raqam
      - start_time:   qo'ng'iroq boshlangan vaqt (unix sec)
      - answer_time:  javob berilgan vaqt
      - end_time:     tugagan vaqt
      - duration:     gaplashish vaqti (sekund)
      - answered:     1 = javob berilgan, 0 = javobsiz
      - db_call_id:   ichki ID
      - recording:    yozuv URL'i (agar bor bo'lsa)
    """
    url = f"https://{domain}/api/v1"
    all_calls = []
    from_offset = 0
    pages = 0

    while pages < max_pages:
        pages += 1
        request_data = {
            "user_name": user_name,
            "api_key": api_key,
            "action": "calls.list",
            "from_date": int(from_ts),
            "to_date": int(to_ts),
            "from_offset": from_offset,
            "max_results": page_size,
            "supervised": supervised,
        }
        body = urllib.parse.urlencode({
            "request_data": json.dumps(request_data, ensure_ascii=False),
        }).encode("utf-8")

        last_err = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, data=body, method="POST")
                req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
                req.add_header("Accept", "application/json")
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read().decode("utf-8"))
                    last_err = None
                    break
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                if e.code >= 500 and attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    last_err = e
                    continue
                raise RuntimeError(
                    f"Moi Zvonki HTTP {e.code} (page {pages}): {err_body}"
                )
            except urllib.error.URLError as e:
                if attempt < 3:
                    time.sleep(1 * (attempt + 1))
                    last_err = e
                    continue
                raise RuntimeError(f"Moi Zvonki URL error: {e}")
        if last_err:
            raise last_err

        results = data.get("results") or []
        all_calls.extend(results)

        # Birinchi sahifada hech narsa yo'q bo'lsa — debug ma'lumot chop etamiz
        if pages == 1 and not results:
            keys = list(data.keys())
            err = data.get("error") or data.get("error_message") or data.get("message")
            status = data.get("status") or data.get("result")
            print(f"     [debug] javob kalitlari: {keys}")
            print(f"     [debug] status={status} error={err}")
            print(f"     [debug] supervised={supervised} from={from_ts} to={to_ts}")
            # to'liq javobni ham (qisqartirilgan) chop etamiz
            try:
                snippet = json.dumps(data, ensure_ascii=False)[:500]
                print(f"     [debug] javob (500ch): {snippet}")
            except Exception:
                pass

        # Paginatsiya: results_remains 0 bo'lsa tugadi
        remains = data.get("results_remains", 0)
        next_offset = data.get("results_next_offset", 0)
        if not remains:
            break
        if next_offset == from_offset:
            # xavfsizlik — offset siljimasa to'xtatamiz
            break
        from_offset = next_offset
        time.sleep(0.15)

    return all_calls


def calls_to_dashboard_format(mz_calls, email_to_user_id=None, user_map=None,
                              start_pseudo_id=-100000):
    """
    Moi Zvonki javobini script ichidagi 'amoCRM call note' formatiga aylantiradi.

    Qaytariladi: (calls_list, user_map_updated)
      - calls_list: amoCRM call notes formatidagi list (created_at, note_type,
                    created_by, params.duration)
      - user_map_updated: yangilangan {user_id: name} dict (yangi MoiZvonki
                          foydalanuvchilari uchun pseudo-id qo'shilgan)
    """
    email_to_user_id = dict(email_to_user_id or {})
    user_map = dict(user_map or {})
    next_pseudo = start_pseudo_id

    out = []
    for c in mz_calls:
        direction = c.get("direction")
        # 1 = kiruvchi (incoming), 2 = chiquvchi (outgoing) — umumiy konventsiya
        if direction == 1:
            note_type = "call_in"
        elif direction == 2:
            note_type = "call_out"
        else:
            # noma'lum — chiquvchi deb hisoblaymiz
            note_type = "call_out"

        email = (c.get("user_account") or "").strip().lower()
        user_id = email_to_user_id.get(email)
        if not user_id and email:
            # amoCRM'da topilmadi — pseudo-id ajratamiz
            user_id = next_pseudo
            next_pseudo -= 1
            email_to_user_id[email] = user_id
            user_map[user_id] = email

        # answered=0 bo'lsa duration ham 0 (javobsiz qo'ng'iroq)
        duration = c.get("duration", 0) or 0
        if not c.get("answered"):
            duration = 0

        out.append({
            "created_at": c.get("start_time", 0),
            "note_type": note_type,
            "created_by": user_id,
            "params": {"duration": duration},
            # qo'shimcha — kelajakda foydali bo'lishi mumkin
            "_mz": {
                "client": c.get("client_number"),
                "rec": c.get("recording"),
                "id": c.get("db_call_id"),
            },
        })

    return out, user_map
