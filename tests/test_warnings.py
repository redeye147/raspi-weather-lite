"""気象庁の警報 JSON の解析（コード → 名称、解除の除外、並び順）"""
import pytest

from jma_alerts import WARNING_CODES, _extract_warning_text, active_warning_names

NARITA = ("1221100",)


def warn_json(*areas):
    """areas: (地域コード, [(警報コード, status), ...])"""
    return {"areaTypes": [{"areas": [
        {"code": code, "warnings": [{"code": c, "status": s} for c, s in ws]} for code, ws in areas
    ]}]}


@pytest.mark.parametrize("code, name", [
    ("03", "大雨警報"),
    ("05", "暴風警報"),
    ("10", "大雨注意報"),
    ("14", "雷注意報"),
    ("15", "強風注意報"),
    ("18", "洪水注意報"),
    ("20", "濃霧注意報"),
    ("33", "大雨特別警報"),
])
def test_warning_codes_match_jma(code, name):
    """過去にずれていた対応（03 を注意報、20 が未登録 等）が戻らないこと"""
    assert WARNING_CODES[code] == name


def test_dense_fog_advisory():
    """2026-09 に実機で確認した成田の濃霧注意報（コード 20）"""
    data = warn_json(("120010", [("20", "発表")]), ("1221100", [("20", "発表")]))
    assert active_warning_names(data, NARITA) == ["濃霧注意報"]


def test_order_and_lifted_excluded():
    """特別警報 → 警報 → 注意報の順。解除は除く。重複はまとめる"""
    data = warn_json(("1221100", [("14", "発表"), ("03", "継続"), ("18", "解除"),
                                  ("33", "発表"), ("14", "継続")]))
    assert active_warning_names(data, NARITA) == ["大雨特別警報", "大雨警報", "雷注意報"]


def test_other_area_ignored():
    data = warn_json(("1220400", [("05", "発表")]))
    assert active_warning_names(data, NARITA) == []


def test_unknown_code_is_shown():
    """表に無いコードは消さずに「警報コードNN」と表示（コード体系の変更に気付けるように）"""
    data = warn_json(("1221100", [("99", "発表")]))
    assert active_warning_names(data, NARITA) == ["警報コード99"]


def test_no_warnings_status():
    """気象庁の「発表警報・注意報はなし」状態"""
    data = {"areaTypes": [{"areas": [{"code": "1221100",
                                      "warnings": [{"status": "発表警報・注意報はなし"}]}]}]}
    assert active_warning_names(data, NARITA) == []
    assert _extract_warning_text(data, NARITA) == "警報・注意報：発表なし"


def test_extract_text_joins_names():
    """同じ種類（注意報どうし）は気象庁データの順のまま並べる"""
    data = warn_json(("1221100", [("20", "発表"), ("14", "発表")]))
    assert _extract_warning_text(data, NARITA) == "警報・注意報：濃霧注意報、雷注意報"


def test_empty_or_broken_json():
    assert active_warning_names({}, NARITA) == []
    assert active_warning_names({"areaTypes": None}, NARITA) == []
