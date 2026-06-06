#!/bin/bash
# Loot. — one-time setup script
# Run: bash setup.sh

set -e
echo "🔥 Setting up Loot. backend..."

# 1. Python virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy env file
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "📝 .env file created. You need to fill in:"
  echo "   TELEGRAM_API_ID + TELEGRAM_API_HASH  →  https://my.telegram.org"
  echo "   OPENROUTER_API_KEY                   →  https://openrouter.ai/keys"
  echo "   SUPABASE_URL + SUPABASE_KEY          →  https://supabase.com"
  echo ""
fi

echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Fill in .env (see above)"
echo "  2. Run Supabase schema: paste data/supabase_schema.sql into Supabase SQL Editor"
echo "  3. Start scraper:  source venv/bin/activate && python scraper/telegram_scraper.py"
echo "  4. Start API:      source venv/bin/activate && uvicorn api.main:app --reload --port 8000"
