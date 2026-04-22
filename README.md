# amoCRM Dashboard — Salohiyat maktab

Kechki guruhlar va Site voronkasi bo'yicha jonli dashboard. Har 15 daqiqada GitHub Actions avtomatik `dashboard.html` ni qayta generatsiya qiladi va GitHub Pages orqali public URL'da xizmat qiladi. Brauzerda `<meta http-equiv="refresh" content="900">` tufayli sahifa ham har 15 daqiqada o'zini yangilaydi.

---

## ⚡ Tezkor variant (avtomatik — 1 buyruq)

Mac Terminal'da:

```bash
cd ~/Documents/amocrm-dashboard-repo
chmod +x setup.sh
./setup.sh
```

Script `gh` CLI ni o'rnatadi (agar yo'q bo'lsa), GitHub'ga login qiladi, repo yaratadi, push qiladi, `AMOCRM_TOKEN` ni Secret sifatida qo'shadi, Pages ni yoqadi, birinchi workflow'ni ishga tushiradi va dashboard URL'ini chop etadi. Sizdan faqat 2 narsa so'raladi: **repo nomi** (yoki Enter — `amocrm-dashboard`) va **amoCRM JWT token**.

Agar avtomatik usul ishlamasa yoki tushunmoqchi bo'lsangiz — pastdagi qo'lda qadamlar.

---

## 🔧 Qo'lda sozlash (~10 daqiqa)

### 1. GitHub repo yaratish

1. https://github.com/new → **Repository name**: `amocrm-dashboard` (yoki boshqa nom)
2. **Public** ni tanlang (free tier'da GitHub Pages faqat public repo'larda ishlaydi).
3. "Create repository" bosing. README/gitignore qo'shmang — bu papkada bor.

### 2. Fayllarni push qilish

Terminal'da shu papka (`amocrm-dashboard-repo`) ichida:

```bash
cd amocrm-dashboard-repo
git init
git add .
git commit -m "Initial dashboard setup"
git branch -M main
git remote add origin https://github.com/<USERNAME>/<REPO>.git
git push -u origin main
```

`<USERNAME>` va `<REPO>` ni o'zingiznikiga almashtiring.

### 3. amoCRM TOKEN'ni Secret sifatida qo'shish

1. Repo sahifasida: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
2. **Name**: `AMOCRM_TOKEN`
3. **Secret**: amoCRM JWT token (eyJ... bilan boshlanadigan uzun satr)
4. **Add secret**

⚠️ Token faqat shu yerda saqlanadi, kodga hech qachon yozilmaydi.

### 4. GitHub Pages'ni yoqish

1. **Settings** → **Pages**
2. **Source**: `GitHub Actions` ni tanlang (Branch emas!)
3. Saqlash shart emas — avtomatik saqlanadi.

### 5. Workflow'ni birinchi marta yuritish

1. **Actions** tabiga o'ting.
2. Agar "Workflows aren't being run on this forked repository" degan xabar chiqsa — "I understand my workflows, go ahead and enable them" ni bosing.
3. Chap tomonda **Refresh amoCRM Dashboard** ni tanlang.
4. O'ng yuqorida **Run workflow** → **Run workflow** bosing.
5. ~1–2 daqiqa kuting, yashil ✓ chiqadi.

### 6. Dashboard URL'ini olish

**Settings** → **Pages** sahifasida ko'rinadi:
```
https://<USERNAME>.github.io/<REPO>/
```

Shu URL'ni jamoa a'zolariga bering. Har 15 daqiqada avtomatik yangilanadi.

---

## Muhim eslatmalar

**Token muddati.** amoCRM JWT tokenlari cheklangan muddatga ega (odatda 1-2 hafta). Expire bo'lsa workflow 401 error beradi. Yangi token olish uchun: amoCRM → Sozlamalar → Integratsiyalar → (o'z integratsiyangiz) → Long-lived token.

**Yangi tokenni joylash:** Repo → Settings → Secrets → `AMOCRM_TOKEN` ni **Update** qiling. Kodni o'zgartirish shart emas.

**Cron kechikishi.** GitHub free tier'da `schedule` workflow'lari peak vaqtlarda 1–5 daqiqa kechikishi mumkin. Shoshilinch yangilash kerak bo'lsa Actions → Run workflow orqali qo'lda yurg'izing.

**Inaktiv repo.** Agar 60 kun ichida hech qanday push bo'lmasa GitHub cron'ni o'chirib qo'yadi. Har 1-2 oyda biror kommit qilish yoki `workflow_dispatch` orqali qo'lda ishga tushirish kifoya.

**Maxfiylik.** Dashboard public URL'da, lekin:
- URL oson topilmas (uzun, tasodifiy bo'lsa) — faqat jamoangizga bering.
- `<meta name="robots" content="noindex">` + `robots.txt` orqali Google/Yandex indekslamaydi.
- Public tarqalib ketmaslik uchun jamoa a'zolariga "boshqalarga bermang" deb ogohlantiring.

**Qat'iyroq himoya kerakmi?** Cloudflare Access yoki Netlify password protection'ga o'tkazish mumkin — hozir kerak bo'lmasa, keyin yozing.

---

## Lokal sinash

Push qilishdan oldin lokal ishlayotganini tekshirish uchun:

```bash
export AMOCRM_TOKEN="eyJ0eXAi..."     # token
python3 amocrm_dashboard.py
open dashboard.html                    # macOS'da brauzerda ochadi
```

---

## Fayllar

```
amocrm-dashboard-repo/
├── amocrm_dashboard.py           # Asosiy script (TOKEN endi env-var'dan o'qiladi)
├── .github/workflows/refresh.yml # Har 15 daq. cron + Pages deploy
├── .gitignore
└── README.md                     # shu fayl
```

Hech qanday `pip install` kerak emas — script faqat Python standart kutubxonasini ishlatadi.
