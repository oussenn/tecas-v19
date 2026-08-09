# TECAS phone normalizer — shared logic for dry-run and apply.
# Target: Moroccan numbers -> "+212 XXX-XXXXXX" (3-6 grouping, uniform for mobile & landline)
#         Foreign numbers   -> phonenumbers INTERNATIONAL ("+CC ...")
import phonenumbers as pn

def normalize(raw, default_region="MA"):
    """Return (normalized_or_None, kind). kind in:
       empty, unparseable, invalid, ma, intl."""
    if not raw or not raw.strip():
        return None, "empty"
    # strip Excel apostrophe + surrounding junk, keep + and digits/spaces/-/()
    s = raw.strip().lstrip("'").strip()
    try:
        num = pn.parse(s, default_region)
    except pn.NumberParseException:
        return None, "unparseable"
    if not pn.is_valid_number(num):
        return None, "invalid"
    if num.country_code == 212:
        nsn = str(num.national_number)
        if len(nsn) != 9:
            return None, "invalid"
        return f"+212 {nsn[:3]}-{nsn[3:]}", "ma"
    return pn.format_number(num, pn.PhoneNumberFormat.INTERNATIONAL), "intl"
