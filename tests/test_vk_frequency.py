from datetime import datetime, timedelta

from bot.vk.outreach import within_campaign_frequency_cap


def test_campaign_frequency_cap_allows_first_message():
    now = datetime(2026, 11, 22, 12, 0, 0)
    assert within_campaign_frequency_cap(
        last_sent_at=None,
        sent_count_30d=0,
        now=now,
        minimum_interval_hours=24,
        maximum_messages_30d=4,
    )


def test_campaign_frequency_cap_blocks_second_message_within_minimum_interval():
    now = datetime(2026, 11, 22, 12, 0, 0)
    assert not within_campaign_frequency_cap(
        last_sent_at=now - timedelta(hours=4),
        sent_count_30d=1,
        now=now,
        minimum_interval_hours=24,
        maximum_messages_30d=4,
    )


def test_campaign_frequency_cap_blocks_above_30_day_limit():
    now = datetime(2026, 11, 22, 12, 0, 0)
    assert not within_campaign_frequency_cap(
        last_sent_at=now - timedelta(days=3),
        sent_count_30d=4,
        now=now,
        minimum_interval_hours=24,
        maximum_messages_30d=4,
    )


def test_campaign_frequency_cap_allows_when_interval_and_monthly_limit_allow():
    now = datetime(2026, 11, 22, 12, 0, 0)
    assert within_campaign_frequency_cap(
        last_sent_at=now - timedelta(hours=30),
        sent_count_30d=2,
        now=now,
        minimum_interval_hours=24,
        maximum_messages_30d=4,
    )
