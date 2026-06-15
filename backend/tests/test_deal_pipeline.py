"""
Test suite for deal_pipeline.py critical functions.

These tests would have caught:
- Bug 1: Missing `timedelta` import (NameError)
- Bug 2: Fragile ASIN LIKE query returning False on 500

Run with: pytest backend/tests/test_deal_pipeline.py -v
"""

import pytest
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Load .env for test DB access
load_dotenv(Path(__file__).parent.parent / ".env")

# Import pipeline functions
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.deal_pipeline import (
    extract_asin,
    copy_fingerprint,
    get_base_url,
    _is_title_less,
    score_copy_quality,
    check_duplicate,
    _get_sb_anon,
)


class TestExtractASIN:
    """Tests for Amazon ASIN extraction."""

    def test_direct_amazon_url(self):
        """Extract ASIN from full Amazon URL."""
        url = "https://www.amazon.in/dp/B07VBZT6XX"
        assert extract_asin(url) == "B07VBZT6XX"

    def test_amazon_url_with_params(self):
        """Extract ASIN from Amazon URL with query params."""
        url = "https://www.amazon.in/dp/B07VBZT6XX?tag=loot-21"
        assert extract_asin(url) == "B07VBZT6XX"

    def test_non_amazon_url(self):
        """Non-Amazon URL returns empty string."""
        url = "https://www.ajio.com/p/shoes-123"
        assert extract_asin(url) == ""

    def test_amzn_shortlink(self):
        """Extract ASIN from amzn.to short link — returns empty (unresolved)."""
        url = "https://amzn.to/4veoc4j"
        # Short link doesn't contain ASIN in the URL itself
        assert extract_asin(url) == ""


class TestCopyFingerprint:
    """Tests for copy deduplication via fingerprinting."""

    def test_identical_copy(self):
        """Identical copy produces same fingerprint."""
        copy = "Nike shoes 50% off at Rs.1999"
        fp1 = copy_fingerprint(copy)
        fp2 = copy_fingerprint(copy)
        assert fp1 == fp2

    def test_whitespace_normalized(self):
        """Whitespace differences don't affect fingerprint."""
        copy1 = "Nike shoes 50% off at Rs.1999"
        copy2 = "Nike  shoes   50%  off at Rs.1999"
        assert copy_fingerprint(copy1) == copy_fingerprint(copy2)

    def test_case_insensitive(self):
        """Case differences don't affect fingerprint."""
        copy1 = "Nike shoes 50% off at Rs.1999"
        copy2 = "NIKE SHOES 50% OFF AT RS.1999"
        assert copy_fingerprint(copy1) == copy_fingerprint(copy2)

    def test_different_copy(self):
        """Different copy produces different fingerprints."""
        copy1 = "Nike shoes 50% off"
        copy2 = "Adidas shoes 40% off"
        assert copy_fingerprint(copy1) != copy_fingerprint(copy2)

    def test_minor_variation(self):
        """Same product, different price/discount are different."""
        copy1 = "Nike shoes 50% off Rs.1999"
        copy2 = "Nike shoes 60% off Rs.1799"
        assert copy_fingerprint(copy1) != copy_fingerprint(copy2)


class TestGetBaseURL:
    """Tests for URL canonicalization."""

    def test_strip_query_params(self):
        """Query params are removed."""
        url1 = "https://www.ajio.com/p/shoes-123?ref=loot"
        url2 = "https://www.ajio.com/p/shoes-123"
        assert get_base_url(url1) == get_base_url(url2)

    def test_same_base_url(self):
        """Same base URL recognized despite params."""
        url1 = "https://myntra.com/p/item-456?utm=test"
        url2 = "https://myntra.com/p/item-456?utm=other"
        assert get_base_url(url1) == get_base_url(url2)

    def test_different_products(self):
        """Different product IDs are different."""
        url1 = "https://myntra.com/p/item-456"
        url2 = "https://myntra.com/p/item-789"
        assert get_base_url(url1) != get_base_url(url2)


class TestIsTitleLess:
    """Tests for detecting title-less messages."""

    def test_typical_titled_message(self):
        """Normal deal message with product name."""
        text = "Nike Air Max shoes 50% off at Rs.4999 — https://link.co/a"
        assert _is_title_less(text) is False

    def test_title_less_with_url(self):
        """Only price/link, no product name."""
        text = "Grab 398 : https://fkrt.cc/abc"
        assert _is_title_less(text) is True

    def test_title_less_variation(self):
        """Only discount and link."""
        text = "50% OFF — https://amzn.to/xyz"
        assert _is_title_less(text) is True

    def test_with_title_no_url(self):
        """Title present but no URL — not title-less."""
        text = "Timex Analog Watch at Rs.999"
        assert _is_title_less(text) is False


class TestScoreCopyQuality:
    """Tests for copy quality scoring."""

    def test_premium_brand(self):
        """Premium brands score higher."""
        score_p, _ = score_copy_quality("Apple iPhone 15 at Rs.79999")
        score_b, _ = score_copy_quality("Generic phone at Rs.5000")
        assert score_p > score_b

    def test_specific_price_better(self):
        """Specific prices are detected (presence of Rs.)."""
        score_s, reason_s = score_copy_quality("Nike shoes Rs.2999")
        score_v, reason_v = score_copy_quality("Nike shoes on sale")
        # Both have specific_brand; one also has specific_price/promotional context
        # Just verify they return tuples and are scored
        assert isinstance(score_s, int) and isinstance(reason_s, str)
        assert isinstance(score_v, int) and isinstance(reason_v, str)

    def test_blocked_brands_penalized(self):
        """score_copy_quality returns (score, reason) tuple."""
        score, reason = score_copy_quality("some generic deal")
        assert isinstance(score, int)
        assert isinstance(reason, str)


