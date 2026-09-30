from data.tariff_db import TariffDB
from engine.classifier import WCOClassifier, classify_extracted_lines
from engine.keyword_rules import parse_mass_kg
from parsers.line_items import LineItem


def setup_module():
    global DB, CLASSIFIER
    DB = TariffDB()
    CLASSIFIER = WCOClassifier(DB)


def teardown_module():
    DB.close()


def test_schedule_covers_the_sars_nomenclature():
    assert DB.leaf_count > 8000
    assert int(DB.meta["chapter_count"]) >= 97
    sealant = DB.get("3214.10.00")
    anti = DB.get("3403.99.90")
    glue = DB.get("3506.10.00")
    assert sealant is not None and sealant.duty_general == "Free"
    assert anti is not None and anti.duty_general == "Free"
    assert glue is not None and glue.duty_general == "Free"
    assert "mastic" in sealant.description.lower()
    assert "lubricat" in anti.legal_path.lower()
    beef = DB.get("0201.10.00")
    assert beef is not None and beef.duty_general == "40% or 240c/kg"


def test_sealing_compound_is_a_mastic_not_a_lubricant():
    result = CLASSIFIER.classify("Sealing compound - TIN", part_number="CS1900", quantity=10)
    assert result.hs_code == "3214.10.00"
    assert result.duty_rate_general == "Free"
    assert result.rule_id == "mastic_3214"
    assert "3214" in result.wco_reasoning
    assert "GRI 1" in result.wco_reasoning
    payload = result.as_dict(1)
    assert list(payload) == [
        "line_number",
        "source_file",
        "part_number",
        "description",
        "quantity",
        "hs_code",
        "duty_rate_general",
        "wco_reasoning",
    ]


def test_anti_seize_is_a_lubricating_preparation():
    result = CLASSIFIER.classify("Anti Seize Compound - 500g", part_number="ANTI-SEIZE", quantity=5)
    assert result.hs_code == "3403.99.90"
    assert result.duty_rate_general == "Free"
    assert result.rule_id == "lubricant_3403"
    assert "32.14" in result.wco_reasoning
    assert "not" in result.wco_reasoning.lower()


def test_retail_adhesive_under_1kg():
    assert parse_mass_kg("PVA wood adhesive - 750g") == 0.75
    result = CLASSIFIER.classify("PVA wood adhesive - 750g")
    assert result.hs_code == "3506.10.00"
    assert result.duty_rate_general == "Free"


def test_bulk_polymer_adhesive():
    result = CLASSIFIER.classify("PVA adhesive 25kg drum")
    assert result.hs_code == "3506.91.00"


def test_bituminous_mastic_is_excluded_from_chapter_32():
    result = CLASSIFIER.classify("Bituminous mastic for roof joints")
    assert result.hs_code == "2715.00.20"
    assert result.duty_rate_general == "20%"


def test_mechanical_seal_is_not_a_chemical_sealant():
    result = CLASSIFIER.classify("Mechanical seal for pump shaft")
    assert result.hs_code == "8484.20.00"


def test_portland_cement_and_engine_oil_and_fastener():
    cement = CLASSIFIER.classify("Portland cement 50 kg bag")
    assert cement.hs_code == "2523.29.00"
    assert cement.duty_rate_general == "Free"

    oil = CLASSIFIER.classify("Engine oil 5L")
    assert oil.hs_code.startswith("2710")
    assert oil.rule_id == "petroleum_oil_2710"

    screw = CLASSIFIER.classify("Hexagon head screw, stainless steel")
    assert screw.hs_code == "7318.15.37"
    assert screw.duty_rate_general == "10%"


def test_leonardo_lines_and_ditto_display():
    seal = CLASSIFIER.classify("Pro Seal - TIN")
    assert seal.hs_code == "3214.10.00"
    inhibitor = CLASSIFIER.classify("Corrosion Inhibitor - 500ML")
    assert inhibitor.hs_code == "3403.99.90"
    tectyl = CLASSIFIER.classify("TECTYL 891D Corrosion Inhibitor - 500ML")
    assert tectyl.hs_code == "3403.19.90"
    ardrox = CLASSIFIER.classify("ARDROX AV40 Compound : Corrosion Inhibitor - LT")
    assert ardrox.hs_code == "3403.19.90"
    gearbox = CLASSIFIER.classify("AEROSHELL 555 Main Gearbox Oil - LT")
    assert gearbox.hs_code == "3403.99.90"
    pad = CLASSIFIER.classify("Scotch Brite")
    assert pad.hs_code == "6805.30.00"
    fluid = CLASSIFIER.classify("Nyco Hydraulic Fluid - LT")
    assert fluid.hs_code == "3403.99.90"
    glue = CLASSIFIER.classify("Loctite - 50Ml")
    assert glue.hs_code == "3506.10.00"
    film = CLASSIFIER.classify("Solidfilm Lubricant - TIN")
    assert film.hs_code == "3403.99.90"

    rows = classify_extracted_lines(
        CLASSIFIER,
        [
            LineItem("CS1900", "Sealing compound - TIN", 1, "a", noted_code="3214.90.00"),
            LineItem("AC-730", "Pro Seal - TIN", 1, "b", noted_code="3214.90.00", same_as_above=True),
            LineItem("X", "Acrylic Adhesive - 40ML", 1, "c"),
        ],
        "invoice.jpg",
    )
    assert rows[0]["hs_code"] == "3214.10.00"
    assert rows[0]["handwritten"] == "3214.90.00"
    assert rows[0]["flag"] == "incorrect"
    assert rows[1]["handwritten_shown"] == '3214.90.00 "'
    assert rows[1]["handwritten"] == "3214.90.00"
    assert rows[1]["flag"] == "incorrect"
    assert rows[1]["hs_code"] == "3214.10.00"
    assert rows[2]["hs_code"] == "3506.10.00"
    assert rows[2]["flag"] == ""

    matched = classify_extracted_lines(
        CLASSIFIER,
        [LineItem("CS1900", "Sealing compound - TIN", 1, "a", noted_code="3214.10.00")],
        "invoice.jpg",
    )
    assert matched[0]["flag"] == "ok"
    critical = classify_extracted_lines(
        CLASSIFIER,
        [LineItem("OIL", "Main Gearbox Oil - LT", 1, "a", noted_code="3304.99.90")],
        "invoice.jpg",
    )
    assert critical[0]["hs_code"] == "3403.99.90"
    assert critical[0]["flag"] == "critical"


def test_common_goods_follow_heading_terms():
    shirt = CLASSIFIER.classify("Cotton t-shirt")
    assert shirt.hs_code == "6109.10.00"
    beer = CLASSIFIER.classify("Beer made from malt")
    assert beer.hs_code == "2203.00.90"
    laptop = CLASSIFIER.classify("Laptop computer")
    assert laptop.hs_code == "8471.30.90"
    coffee = CLASSIFIER.classify("Roasted coffee beans")
    assert coffee.hs_code.startswith("0901.2")
