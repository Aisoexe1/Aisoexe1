#!/bin/bash
# Moodle Assistant — Mac launcher
# Первый запуск: правая кнопка мыши → Открыть (чтобы обойти Gatekeeper)

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# ── Проверка Python ────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    osascript -e 'display alert "Потрібен Python 3" message "Встановіть Python 3 з сайту python.org і спробуйте ще раз."'
    exit 1
fi

# ── Установка зависимостей (если нужно) ───────────────────────────────────────
if ! python3 -c "import fastapi, playwright" &>/dev/null 2>&1; then
    echo "📦 Встановлення залежностей (один раз)..."
    pip3 install -r requirements.txt
    python3 -m playwright install chromium
fi

# ── Проверка .env ─────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    osascript -e 'display alert "Потрібен GEMINI_API_KEY" message "Файл .env відкрито. Встав свій ключ після GEMINI_API_KEY= і збережи файл."'
    open -e .env
    echo ""
    echo "⚠️  Встав GEMINI_API_KEY у файл .env і запусти знову."
    read -p "Натисни Enter після збереження .env..."
fi

# ── Загрузка .env ─────────────────────────────────────────────────────────────
export $(grep -v '^#' .env | xargs) 2>/dev/null

if [ -z "$GEMINI_API_KEY" ]; then
    osascript -e 'display alert "GEMINI_API_KEY не знайдено" message "Відкрий файл .env і встав свій ключ після GEMINI_API_KEY="'
    open -e .env
    echo ""
    echo "⚠️  GEMINI_API_KEY порожній. Додай ключ у .env і запусти знову."
    exit 1
fi

# ── Запуск ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════╗"
echo "║      🎓 Moodle Assistant v1.0        ║"
echo "║   http://localhost:8888              ║"
echo "║   Зупинити: Ctrl+C                   ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Открыть браузер через 2 секунды
(sleep 2 && open "http://localhost:8888") &

python3 app.py
