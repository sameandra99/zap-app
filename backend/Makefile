.PHONY: test test-check-duplicate lint pre-deploy help

help:
	@echo "Loot deals backend commands:"
	@echo "  make test                 — Run full pytest suite"
	@echo "  make test-check-duplicate — Run critical dedup tests only"
	@echo "  make pre-deploy           — Run pre-deploy checks (pytest + syntax)"

test:
	@source venv/bin/activate && python -m pytest tests/ -v --tb=short

test-check-duplicate:
	@source venv/bin/activate && python -m pytest tests/test_deal_pipeline.py::TestCheckDuplicate -v --tb=short

pre-deploy: test
	@echo "✅ Pre-deploy checks passed"
	@echo "Ready to deploy:"
	@echo "  cd backend && fly deploy --config fly.scraper.toml -a loot-scraper"
	@echo "  cd backend && fly deploy --config fly.api.toml -a loot-api"
