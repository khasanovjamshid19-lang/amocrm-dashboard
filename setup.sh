#!/usr/bin/env bash
# ============================================================
# amoCRM Dashboard — GitHub'ga avtomatik joylash
#
# Ishlatish:
#   cd ~/Documents/amocrm-dashboard-repo
#   chmod +x setup.sh
#   ./setup.sh
#
# Script quyidagilarni qiladi:
#   1. GitHub CLI (gh) ni o'rnatadi (agar yo'q bo'lsa)
#   2. GitHub'ga login qiladi (brauzer ochadi)
#   3. Yangi public repo yaratadi
#   4. Fayllarni push qiladi
#   5. AMOCRM_TOKEN ni Secret sifatida qo'shadi
#   6. GitHub Pages'ni Actions source bilan yoqadi
#   7. Birinchi workflow ishga tushiradi va kutadi
#   8. Public Dashboard URL ni chop etadi
# ============================================================

set -euo pipefail

# Colors
G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[0;34m'; N='\033[0m'
step() { echo -e "${B}▶${N} $*"; }
ok()   { echo -e "${G}✓${N} $*"; }
warn() { echo -e "${Y}!${N} $*"; }
err()  { echo -e "${R}✗${N} $*" >&2; }

# Script papkasiga o'tish
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Tekshirish: kerakli fayllar bormi
if [[ ! -f amocrm_dashboard.py ]] || [[ ! -f .github/workflows/refresh.yml ]]; then
  err "amocrm_dashboard.py yoki .github/workflows/refresh.yml topilmadi."
  err "Bu script amocrm-dashboard-repo papkasi ichida yurg'izilishi kerak."
  exit 1
fi

echo "════════════════════════════════════════════════════════"
echo "  📊 amoCRM Dashboard — GitHub setup"
echo "════════════════════════════════════════════════════════"
echo ""

# ----------------------------------------------------------------
# 1. Homebrew tekshirish
# ----------------------------------------------------------------
if ! command -v brew >/dev/null 2>&1; then
  warn "Homebrew o'rnatilmagan."
  echo "   Quyidagini Terminal'da yurg'izing:"
  echo ""
  echo '   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo ""
  echo "   Keyin shu scriptni qaytadan yurg'izing."
  exit 1
fi
ok "Homebrew topildi"

# ----------------------------------------------------------------
# 2. gh CLI o'rnatish
# ----------------------------------------------------------------
if ! command -v gh >/dev/null 2>&1; then
  step "GitHub CLI o'rnatilmoqda (brew install gh)..."
  brew install gh
fi
ok "gh CLI: $(gh --version | head -1)"

# ----------------------------------------------------------------
# 3. GitHub auth
# ----------------------------------------------------------------
if ! gh auth status >/dev/null 2>&1; then
  step "GitHub'ga login qilish kerak. Brauzer ochiladi..."
  gh auth login --hostname github.com --git-protocol https --web --scopes "repo,workflow"
fi

# Scope tekshirish — workflow scope kerak
if ! gh auth status 2>&1 | grep -q "workflow"; then
  warn "gh auth'da 'workflow' scope yo'q. Refresh qilamiz..."
  gh auth refresh -h github.com -s workflow
fi

GH_USER=$(gh api user --jq .login)
ok "GitHub login: $GH_USER"

# ----------------------------------------------------------------
# 4. Repo nomini olish
# ----------------------------------------------------------------
echo ""
DEFAULT_REPO="amocrm-dashboard"
read -r -p "Repo nomi [${DEFAULT_REPO}]: " REPO_NAME
REPO_NAME="${REPO_NAME:-$DEFAULT_REPO}"

REPO_EXISTS=0
if gh repo view "$GH_USER/$REPO_NAME" >/dev/null 2>&1; then
  warn "Repo $GH_USER/$REPO_NAME allaqachon mavjud."
  read -r -p "Davom etamizmi? Push qilinadi (y/N): " yn
  [[ "$yn" =~ ^[Yy]$ ]] || { err "Bekor qilindi."; exit 1; }
  REPO_EXISTS=1
fi

# ----------------------------------------------------------------
# 5. AMOCRM_TOKEN
# ----------------------------------------------------------------
# Variant 1: env var orqali (tavsiya — paste muammosi bo'lmaydi)
#   export AMOCRM_TOKEN='eyJ...'   keyin   ./setup.sh
# Variant 2: TOKEN_FILE orqali (token faylda saqlangan bo'lsa)
#   ./setup.sh /path/to/token.txt
# Variant 3: Interaktiv prompt (eski usul, paste qiyin)

if [[ -n "${1:-}" ]] && [[ -f "$1" ]]; then
  step "Tokenni fayldan o'qiyapman: $1"
  AMOCRM_TOKEN=$(tr -d ' \n\r\t' < "$1")
elif [[ -n "${AMOCRM_TOKEN:-}" ]]; then
  step "Tokenni env var'dan oldim (uzunligi: ${#AMOCRM_TOKEN})"
else
  echo ""
  echo "amoCRM JWT tokenni kiriting (eyJ... bilan boshlanadi)."
  echo "Yopiq input — yozganingiz ko'rinmaydi."
  read -r -s -p "AMOCRM_TOKEN: " AMOCRM_TOKEN
  echo ""
fi

if [[ -z "$AMOCRM_TOKEN" ]] || [[ "${AMOCRM_TOKEN:0:3}" != "eyJ" ]]; then
  err "Token bo'sh yoki noto'g'ri (eyJ... bilan boshlanishi kerak)."
  echo ""
  echo "Yengilroq usul: tokenni env var'ga qo'ying va qaytadan yurg'izing:"
  echo "   export AMOCRM_TOKEN='eyJ...'"
  echo "   ./setup.sh"
  exit 1
fi
ok "Token qabul qilindi (uzunligi: ${#AMOCRM_TOKEN})"

# ----------------------------------------------------------------
# 6. Git init va commit
# ----------------------------------------------------------------
step "Git repo tayyorlanmoqda..."

# Eski __pycache__ va dashboard.html ni tozalash
rm -rf __pycache__ 2>/dev/null || true
rm -f dashboard.html 2>/dev/null || true

if [[ ! -d .git ]]; then
  git init -q
  git branch -M main 2>/dev/null || true
fi

# git user.email/name agar yo'q bo'lsa
if ! git config user.email >/dev/null 2>&1; then
  git config user.email "${GH_USER}@users.noreply.github.com"
  git config user.name "$GH_USER"
fi

git add .
if ! git diff --cached --quiet 2>/dev/null; then
  git commit -q -m "Initial dashboard setup" || true
fi
ok "Git tayyor"

# ----------------------------------------------------------------
# 7. Repo yaratish va push
# ----------------------------------------------------------------
if [[ "$REPO_EXISTS" == "0" ]]; then
  step "GitHub'da yangi public repo yaratilmoqda: $GH_USER/$REPO_NAME"
  gh repo create "$GH_USER/$REPO_NAME" --public --source=. --remote=origin --push
else
  if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "https://github.com/$GH_USER/$REPO_NAME.git"
  fi
  step "Mavjud repo'ga push qilinmoqda..."
  git push -u origin main --force-with-lease 2>/dev/null || git push -u origin main
fi
ok "Push tugadi"

# ----------------------------------------------------------------
# 8. AMOCRM_TOKEN secret
# ----------------------------------------------------------------
step "AMOCRM_TOKEN Secret sozlanmoqda..."
echo -n "$AMOCRM_TOKEN" | gh secret set AMOCRM_TOKEN --repo "$GH_USER/$REPO_NAME" --body -
ok "Secret saqlandi"

# ----------------------------------------------------------------
# 9. Pages yoqish (Source: GitHub Actions)
# ----------------------------------------------------------------
step "GitHub Pages yoqilmoqda (Source: Actions)..."
PAGES_OK=0
if gh api -X POST "repos/$GH_USER/$REPO_NAME/pages" -f build_type=workflow >/dev/null 2>&1; then
  PAGES_OK=1
elif gh api -X PUT "repos/$GH_USER/$REPO_NAME/pages" -f build_type=workflow >/dev/null 2>&1; then
  PAGES_OK=1
fi

if [[ "$PAGES_OK" == "1" ]]; then
  ok "Pages yoqildi"
else
  warn "Pages avtomatik yoqilmadi. Qo'lda yoqing:"
  echo "   https://github.com/$GH_USER/$REPO_NAME/settings/pages"
  echo "   Source: GitHub Actions"
fi

# ----------------------------------------------------------------
# 10. Birinchi workflow run
# ----------------------------------------------------------------
step "Workflow ishga tushirilmoqda..."
sleep 3

# Workflow ro'yxatga olinishi uchun bir necha urinish
for i in 1 2 3 4 5; do
  if gh workflow run refresh.yml --repo "$GH_USER/$REPO_NAME" >/dev/null 2>&1; then
    ok "Workflow trigger qilindi"
    break
  fi
  if [[ "$i" == "5" ]]; then
    warn "Workflow trigger qilolmadim. Qo'lda yurg'izing:"
    echo "   https://github.com/$GH_USER/$REPO_NAME/actions"
  else
    sleep 4
  fi
done

# ----------------------------------------------------------------
# 11. Run kutish
# ----------------------------------------------------------------
sleep 6
RUN_ID=$(gh run list --repo "$GH_USER/$REPO_NAME" --workflow=refresh.yml --limit 1 --json databaseId --jq '.[0].databaseId' 2>/dev/null || echo "")

if [[ -n "$RUN_ID" ]]; then
  step "Workflow tugashini kutyapman (Run ID: $RUN_ID)..."
  if gh run watch "$RUN_ID" --repo "$GH_USER/$REPO_NAME" --exit-status --interval 5 2>/dev/null; then
    ok "Workflow muvaffaqiyatli tugadi"
  else
    err "Workflow xato bilan tugadi."
    echo "   Loglarni ko'rish:"
    echo "   gh run view $RUN_ID --repo $GH_USER/$REPO_NAME --log-failed"
    echo ""
    echo "   Eng ehtimol sabab: AMOCRM_TOKEN expired (401 Unauthorized)."
    echo "   amoCRM'dan yangi token oling va Secret'ni yangilang:"
    echo "   gh secret set AMOCRM_TOKEN --repo $GH_USER/$REPO_NAME"
    exit 1
  fi
fi

# ----------------------------------------------------------------
# 12. URL chop etish
# ----------------------------------------------------------------
sleep 3
PAGES_URL=$(gh api "repos/$GH_USER/$REPO_NAME/pages" --jq .html_url 2>/dev/null || echo "https://$GH_USER.github.io/$REPO_NAME/")

echo ""
echo "════════════════════════════════════════════════════════"
echo -e "${G}🎉 TAYYOR!${N}"
echo "════════════════════════════════════════════════════════"
echo ""
echo -e "  📊 Dashboard URL:    ${G}$PAGES_URL${N}"
echo "  📦 Repo:             https://github.com/$GH_USER/$REPO_NAME"
echo "  ⚙️  Actions:          https://github.com/$GH_USER/$REPO_NAME/actions"
echo ""
echo "  ⏱️  Har 15 daqiqada avtomatik yangilanadi."
echo "  🔒 Token GitHub Secrets'da xavfsiz, kodda yo'q."
echo "  🚫 Google indekslanmaydi (noindex meta + robots.txt)."
echo ""
echo "  Pages birinchi marta tayyorlanishi 1–2 daqiqa olishi mumkin."
echo "  Brauzerda yuqoridagi URL'ni oching."
echo ""
echo "════════════════════════════════════════════════════════"
