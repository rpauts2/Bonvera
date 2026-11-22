from bot.config import cfg
from bot.vk.attribution import build_campaign_entry_link, make_campaign_ref, parse_campaign_ref


def test_campaign_ref_is_signed_and_round_trips():
    ref = make_campaign_ref(123)
    assert parse_campaign_ref(ref) == 123
    assert parse_campaign_ref("c123_0000000000000000") is None
    assert parse_campaign_ref("c0_0000000000000000") is None
    assert parse_campaign_ref("../123") is None


def test_campaign_entry_link_uses_vk_me_and_ref_tags(monkeypatch):
    monkeypatch.setattr(cfg, "vk_community_url", "https://vk.me/bonvera_test")
    link = build_campaign_entry_link(42)
    assert link.startswith("https://vk.me/bonvera_test?")
    assert "ref=" + make_campaign_ref(42) in link
    assert "ref_source=bonvera" in link


def test_campaign_entry_link_rejects_untrusted_community_url(monkeypatch):
    monkeypatch.setattr(cfg, "vk_community_url", "https://evil.example/chat")
    try:
        build_campaign_entry_link(42)
    except ValueError:
        pass
    else:
        raise AssertionError("only a VK community chat URL must be accepted")
