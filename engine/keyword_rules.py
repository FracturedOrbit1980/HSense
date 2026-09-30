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

    if re.search(
        r"\bcorrosion inhibitors?\b|\btectyl\b|\bcorban\b|\bardrox\s*av\b",
        text,
    ):
        return RuleHit(
            "corrosion_inhibitor_3811",
            "3811",
            "3811.90.00",
            _duty(
                "Classified under {hs_code} as an anti-corrosive preparation. "
                "GRI 1: heading 38.11 covers anti-corrosive preparations and other "
                "prepared additives for mineral oils or for other liquids used for "
                "the same purposes. The description is not an anti-knock preparation "
                "or an additive confined to lubricating oils, so residual subheading "
                "3811.90 applies."
            ),
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
            )

    if re.search(
        r"\b(?:engine|motor|gear|gearbox|gear\s*box|crankcase|hydraulic)\s+(?:oils?|fluids?)\b",
        text,
    ) and not re.search(r"cutting[-\s]?oil", text):
        return RuleHit(
            "petroleum_oil_2710",
            "2710",
            None,
            _duty(
                "Classified under {hs_code} as a petroleum oil. GRI 1: heading 34.03 "
                "excludes preparations whose basic constituents are 70 per cent or "
                "more by mass of petroleum oils. Engine, gear and motor oils of that "
                "kind fall in heading 27.10."
            ),
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
        r"painters?'?\s+fillings?|silicone sealants?|pro\s*seals?)\b",
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
        return RuleHit("mastic_3214", "3214", prefer, _duty(body))

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