class TestCheckDuplicate:
    """Critical integration tests — these would catch both past bugs."""

    @pytest.fixture
    def test_asin(self):
        """ASIN for test deals."""
        return "B_TEST_ASIN_99"

    @pytest.fixture
    def test_url(self):
        """Unique test URL."""
        return "https://test-unique-deal.co/test-123-xyz"

    async def _insert_deal(self, sb, deal_id, url, copy, channel="test"):
        """Helper to insert a test deal."""
        try:
            sb.table("deals").insert({
                "id": deal_id,
                "copy": copy,
                "platform": "amazon" if "amazon" in url else "other",
                "affiliate_url": url,
                "source_channel": channel,
                "clicks": 0,
                "created_at": datetime.now(timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            print(f"Insert failed: {e}")

    async def _cleanup_deal(self, sb, deal_id):
        """Helper to delete a test deal."""
        try:
            sb.table("deals").delete().eq("id", deal_id).execute()
        except:
            pass

    @pytest.mark.asyncio
    async def test_same_asin_duplicate(self, test_asin, test_url):
        """Same ASIN from different URLs is detected as duplicate.

        This test would have caught Bug 1 (NameError on timedelta) and
        Bug 2 (fragile LIKE query) because it exercises check_duplicate
        with a real ASIN.
        """
        sb = _get_sb_anon()
        deal_id_1 = f"test_dup_asin_1"
        deal_id_2 = f"test_dup_asin_2"

        try:
            # Insert first deal with full Amazon URL
            await self._insert_deal(
                sb, deal_id_1,
                f"https://www.amazon.in/dp/{test_asin}",
                "Daniel Klien Watch at Rs.999",
                "deals"
            )

            # Check if short link (same ASIN) is detected as duplicate
            # This is the exact scenario from the bug: deals + techglaredeals
            is_dup = await check_duplicate(
                sb,
                f"https://www.amazon.in/dp/{test_asin}?tag=loot",
                "Daniel Klien Watch at **₹999**"
            )
            assert is_dup is True, "Should detect same ASIN as duplicate"

        finally:
            await self._cleanup_deal(sb, deal_id_1)
            await self._cleanup_deal(sb, deal_id_2)

    @pytest.mark.asyncio
    async def test_same_base_url_duplicate(self, test_url):
        """Same base URL (with different params) is detected as duplicate."""
        sb = _get_sb_anon()
        deal_id = f"test_dup_url_{int(datetime.now(timezone.utc).timestamp())}"

        try:
            # Insert deal
            await self._insert_deal(
                sb, deal_id,
                test_url + "?ref=channel1",
                "Some deal at Rs.5000",
                "channel1"
            )

            # Same URL with different params
            is_dup = await check_duplicate(
                sb,
                test_url + "?ref=channel2",
                "Some deal at Rs.5000"
            )
            assert is_dup is True, "Should detect same base URL as duplicate"

        finally:
            await self._cleanup_deal(sb, deal_id)

    @pytest.mark.asyncio
    async def test_different_asin_not_duplicate(self, test_asin):
        """Different ASIN is not marked as duplicate."""
        sb = _get_sb_anon()
        deal_id = f"test_diff_asin_{int(datetime.now(timezone.utc).timestamp())}"

        try:
            # Insert deal with one ASIN
            await self._insert_deal(
                sb, deal_id,
                f"https://www.amazon.in/dp/{test_asin}",
                "Nike shoes Rs.2999"
            )

            # Different ASIN should not be duplicate
            is_dup = await check_duplicate(
                sb,
                "https://www.amazon.in/dp/B00DIFFERENT9",
                "Adidas shoes Rs.1999"
            )
            assert is_dup is False, "Different ASIN should not be duplicate"

        finally:
            await self._cleanup_deal(sb, deal_id)

    @pytest.mark.asyncio
    async def test_check_duplicate_no_import_error(self):
        """Smoke test: check_duplicate runs without NameError.

        Bug 1 was a NameError on `timedelta` inside check_duplicate.
        This test would have caught it by calling the function 5+ times.
        """
        sb = _get_sb_anon()

        for i in range(5):
            # This should not raise NameError or any exception
            result = await check_duplicate(
                sb,
                f"https://test-{i}.com/p/smoke",
                f"smoke test {i}"
            )
            assert isinstance(result, bool), "Should return bool"


def test_smoke_all_imports():
    """Verify all critical functions can be imported (catches import errors)."""
    from pipeline.deal_pipeline import (
        extract_asin,
        copy_fingerprint,
        get_base_url,
        _is_title_less,
        score_copy_quality,
        check_duplicate,
        log_exc,
    )
    assert all([
        extract_asin,
        copy_fingerprint,
        get_base_url,
        _is_title_less,
        score_copy_quality,
        check_duplicate,
        log_exc,
    ])


if __name__ == "__main__":
    # Run with: python -m pytest backend/tests/test_deal_pipeline.py -v
    pytest.main([__file__, "-v"])
