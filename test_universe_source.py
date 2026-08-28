import pandas as pd
from data import _extract_stockanalysis_table, _normalise_name, exclusion_reason


def test_stockanalysis_table_parsing():
    html = '''<table><thead><tr><th>No.</th><th>Symbol</th><th>Company Name</th></tr></thead>
    <tbody><tr><td>1</td><td>D05</td><td>DBS Group Holdings Ltd</td></tr>
    <tr><td>2</td><td>O39</td><td>Oversea-Chinese Banking Corporation Limited</td></tr></tbody></table>'''
    df = _extract_stockanalysis_table(html)
    assert list(df["Code"]) == ["D05", "O39"]


def test_global_quote_exclusion_by_normalised_name():
    names = {_normalise_name("Tencent Holdings Limited")}
    reason = exclusion_reason({"ticker": "HTCD", "company_name": "Tencent Holdings Ltd"}, names)
    assert reason == "Global Quote / SDR"


def test_penny_company_is_not_excluded():
    assert exclusion_reason({"ticker": "1A1", "company_name": "Example Holdings Limited"}, set()) is None


def test_reit_and_business_trust_exclusions():
    assert exclusion_reason({"ticker": "AAA", "company_name": "Example REIT"}, set()) == "REIT"
    assert exclusion_reason({"ticker": "BBB", "company_name": "Example Business Trust"}, set()) == "Business Trust"
