import pytest

from bot.vk.tracking import validate_external_target


def test_tracking_target_accepts_https_partner_urls():
    assert validate_external_target("https://partner.example/apply") == "https://partner.example/apply"


@pytest.mark.parametrize(
    "url",
    [
        "http://partner.example/apply",
        "https://user:pass@partner.example/apply",
        "https://localhost/apply",
        "https://127.0.0.1/apply",
        "https://10.0.0.4/apply",
        "javascript:alert(1)",
        "//partner.example/apply",
    ],
)
def test_tracking_target_rejects_unsafe_redirect_urls(url):
    with pytest.raises(ValueError):
        validate_external_target(url)
