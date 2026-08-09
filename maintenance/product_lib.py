# Shared helpers for the product attribute cleanup (survey / dry-run / review sheet).
# Imported by product_cleanup_dry.py and product_review_sheet.py.
import re
import unicodedata

# A value is "description-stuffed" when it is too long or too wordy to be a spec.
STUFFED_LEN = 30
STUFFED_WORDS = 4

# Unit-bearing spec token, e.g. "5000W", "20kW", "2.5MM²", "7.5CV", "48V", "200AH".
# NOTE: a bare "M" is deliberately NOT a unit — in this catalogue it is a model
# suffix ("LUNA2000 60M", "BACKUP BOX 12M"), and treating it as one produced
# nonsense proposals like 'BACKUP BOX TRIPHASE POUR LUNA2000 12M' -> '12M'.
UNIT = r"(?:KVA|KWH|KWC|KW|WC|W|VDC|VAC|V|AH|A|MM2|MM²|CV|KLT)"
SPEC_RE = re.compile(r"(?<![A-Za-z0-9.,-])(\d+(?:[.,]\d+)?)\s*(" + UNIT + r")\b", re.I)

# Model/reference code, e.g. "SUN2000-20KTL-M5", "X1-1.1S", "GRL8-02".
REF_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,}(?:[-./][A-Z0-9]+){1,})\b")

# Attributes whose value should be a reference/model code rather than a spec.
REF_ATTRS = ("ref", "reference", "modele", "modèle", "serie")


def norm(s):
    """Accent/case/punctuation-insensitive key for name comparison."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def is_stuffed(name):
    name = name or ""
    return len(name) > STUFFED_LEN or len(name.split()) >= STUFFED_WORDS


def propose(attr_name, raw):
    """Suggest a clean value for a stuffed one.

    Returns (proposal, confidence, why). confidence is 'AUTO' only when exactly
    one unambiguous token was found — everything else is 'REVIEW' and must be
    decided by a human.
    """
    txt = (raw or "").strip()
    an = norm(attr_name)
    prefer_ref = any(an.startswith(k) or k in an for k in REF_ATTRS)

    refs = [r for r in REF_RE.findall(txt.upper()) if any(c.isdigit() for c in r)]
    specs = ["".join(m).replace(",", ".").upper().replace(" ", "")
             for m in SPEC_RE.findall(txt)]
    specs = list(dict.fromkeys(specs))

    if prefer_ref:
        if len(refs) == 1:
            return refs[0], "AUTO", "single_reference_code"
        if refs:
            return refs[0], "REVIEW", "%d_reference_codes" % len(refs)
        return "", "REVIEW", "no_reference_code_found"

    if len(specs) == 1:
        return specs[0], "AUTO", "single_spec_token"
    if len(specs) > 1:
        return " / ".join(specs), "REVIEW", "%d_spec_tokens" % len(specs)
    if len(refs) == 1:
        return refs[0], "REVIEW", "only_a_reference_code"
    return "", "REVIEW", "nothing_extractable"


def classify(attr_name, raw):
    """propose() + the guard that demotes empty / no-op proposals to REVIEW."""
    prop, conf, why = propose(attr_name, raw)
    if not prop:
        return prop, "REVIEW", why
    if norm(prop) == norm(raw):
        return prop, "REVIEW", "proposal_equals_current"
    return prop, conf, why


# Proposals that are syntactically right but semantically doubtful — the unit
# found is not the spec the attribute is actually about. Kept out of any
# auto-apply set until a human rules on them.
FLAGGED_VALUE_HINTS = {
    "40A": "MPPT charge current, not the inverter power (PLI 1000-12 is 1000W)",
    "80A": "MPPT charge current, not the inverter power",
    "CORE-1": "product line, not the model — 'STP 50-21' is likelier",
    "LT-G2": "drops the 'Pro' qualifier",
}
