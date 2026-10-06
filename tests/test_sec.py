import pytest

from analyst import sec

FILLER = "<p>" + ("Our business faces many risks that could harm results. " * 20) + "</p>\n"


def doc(*blocks: str) -> str:
    return "<html><body>" + "".join(blocks) + "</body></html>"


def toc():
    return ("<table><tr><td>Item 1A.</td><td>Risk Factors</td><td>5</td></tr>"
            "<tr><td>Item 1B.</td><td>Unresolved Staff Comments</td><td>9</td></tr>"
            "<tr><td>Item 2.</td><td>Properties</td><td>9</td></tr></table>")


def test_extracts_real_section_not_table_of_contents():
    html = doc(toc(), "<p>Item 1. Business</p>", FILLER,
               "<div>Item 1A. Risk Factors</div>", FILLER * 3,
               "<div>Item 1B. Unresolved Staff Comments</div>", "<p>None.</p>")
    text = sec.extract_section(html, "item1a")
    assert text.startswith("Item 1A. Risk Factors")
    assert "Unresolved Staff" not in text
    assert text.count("Our business faces") >= 60


def test_ignores_cross_reference_links_in_business_section():
    # Regression: WMT/PFE filings link to "Item 1A. Risk Factors" from Item 1, with lowercase text after.
    html = doc(toc(), "<p>Item 1. Business</p>", FILLER,
               '<p>see <a>Item 1A. Risk Factors</a> under the sub-caption "Legal"</p>', FILLER,
               "<div>ITEM 1A. RISK FACTORS</div>", FILLER * 3,
               "<div>ITEM 1B. UNRESOLVED STAFF COMMENTS</div>")
    text = sec.extract_section(html, "item1a")
    assert text.startswith("ITEM 1A. RISK FACTORS")
    assert "sub-caption" not in text


def test_handles_heading_split_mid_word():
    # MSFT's filing literally splits "ITEM 1A. RIS" / "K FACTORS" across lines.
    html = doc(toc(), "<div>ITEM 1A. RIS</div><div>K FACTORS</div>", FILLER * 3,
               "<div>ITEM 1B. UNRESOLVED STAFF COMMENTS</div>")
    assert "Our business faces" in sec.extract_section(html, "item1a")


def test_accepts_dash_separator():
    html = doc(toc(), "<div>Item 1A-Risk Factors</div>", FILLER * 3, "<div>Item 1B-Unresolved</div>")
    assert sec.extract_section(html, "item1a").startswith("Item 1A-Risk Factors")


def test_section_can_end_at_item_2_when_1b_is_absent():
    html = doc(toc(), "<div>Item 1A. Risk Factors</div>", FILLER * 3, "<div>Item 2. Properties</div>")
    assert "Our business faces" in sec.extract_section(html, "item1a")


def test_missing_section_raises():
    with pytest.raises(sec.FilingNotFoundError):
        sec.extract_section(doc("<p>Nothing relevant here</p>"), "item1a")


def test_too_short_section_raises():
    html = doc("<div>Item 1A. Risk Factors</div><p>Short.</p><div>Item 1B. Unresolved</div>")
    with pytest.raises(sec.FilingNotFoundError, match="parsing miss"):
        sec.extract_section(html, "item1a")


def test_unknown_section_name():
    with pytest.raises(ValueError):
        sec.extract_section(doc(), "item99")


def test_non_ascii_is_normalised_not_deleted():
    html = doc("<div>Item 1A. Risk Factors</div>",
               "<p>We don’t control suppliers — a risk. " * 1 + FILLER * 3 + "</p>",
               "<div>Item 1B. Unresolved</div>")
    text = sec.extract_section(html, "item1a")
    assert "don't control suppliers - a risk" in text


def test_truncate_at_boundary():
    text = "First paragraph. " * 50 + "\n\n" + "Second paragraph. " * 50
    short, cut = sec.truncate_at_boundary(text, 1000)
    assert cut and len(short) <= 1000 and short.endswith(".")
    whole, cut = sec.truncate_at_boundary("tiny", 1000)
    assert whole == "tiny" and not cut
