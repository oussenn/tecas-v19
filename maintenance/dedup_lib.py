# Safe-merge classifier for Odoo data_merge groups (res.partner only).
# A group is SAFE only if all records are clearly the SAME entity.
import sys, re, unicodedata
sys.path.insert(0, "/tmp")
from phone_normalize import normalize as _norm_phone

SIM_MIN = 0.90

# Honorifics/titles stripped before identity + token-count checks, so that
# "MR MOSTAPHA" -> "mostapha" (1 token) is rejected as a bare first name,
# while "MR Brahim BAADI" -> "brahim baadi" (2 tokens) is kept.
TITLES = {"mr", "mrs", "mme", "mlle", "m", "mister", "miss", "monsieur", "madame",
          "dr", "pr", "prof", "sidi", "si", "haj", "hajj", "elhaj", "lhaj",
          "hadj", "lhadj", "ste", "sté", "ets"}

def norm_name(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    toks = [t for t in s.split() if t not in TITLES]
    return " ".join(toks)

def phone_key(s):
    """Conflict key: canonical form if valid, else raw digits. None if empty.
    Two records 'conflict' when they have >1 distinct key -> different numbers,
    even when both are invalid (e.g. fake test numbers 060606060 vs 050505050)."""
    if not s or not s.strip():
        return None
    n, _ = _norm_phone(s)
    if n:
        return n
    d = re.sub(r"\D", "", s)
    return "raw:" + d if d else None

def _sim(group):
    s = group.similarity or 0.0
    return s / 100.0 if s > 1 else s

def classify(env, group):
    """Return dict: decision ('SAFE'/'SKIP'), reason, survivor, partners info."""
    sim = _sim(group)
    recs = group.record_ids.filtered(lambda r: not r.is_discarded)
    partner_ids = [rid for rid in recs.mapped("res_id") if rid]
    partners = env["res.partner"].with_context(active_test=False).browse(partner_ids).exists()
    ids = partners.ids
    info = {
        "group_id": group.id,
        "similarity": round(sim, 3),
        "partner_ids": ids,
        "names": [p.name or "" for p in partners],
        "phones": [p.phone or "" for p in partners],
        "survivor": None,
    }
    if len(partners) < 2:
        info.update(decision="SKIP", reason="fewer_than_2_live_records"); return info

    # survivor = oldest active (mirror Odoo _elect_method)
    survivor = env[group.res_model_name]._elect_method(partners)
    info["survivor"] = survivor.id if survivor else None

    if sim < SIM_MIN:
        info.update(decision="SKIP", reason="similarity_below_%d" % int(SIM_MIN*100)); return info

    names = {norm_name(n) for n in info["names"]}
    if len(names) != 1 or "" in names:
        info.update(decision="SKIP", reason="names_not_identical"); return info
    if len(next(iter(names)).split()) < 2:
        info.update(decision="SKIP", reason="single_token_name"); return info

    if len({p.company_type for p in partners}) != 1:
        info.update(decision="SKIP", reason="mixed_company_type"); return info

    phones = {k for k in (phone_key(p.phone) for p in partners) if k}
    if len(phones) > 1:
        info.update(decision="SKIP", reason="conflicting_phones"); return info

    emails = {(p.email or "").strip().lower() for p in partners if p.email}
    if len(emails) > 1:
        info.update(decision="SKIP", reason="conflicting_emails"); return info

    if env["res.users"].with_context(active_test=False).search_count([("partner_id", "in", ids)]):
        info.update(decision="SKIP", reason="linked_to_user"); return info

    info.update(decision="SAFE", reason="identical_name_no_conflict")
    return info
