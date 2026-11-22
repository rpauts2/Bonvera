from bot.vk.admin_api import mask_phone, validate_slots_payload


def valid_slots():
    rows = []
    for number in range(1, 5):
        rows.append({
            "slot_number": number,
            "kind": "mfo_offer",
            "advertiser_name": f"ООО МФО {number}",
            "title": f"МФО {number}",
            "target_url": f"https://mfo{number}.example/apply",
            "enabled": True,
        })
    rows.append({
        "slot_number": 5,
        "kind": "storefront",
        "advertiser_name": "Bonvera CPA storefront",
        "title": "Все предложения Bonvera",
        "target_url": "",
        "enabled": False,
    })
    return rows


def test_admin_slots_require_four_mfo_slots_and_one_storefront():
    validated, errors = validate_slots_payload(valid_slots())
    assert errors == []
    assert len(validated) == 5


def test_admin_slots_reject_wrong_storefront_kind_and_unsafe_url():
    rows = valid_slots()
    rows[4]["kind"] = "mfo_offer"
    rows[0]["target_url"] = "http://unsafe.example/"
    validated, errors = validate_slots_payload(rows)
    assert validated == []
    assert errors


def test_admin_slots_reject_enabled_unconfigured_slot():
    rows = valid_slots()
    rows[4]["enabled"] = True
    validated, errors = validate_slots_payload(rows)
    assert validated == []
    assert "slot_5_url_required" in errors


def test_phone_is_masked_in_contact_lists():
    assert mask_phone("79001234567") == "+7 *** ***-45-67"
    assert mask_phone("") == ""
