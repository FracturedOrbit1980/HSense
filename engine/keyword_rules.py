"""Explicit keyword rules for high-friction customs categories.

These rules run before fuzzy search. They encode WCO heading terms that
commercial invoices rarely repeat verbatim: anti-seize is a lubricating
preparation of heading 34.03, a mastic stays in 32.14, and a retail glue of
not more than 1 kg stays in 35.06. The 8-digit line is then chosen from the
SARS split inside that heading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MASS = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|kgs|kilograms?|g|gr|grams?|mg|milligrams?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    heading: str
    prefer: str | None
    reasoning: str
    review: str = ""


def parse_mass_kg(text: str) -> float | None:
    """Return the first stated net mass in kilograms, ignoring bare quantities."""
    match = _MASS.search(text)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    if unit.startswith("mg") or unit.startswith("milligram"):
        return value / 1_000_000
    if unit.startswith("k"):
        return value
    return value / 1000.0


def _prefer_3403(description: str) -> str:
    aerosol = re.search(r"\baerosol\b|\bspray\b", description, re.IGNORECASE)
    petroleum = re.search(
        r"petroleum|mineral oils?|oil[-\s]?based", description, re.IGNORECASE
    )
    if petroleum and aerosol:
        return "3403.19.10"
    if petroleum:
        return "3403.19.90"
    if aerosol:
        return "3403.99.10"
    return "3403.99.90"


def _prefer_3214(description: str) -> str:
    surfacing = re.search(
        r"surfac|facade|skim coat|floor levell|rendering",
        description,
        re.IGNORECASE,
    )
    mastic = re.search(
        r"seal|mastic|caulk|putty|resin cement", description, re.IGNORECASE
    )
    if surfacing and not mastic:
        return "3214.90.00"
    return "3214.10.00"


def _prefer_3506(description: str) -> str:
    mass = parse_mass_kg(description)
    bulk_words = re.search(
        r"\b(drum|bulk|pail|ibc|hobbock)\b", description, re.IGNORECASE
    )
    bulk = (mass is not None and mass > 1) or (mass is None and bulk_words)
    if not bulk:
        return "3506.10.00"
    polymer = re.search(
        r"polymer|pva|polyvinyl|polyurethane|epoxy|rubber|acrylic|"
        r"cyanoacrylate|plastic|resin",
        description,
        re.IGNORECASE,
    )
    return "3506.91.00" if polymer else "3506.99.00"


def _prefer_2715(description: str) -> str:
    if re.search(r"mastic|seal", description, re.IGNORECASE):
        return "2715.00.20"
    if re.search(r"emulsion", description, re.IGNORECASE):
        return "2715.00.10"
    return "2715.00.90"


def _prefer_2523(description: str) -> str:
    if re.search(r"clinker", description, re.IGNORECASE):
        return "2523.10.00"
    if re.search(r"\bwhite\b", description, re.IGNORECASE):
        return "2523.21.00"
    if re.search(r"aluminous", description, re.IGNORECASE):
        return "2523.30.00"
    if re.search(r"portland", description, re.IGNORECASE):
        return "2523.29.00"
    return "2523.90.00"


def _duty(text: str) -> str:
    return text + " General duty: {duty} (SARS Schedule 1 Part 1, {schedule})."


def match_rules(description: str) -> RuleHit | None:
    text = " ".join(description.lower().split())

    if re.search(
        r"\bbituminous mastics?\b|\basphalt (?:sealants?|mastics?|compounds?)\b|"
        r"\bbitumen mastics?\b",
        text,
    ):
        return RuleHit(
            "bituminous_mastic_2715",
            "2715",
            _prefer_2715(description),
            _duty(
                "Classified under {hs_code} as a bituminous mastic. GRI 1 and "
                "Chapter 32 Note 1(c): mastics of asphalt or other bituminous "
                "mastics are excluded from Chapter 32 and fall in heading 27.15."
            ),
        )

    if re.search(r"\b(?:mechanical|oil|shaft|bearing)\s+seals?\b", text) and not re.search(
        r"sealant|sealing compound|mastic|caulk", text
    ):
        return RuleHit(
            "mechanical_seal_8484",
            "8484",
            "8484.20.00",
            _duty(
                "Classified under {hs_code} as a mechanical seal. GRI 1: heading "
                "84.84 covers mechanical seals. An oil seal or shaft seal is an "
                "article of machinery, not a chemical mastic of heading 32.14."
            ),
        )

    if re.search(r"\b(?:fuel|gasoline|petrol)\s+additives?\b|\boil additives?\b", text):
        return RuleHit(
            "oil_additive_3811",
            "3811",
            "3811.90.00",
            _duty(
                "Classified under {hs_code} as a prepared additive for mineral oils. "
                "GRI 1: heading 38.11 covers anti-knock preparations, oxidation "
                "inhibitors and other prepared additives for mineral oils or for "
                "other liquids used for the same purposes."
            ),
            "3811.90 is for fuel and oil additives. This description is that kind of additive.",
        )

    if re.search(r"\btectyl\b|\bardrox\s*av", text):
        spray = re.search(r"\baerosol\b|\bspray\b", text)
        code = "3403.19.10" if spray else "3403.19.90"
        return RuleHit(
            "surface_coating_3403_19",
            "3403",
            code,
            _duty(
                "Classified under {hs_code} as a petroleum-based anti-corrosion "
                "preparation. GRI 1: heading 34.03 covers anti-rust and anti-corrosion "
                "preparations. Heading 38.11 is for additives put into fuel or oil, "
                "not a coating applied to a surface. Subheading 3403.19 is the "
                "petroleum-oil split."
            ),
            "3811.90 is for fuel and oil additives. This is a surface anti-corrosion "
            "coating, so 3403.19 applies when it is petroleum-based.",
        )

    if re.search(r"\bcorban\b|\bcorrosion inhibitors?\b", text):
        return RuleHit(
            "surface_coating_3403_99",
            "3403",
            "3403.99.90",
            _duty(
                "Classified under {hs_code} as a surface anti-corrosion preparation. "
                "GRI 1: heading 34.03 covers anti-rust and anti-corrosion preparations. "
                "Heading 38.11 is limited to additives for mineral oils and similar "
                "liquids, not a compound applied to a metal surface."
            ),
            "Reclassified from fuel additives (3811.90) to a surface anti-corrosion "
            "preparation under 3403.99.",
        )

    if re.search(r"\bscotch\s*brite\b|\babrasive pads?\b|\bscouring pads?\b", text):
        return RuleHit(
            "abrasive_6805",
            "6805",
            "6805.30.00",
            _duty(
                "Classified under {hs_code} as abrasive powder or grain on a base. "
                "GRI 1: heading 68.05 covers natural or artificial abrasive on a base "
                "of textile, paper or other materials. A nylon scouring pad is on a "
                "base of other materials, so subheading 6805.30 applies."
            ),
            "Abrasive powder on a non-woven or synthetic base is 6805.30.",
        )

    if re.search(r"greaseproof", text) is None and re.search(
        r"\banti[-\s]?seize\b|\bcopper\s*slip\b|"
        r"\bmoly(?:bdenum)?\s+(?:paste|grease)\b|"
        r"\bthread lubricants?\b|\bfriction reduc(?:er|ing|tion)\b|"
        r"\bcutting[-\s]?oils?\b|\blithium greases?\b|\bbearing greases?\b|"
        r"\b(?:lubricating|multipurpose)\s+greases?\b|\bgreases?\b|\blubricants?\b|"
        r"\banti[-\s]?rust\b|\brust[-\s]?prevent",
        text,
    ) and not re.search(r"\b(?:gearbox|engine|hydraulic)\b", text):
        if re.search(r"\banti[-\s]?rust\b|\brust[-\s]?prevent", text) and re.search(
            r"\bpaint|enamel|lacquer|primer\b", text
        ):
            pass
        else:
            petroleum = re.search(r"petroleum|mineral oils?|oil[-\s]?based", text)
            split = (
                "The description names petroleum or mineral oil, so the split "
                "for preparations containing petroleum oils (3403.1) applies."
                if petroleum
                else "The invoice does not state that petroleum oils are the basic "
                "constituent, so the residual lubricating-preparation split 3403.99 applies."
            )
            return RuleHit(
                "lubricant_3403",
                "3403",
                _prefer_3403(description),
                _duty(
                    "Classified under {hs_code} as a lubricating preparation. "
                    "GRI 1: heading 34.03 covers lubricating preparations, including "
                    "cutting-oil preparations, bolt or nut release preparations, "
                    "anti-rust preparations and mould-release preparations. "
                    "Anti-seize and other friction reducers are bolt-release "
                    "preparations; they are not mastics of heading 32.14. "
                    "GRI 3(a) prefers this specific lubricating-preparation wording "
                    f"over a general sealant category. {split}"
                ),
                "Anti-seize and dry-film or synthetic lubricants are 3403.99, not sealants "
                "or surfacing preparations of 3214.90.",
            )

    if re.search(r"\b(?:gearbox|gear\s*box)\s+oils?\b|\baeroshell\b", text) and not re.search(
        r"\bmineral\b|\bpetroleum\b", text
    ):
        return RuleHit(
            "synthetic_gearbox_3403",
            "3403",
            "3403.99.90",
            _duty(
                "Classified under {hs_code} as a synthetic lubricating preparation. "
                "GRI 1: heading 34.03 covers lubricating preparations other than those "
                "based on petroleum oils. A synthetic gearbox oil is not a cosmetic of "
                "heading 33.04 and is not a petroleum oil of heading 27.10."
            ),
            "Synthetic gearbox lubricating oil is 3403.99. Heading 3304 is cosmetics "
            "and skincare, and heading 27.10 is for petroleum oils.",
        )

    if re.search(r"\bhydraulic\s+(?:oils?|fluids?)\b", text):
        mineral = re.search(r"\bmineral\b|\bpetroleum\b", text) and not re.search(
            r"\bsynthetic\b|\bnyco\b", text
        )
        if mineral:
            return RuleHit(
                "mineral_hydraulic_2710",
                "2710",
                "2710.19.80",
                _duty(
                    "Classified under {hs_code} as a petroleum hydraulic fluid. "
                    "GRI 1: heading 27.10 covers petroleum oils. Mineral-oil hydraulic "
                    "transmission fluids are named in subheading 2710.19."
                ),
                "Mineral-oil hydraulic fluid is 2710.19. Synthetic hydraulic fluid is 3403.99.",
            )
        return RuleHit(
            "synthetic_hydraulic_3403",
            "3403",
            "3403.99.90",
            _duty(
                "Classified under {hs_code} as a synthetic lubricating preparation. "
                "GRI 1: heading 34.03 covers lubricating preparations that are not "
                "70 per cent or more petroleum oil. A synthetic aviation hydraulic "
                "fluid is not a cosmetic of heading 33.04."
            ),
            "Synthetic hydraulic fluid is 3403.99. Mineral-oil hydraulic fluid is "
            "2710.19. Heading 3304 is cosmetics and cannot apply.",
        )

    if re.search(
        r"\b(?:engine|motor|gear|crankcase)\s+oils?\b",
        text,
    ) and not re.search(r"cutting[-\s]?oil|gearbox|gear\s*box", text):
        return RuleHit(
            "petroleum_oil_2710",
            "2710",
            None,
            _duty(
                "Classified under {hs_code} as a petroleum oil. GRI 1: heading 34.03 "
                "excludes preparations whose basic constituents are 70 per cent or "
                "more by mass of petroleum oils. Engine and motor oils of that kind "
                "fall in heading 27.10."
            ),
            "Engine and motor oils that are petroleum oils fall in heading 27.10.",
        )

    if re.search(
        r"\b(?:portland|aluminous|hydraulic|slag)\s+cements?\b|\bcement clinkers?\b",
        text,
    ):
        return RuleHit(
            "hydraulic_cement_2523",
            "2523",
            _prefer_2523(description),
            _duty(
                "Classified under {hs_code} as a hydraulic cement. GRI 1: heading "
                "25.23 covers Portland cement, aluminous cement and similar hydraulic "
                "cements. This is not a resin cement or mastic of heading 32.14."
            ),
        )

    if re.search(
        r"\b(?:sealants?|sealing compounds?|caulks?|caulking(?:\s+compounds?)?|"
        r"mastics?|putties|putty|glaziers?'?\s+putty|resin cements?|"
        r"painters?'?\s+fillings?|silicone sealants?|pro\s*seals?|rtv)\b",
        text,
    ):
        prefer = _prefer_3214(description)
        if prefer == "3214.90.00":
            body = (
                "Classified under {hs_code} as a non-refractory surfacing "
                "preparation. GRI 1: heading 32.14 covers mastics and "
                "non-refractory surfacing preparations for facades, walls, floors "
                "and ceilings. The goods are not described as putty, caulk or "
                "mastic, so residual subheading 3214.90 applies (GRI 3(a))."
            )
        else:
            body = (
                "Classified under {hs_code} as a mastic or sealing compound. "
                "GRI 1: heading 32.14 covers glaziers' putty, grafting putty, "
                "resin cements, caulking compounds and other mastics, and "
                "painters' fillings. Subheading 3214.10 names those goods; "
                "residual subheading 3214.90 is for other surfacing preparations, "
                "so GRI 3(a) selects 3214.10. Chapter 32 Note 1(c) sends bituminous "
                "mastics to heading 27.15, and this description is not bituminous."
            )
        return RuleHit(
            "mastic_3214",
            "3214",
            prefer,
            _duty(body),
            "Mastics, sealants and caulking compounds are 3214.10. "
            "3214.90 is only for non-refractory wall and facade surfacing preparations.",
        )

    if re.search(
        r"\b(?:glues?|adhesives?|superglue|super glue|cyanoacrylates?|"
        r"wood glues?|contact adhesives?|loctite)\b|\bpva\b",
        text,
    ):
        prefer = _prefer_3506(description)
        mass = parse_mass_kg(description)
        if prefer == "3506.10.00":
            mass_text = (
                f"The stated pack mass is {mass:g} kg, which does not exceed 1 kg."
                if mass is not None
                else "No pack above 1 kg is stated, so the retail put-up of subheading 3506.10 is applied."
            )
        elif prefer == "3506.91.00":
            mass_text = (
                "The pack exceeds 1 kg and the adhesive is polymer or rubber based, "
                "so subheading 3506.91 applies rather than the retail subheading 3506.10."
            )
        else:
            mass_text = (
                "The pack exceeds 1 kg, so the goods are outside the retail "
                "subheading 3506.10 and fall in residual subheading 3506.99."
            )
        return RuleHit(
            "adhesive_3506",
            "3506",
            prefer,
            _duty(
                "Classified under {hs_code} as a prepared glue or adhesive. "
                "GRI 1: heading 35.06 covers prepared glues and other prepared "
                "adhesives, including products put up for retail sale as glues "
                f"not exceeding a net mass of 1 kg. {mass_text}"
            ),
            "Adhesives and glues put up for retail sale at 1 kg or less are 3506.10.",
        )

    return None


def expand_query(description: str) -> str:
    """Add HS wording for commercial names the tariff does not use."""
    extras: list[str] = []
    text = description.lower()
    if re.search(r"\blaptops?\b|\bnotebook computers?\b", text):
        extras.append("portable automatic data processing machine")
    if re.search(r"\bt-?shirts?\b", text):
        extras.append("t-shirt singlet knitted vest")
    if re.search(r"\bhex(?:agon)?(?:agonal)?\b", text) and re.search(r"\b(?:screw|bolt)s?\b", text):
        extras.append("hexagon head screw bolt threaded stainless")
    if re.search(r"\broasted\b", text) and re.search(r"\bcoffee\b", text):
        extras.append("coffee roasted")
    if re.search(r"\bbeer\b", text):
        extras.append("beer made from malt")
    if not extras:
        return description
    return description + " " + " ".join(extras)
