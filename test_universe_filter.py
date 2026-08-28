from data import exclusion_reason


def test_excludes_reit_by_name():
    assert exclusion_reason({"company_name": "Example REIT"}) == "REIT"


def test_excludes_reit_by_classification():
    assert exclusion_reason({"company_name": "Example Property", "security_type": "Real Estate Investment Trust"}) == "REIT"


def test_excludes_business_trust_phrase():
    assert exclusion_reason({"company_name": "Example Business Trust"}) == "Business Trust"


def test_excludes_named_trust_without_subtype():
    assert exclusion_reason({"company_name": "Example Infrastructure Trust"}) == "Trust / Business Trust"


def test_keeps_operating_company_and_penny_stock():
    assert exclusion_reason({"company_name": "Example Holdings Ltd", "sector": "Industrials"}) is None
