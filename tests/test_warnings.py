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


def test_warning_data_stale():
    """発表が 3 日より古い警報データは使わない（2026-05-28 の発表のまま止まっていて、5 か月前の濃霧注意報を出していた）"""
    import datetime
    import jma_alerts
    JST = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime(2026, 10, 25, 12, 0, tzinfo=JST)
    assert jma_alerts.warning_data_stale("2026-05-28T09:41:00+09:00", now) == "5/28"
    assert jma_alerts.warning_data_stale("2026-10-24T10:39:00+09:00", now) is None
    assert jma_alerts.warning_data_stale("", now) is None                     # 読めなければ止めない


# ---------------------------------------------------------------- 2026 年の新しい形（r8）
def _r8(dt, typ, kinds, head="", area="2321600"):
    return {"reportDatetime": dt, "dataTypeCode": typ, "infoType": "発表", "headlineText": head,
            "warning": {"class10Items": [], "class20Items": [{"areaCode": area, "kinds": kinds},
                                                           {"areaCode": "2310000", "kinds": [{"code": "03", "status": "発表"}]}]}}


R8_AICHI = [   # 2026-10-25 12 時ごろに Pi で見た愛知県（230000）の中身（常滑市の所）
    _r8("2026-09-26T07:26:00+09:00", "VPWW55", [{"status": "発表警報・注意報はなし"}], "注意報を解除します。"),
    _r8("2026-09-30T04:03:00+09:00", "VPWW56", [{"status": "発表警報・注意報はなし"}]),
    _r8("2026-10-14T20:41:00+09:00", "VPWW58", [{"code": "15", "status": "解除"}]),
    _r8("2026-10-25T04:42:00+09:00", "VPWW59", [{"code": "16", "status": "解除"}], "東部では、高波に注意してください。"),
    _r8("2026-10-25T04:42:00+09:00", "VPWW61", [{"code": "14", "status": "発表", "additions": ["突風", "ひょう"]}],
        "愛知県では、急な強い雨や落雷に注意してください。"),
]


def test_r8_active_warnings_for_tokoname():
    """常滑市は雷注意報（突風・ひょう）だけ。ほかの市の大雨警報・解除済みの注意報は出さない"""
    import jma_alerts
    assert jma_alerts.active_warning_names_r8(R8_AICHI, ("2321600",)) == ["雷注意報（突風・ひょう）"]
    assert jma_alerts.active_warning_names_r8(R8_AICHI, ("2310000",)) == ["大雨警報"]


def test_r8_latest_report_per_type_wins():
    """同じ種類の発表が 2 つあれば新しい方（発表 → 解除）"""
    import jma_alerts
    reports = [_r8("2026-10-25T04:42:00+09:00", "VPWW61", [{"code": "14", "status": "発表"}]),
               _r8("2026-10-25T09:00:00+09:00", "VPWW61", [{"code": "14", "status": "解除"}])]
    assert jma_alerts.active_warning_names_r8(reports, ("2321600",)) == []
    assert jma_alerts.headline_r8(R8_AICHI, ("2321600",)) == "愛知県では、急な強い雨や落雷に注意してください。"


def test_r8_headline_from_active_report_only():
    """見出しは、その市町村に発表中の警報・注意報がある発表のもの。あとから出た別の注意報の
    「注意報を解除します。」を、発表中の雷注意報に添えない（2026-10-25 20 時の 118）"""
    import jma_alerts
    reports = R8_AICHI + [_r8("2026-10-25T16:30:00+09:00", "VPWW59", [{"code": "16", "status": "解除"}],
                              "注意報を解除します。")]
    assert jma_alerts.active_warning_names_r8(reports, ("2321600",)) == ["雷注意報（突風・ひょう）"]
    assert jma_alerts.headline_r8(reports, ("2321600",)) == "愛知県では、急な強い雨や落雷に注意してください。"
    cleared = reports + [_r8("2026-10-25T21:00:00+09:00", "VPWW61", [{"code": "14", "status": "解除"}],
                             "注意報を解除します。")]
    assert jma_alerts.active_warning_names_r8(cleared, ("2321600",)) == []        # 雷も解除 → 発表なし
    assert jma_alerts.headline_r8(cleared, ("2321600",)) == ""


def test_r8_fetch_and_stale_feed():
    import datetime
    import pytest as _pytest
    import jma_alerts
    fresh = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    get = lambda url: R8_AICHI if url.endswith("230000.json") else {"latestControlDatetime": fresh}
    names, head = jma_alerts.fetch_warnings_r8("230000", ("2321600",), get_json=get)
    assert names == ["雷注意報（突風・ひょう）"]
    old = lambda url: R8_AICHI if url.endswith("230000.json") else {"latestControlDatetime": "2026-05-28T00:41:00Z"}
    with _pytest.raises(ValueError):
        jma_alerts.fetch_warnings_r8("230000", ("2321600",), get_json=old)
