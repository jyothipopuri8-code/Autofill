"""Canonical field taxonomy and the deterministic rules that recognise each field (doc §11, §14).

Rules look at normalised text (lowercase, camelCase and punctuation split into words).
``label`` patterns apply to the visible label/legend/aria-label, ``attr`` patterns to
name/id/placeholder, and ``autocomplete`` uses the HTML autocomplete tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from autofill_agent.db.enums import SensitiveField


@dataclass(frozen=True)
class Spec:
    key: str
    label: tuple[str, ...] = ()
    attr: tuple[str, ...] = ()
    autocomplete: tuple[str, ...] = ()
    input_types: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()          # if any matches the label text, this spec is rejected
    section: str | None = None          # only considered inside this repeatable section
    kinds: tuple[str, ...] = ()         # allowed control kinds (empty = any)
    sensitive: bool = False
    resume_based: bool = False          # value comes from the tailored resume
    category: str = "profile"           # profile | sensitive | resume | calc | legal | security | file | custom


TEXTY = ("text", "email", "tel", "number", "url", "textarea", "autocomplete", "unknown", "custom_select", "select")
CHOICE = ("select", "custom_select", "radio_group", "checkbox", "checkbox_group", "text", "autocomplete", "unknown")
DATEY = ("text", "date", "month_year", "select", "custom_select", "autocomplete", "unknown")


def _s(key, label=(), attr=(), ac=(), types=(), deny=(), section=None, kinds=(), sensitive=False, resume=False, cat="profile"):
    return Spec(key, tuple(label), tuple(attr), tuple(ac), tuple(types), tuple(deny), section, tuple(kinds), sensitive, resume, cat)


SPECS: list[Spec] = [
    # --- personal ---------------------------------------------------------
    _s("personal.first_name", [r"\b(legal |candidate |applicant )?first name\b", r"\bgiven name\b", r"\bforename\b"],
       [r"^(f ?name|first ?name|first|given ?name|forename|candidate first name)$", r"\bfirst name\b"], ["given-name"],
       deny=[r"\bpreferred\b"], kinds=TEXTY),
    _s("personal.last_name", [r"\b(legal |candidate |applicant )?last name\b", r"\bfamily name\b", r"\bsurname\b"],
       [r"^(l ?name|last ?name|last|surname|family ?name|candidate last name)$", r"\blast name\b"], ["family-name"], kinds=TEXTY),
    _s("personal.middle_name", [r"\bmiddle (name|initial)\b"], [r"^(middle ?name|mname|middle)$"], ["additional-name"], kinds=TEXTY),
    _s("personal.preferred_name", [r"\bpreferred (first )?name\b", r"\bnick ?name\b", r"\bgo(es)? by\b"], [r"\bpreferred name\b", r"^nickname$"], kinds=TEXTY),
    _s("personal.full_name", [r"^(your |legal |candidate |applicant )?(full )?name$", r"\bfull name\b", r"\blegal name\b", r"^your name$"],
       [r"^(full ?name|name|your ?name|applicant ?name|candidate ?name)$"], ["name"], kinds=TEXTY),
    _s("personal.pronouns", [r"\bpronouns?\b"], [r"^pronouns?$"], kinds=TEXTY + ("radio_group",)),
    # --- contact ----------------------------------------------------------
    _s("contact.email", [r"\be ?mail( address)?\b"], [r"\be ?mail\b"], ["email"], ["email"], kinds=TEXTY),
    _s("contact.phone", [r"\b(phone|mobile|cell|telephone|contact)( phone)?( number| no)?\b"], [r"^(phone|tel|telephone|mobile|cell|phone ?number)$", r"\bphone\b"],
       ["tel", "tel-national"], ["tel"], deny=[r"\bextension\b", r"\bcountry code\b", r"\b(device|phone) type\b", r"\bemail\b", r"\bcode\b"], kinds=TEXTY),
    _s("contact.phone_country_code", [r"\b(phone |dialing |calling )?country code\b", r"\bphone code\b"], [r"country ?code", r"phone ?code"], ["tel-country-code"], kinds=TEXTY),
    _s("contact.phone_device_type", [r"\b(phone|device) type\b", r"\bphone device\b"], [r"phone ?type", r"device ?type"], kinds=TEXTY + ("radio_group",)),
    _s("contact.phone_extension", [r"\bphone extension\b", r"^extension$"], [r"extension"], ["tel-extension"], kinds=TEXTY),
    _s("contact.linkedin", [r"\blinked ?in\b"], [r"linked ?in"], types=("url",), kinds=TEXTY),
    _s("contact.github", [r"\bgit ?hub\b"], [r"git ?hub"], kinds=TEXTY),
    _s("contact.portfolio", [r"\bportfolio\b", r"\bpersonal (web ?site|page)\b"], [r"portfolio"], kinds=TEXTY),
    _s("contact.website", [r"\bweb ?site\b", r"\bpersonal url\b", r"\bother (url|link)s?\b", r"\bblog\b"], [r"web ?site", r"^url$"], ["url"], kinds=TEXTY),
    # --- location ---------------------------------------------------------
    _s("location.address_line1", [r"\b(street )?address( line)?( 1| one)?\b", r"\bstreet\b"], [r"address ?(line)? ?1?$", r"^street"], ["address-line1", "street-address"],
       deny=[r"\bemail\b", r"\bip\b", r"\bline 2\b", r"\bweb\b"], kinds=TEXTY),
    _s("location.address_line2", [r"\baddress line 2\b", r"\b(apt|apartment|suite|unit)\b"], [r"address ?(line)? ?2"], ["address-line2"], kinds=TEXTY),
    _s("location.city", [r"\bcity\b", r"\btown\b"], [r"^city$", r"\bcity\b"], ["address-level2"], deny=[r"\bstate\b.*\bcity\b"], kinds=TEXTY),
    _s("location.state", [r"\bstate\b", r"\bprovince\b", r"\bregion\b"], [r"^(state|province|region)$"], ["address-level1"],
       deny=[r"\bunited states\b"], kinds=TEXTY),
    _s("location.country", [r"\bcountry\b"], [r"^country$"], ["country", "country-name"], deny=[r"\bcode\b", r"\bphone\b", r"\bcitizen"], kinds=TEXTY),
    _s("location.postal_code", [r"\b(zip|postal|post) ?(code)?\b", r"\bpostcode\b"], [r"zip", r"postal", r"post ?code"], ["postal-code"], kinds=TEXTY),
    _s("location.location", [r"^(current |your |preferred )?location\b", r"\bwhere are you (located|based)\b", r"\bcity,? state\b"], [r"^location$"], kinds=TEXTY),
    # --- work authorization ----------------------------------------------
    _s("work_auth.sponsorship_any", [r"\bnow or in the future\b.*\bsponsor", r"\b(now|currently) (and|or) (in the )?future\b.*\bsponsor", r"\bh ?1 ?b\b.*\bsponsor", r"\bsponsor\w*\b.*\b(now or in the future|now and in the future)\b"], kinds=CHOICE, cat="profile"),
    _s("work_auth.sponsorship_future", [r"\bsponsor\w*\b.*\bfuture\b", r"\bfuture\b.*\bsponsor"], kinds=CHOICE),
    _s("work_auth.sponsorship_now", [r"\bsponsor", r"\bvisa\b.*\b(require|need)"], [r"sponsor"], kinds=CHOICE),
    _s("work_auth.authorized_to_work", [r"\b(legally |lawfully )?(authorized|eligible|permitted|legal) .*\bwork\b", r"\bright to work\b", r"\bwork authori[sz]ation\b",
       r"\bwork (legally|lawfully)\b"], [r"authori[sz]ed.*work", r"work.*authori"], kinds=CHOICE),
    # --- preferences / answer library ------------------------------------
    _s("preferences.relocate", [r"\b(willing|open|able|prepared) to relocate\b", r"\brelocat"], kinds=CHOICE),
    _s("preferences.travel", [r"\btravel\b"], kinds=CHOICE + ("textarea",)),
    _s("preferences.remote", [r"\bremote\b"], kinds=CHOICE, deny=[r"\bexperience\b"]),
    _s("preferences.hybrid", [r"\bhybrid\b"], kinds=CHOICE),
    _s("preferences.onsite", [r"\bon[- ]?site\b", r"\bin[- ]office\b", r"\bin person\b"], kinds=CHOICE),
    _s("preferences.start_date", [r"\b(available |earliest |desired |expected )?start date\b", r"\bwhen (can|could|would) you start\b", r"\bearliest .*start\b", r"\bavailable to start\b", r"\bavailability\b"],
       [r"start ?date", r"available ?(from|date)"], kinds=DATEY + ("textarea",)),
    _s("preferences.referral_source", [r"\bhow did you (hear|find|learn)\b", r"\breferral source\b", r"\bwhere did you (hear|find)\b", r"\bsource\b.*\bapplication\b", r"\bwho referred you\b"],
       [r"referral", r"hear ?about"], kinds=TEXTY + ("radio_group",)),
    _s("preferences.desired_salary", [r"\b(desired|expected|target|minimum) (salary|compensation|pay|base)\b", r"\bsalary (expectations?|requirements?|range)\b", r"\bcompensation expectations?\b", r"\bpay expectations?\b"],
       [r"salary", r"compensation"], deny=[r"\bcurrent\b", r"\bprevious\b", r"\blast\b"], kinds=TEXTY),
    _s("preferences.security_clearance", [r"\bsecurity clearance\b", r"\bclearance\b"], kinds=CHOICE + ("textarea",)),
    _s("preferences.background_check", [r"\bbackground (check|screen|investigation)\b"], kinds=CHOICE),
    # --- sensitive (EEO) --------------------------------------------------
    _s("sensitive.gender", [r"\bgender( identity)?\b", r"^sex$", r"\bwhat is your sex\b"], [r"^gender$"], sensitive=True, cat="sensitive", kinds=CHOICE),
    _s("sensitive.hispanic_latino", [r"\bhispanic\b", r"\blatin[oax]\b"], sensitive=True, cat="sensitive", kinds=CHOICE),
    _s("sensitive.race", [r"\brace\b", r"\bracial\b"], [r"^race$"], sensitive=True, cat="sensitive", kinds=CHOICE),
    _s("sensitive.ethnicity", [r"\bethnic(ity)?\b"], sensitive=True, cat="sensitive", kinds=CHOICE),
    _s("sensitive.disability_status", [r"\bdisabilit(y|ies)\b"], sensitive=True, cat="sensitive", kinds=CHOICE),
    _s("sensitive.veteran_status", [r"\bveteran\b", r"\bmilitary (status|service)\b"], sensitive=True, cat="sensitive", kinds=CHOICE),
    _s("sensitive.medical_accommodation", [r"\baccommodat(e|ion|ions)\b"], sensitive=True, cat="sensitive", kinds=CHOICE + ("textarea",)),
    _s("sensitive.other", [r"\bsexual orientation\b", r"\btransgender\b", r"\breligio(n|us)\b", r"\bmarital status\b", r"\bdate of birth\b", r"\bbirth ?date\b", r"\bage\b group", r"\bsocial security\b", r"\bssn\b", r"\bnational id\b"],
       sensitive=True, cat="sensitive"),
    # --- resume-derived: work experience ---------------------------------
    _s("experience.title", [r"\b(job )?title\b", r"\bposition( title)?\b", r"\brole\b"], [r"title", r"position"], section="experience", resume=True, cat="resume", kinds=TEXTY),
    _s("experience.company", [r"\bcompany( name)?\b", r"\bemployer\b", r"\borgani[sz]ation\b"], [r"company", r"employer", r"^org"], section="experience", resume=True, cat="resume", kinds=TEXTY),
    _s("experience.location", [r"\blocation\b", r"\bcity\b"], [r"location"], section="experience", resume=True, cat="resume", kinds=TEXTY),
    _s("experience.start_date", [r"\bstart( date)?\b", r"^from\b", r"\bdate from\b"], [r"start", r"from"], section="experience", resume=True, cat="resume", kinds=DATEY),
    _s("experience.end_date", [r"\bend( date)?\b", r"^to$", r"\bdate to\b"], [r"end", r"^to$"], section="experience", resume=True, cat="resume", kinds=DATEY),
    _s("experience.current", [r"\bcurrently (work|employed)\b", r"\bi currently\b", r"\bpresent\b", r"\bcurrent (job|position|role)\b"], [r"current"], section="experience", resume=True, cat="resume", kinds=("checkbox", "radio_group", "select", "custom_select", "unknown")),
    _s("experience.description", [r"\bdescription\b", r"\bresponsibilities\b", r"\bduties\b", r"\bsummary\b", r"\bachievements\b"], [r"description", r"responsib"], section="experience", resume=True, cat="resume", kinds=("textarea", "text", "unknown")),
    # education
    _s("education.school", [r"\b(school|university|college|institution)( name)?\b"], [r"school", r"university", r"institution"], section="education", resume=True, cat="resume", kinds=TEXTY),
    _s("education.degree", [r"\bdegree\b", r"\bqualification\b", r"\blevel of education\b"], [r"degree"], section="education", resume=True, cat="resume", kinds=TEXTY),
    _s("education.field_of_study", [r"\bfield of study\b", r"\bmajor\b", r"\bdiscipline\b", r"\barea of study\b", r"\bsubject\b"], [r"major", r"discipline", r"field"], section="education", resume=True, cat="resume", kinds=TEXTY),
    _s("education.start_date", [r"\bstart( date)?\b", r"^from\b"], [r"start", r"from"], section="education", resume=True, cat="resume", kinds=DATEY),
    _s("education.graduation_date", [r"\bgraduat", r"\bend( date)?\b", r"\bcompletion\b", r"^to$", r"\byear\b"], [r"graduat", r"end", r"^to$"], section="education", resume=True, cat="resume", kinds=DATEY),
    # certifications
    _s("certification.name", [r"\bcertification( name)?\b", r"\bcertificate( name)?\b", r"^name$", r"\blicense( name)?\b"], [r"cert", r"name"], section="certification", resume=True, cat="resume", kinds=TEXTY),
    _s("certification.number", [r"\b(certificate|certification|credential|license) (id|number|no)\b", r"\bcredential\b"], [r"number", r"credential"], section="certification", resume=True, cat="resume", kinds=TEXTY),
    _s("certification.issued_date", [r"\b(issue|issued|obtained|date earned|date)\b"], [r"issue"], section="certification", resume=True, cat="resume", kinds=DATEY),
    _s("certification.expiration_date", [r"\bexpir", r"\bvalid (through|until)\b"], [r"expir"], section="certification", resume=True, cat="resume", kinds=DATEY),
    # languages
    _s("language.language", [r"^language$", r"\blanguage\b"], [r"language"], section="language", resume=True, cat="resume", kinds=TEXTY),
    _s("language.proficiency", [r"\bproficiency\b", r"\blevel\b", r"\bfluen", r"\bspeak", r"\bread", r"\bwrit", r"\bcomprehension\b"], [r"proficien", r"level", r"fluen"], section="language", resume=True, cat="resume", kinds=TEXTY),
    # --- derived from resume (not in a section) --------------------------
    _s("calc.current_company", [r"\bcurrent (company|employer)\b", r"\bmost recent (company|employer)\b", r"\bpresent (company|employer)\b"], [r"^org$", r"current ?(company|employer)"], resume=True, cat="calc", kinds=TEXTY),
    _s("calc.current_title", [r"\bcurrent (job )?(title|position|role)\b", r"\bmost recent (job )?title\b"], [r"current ?title"], resume=True, cat="calc", kinds=TEXTY),
    _s("calc.years_experience", [r"\b(total )?years of (professional |work |relevant )?experience\b", r"\bhow many years of (professional |work |relevant )?experience\b", r"\btotal experience\b"], resume=True, cat="calc", kinds=TEXTY + ("number",),
       deny=[r"\b(with|in|using|of) (?!professional|work|relevant)\w"]),
    _s("calc.highest_degree", [r"\bhighest (level of )?(education|degree)\b"], resume=True, cat="calc", kinds=TEXTY + ("radio_group",)),
    # --- files, legal, security ------------------------------------------
    _s("resume.file", [r"\b(resume|r[ée]sum[ée]|cv|curriculum vitae)\b"], [r"resume", r"^cv$"], cat="file", kinds=("file",)),
    _s("other.cover_letter", [r"\bcover letter\b"], [r"cover"], cat="file", kinds=("file", "textarea")),
    _s("security.password", [r"\bpassword\b", r"\bpasscode\b"], [r"password"], types=("password",), cat="security", kinds=("password", "text", "unknown")),
    _s("security.captcha", [r"\bcaptcha\b", r"\brecaptcha\b", r"\bnot a robot\b", r"\bverify you are human\b"], cat="security", kinds=("captcha", "checkbox", "unknown")),
    _s("legal.signature", [r"\b(electronic |e-?)?signature\b", r"\btype your (full )?name to (sign|certify)\b"], [r"signature"], cat="legal"),
    _s("legal.consent", [r"\bi (hereby )?(agree|accept|acknowledge|consent|certify|declare|attest|understand|confirm that)\b", r"\bprivacy (policy|notice|statement)\b", r"\bterms (and|&) conditions\b", r"\bterms of (use|service)\b",
       r"\bconsent\b", r"\bgdpr\b", r"\bdata processing\b", r"\bcertif(y|ication) (that|the)\b", r"\bto the best of my knowledge\b", r"\baccuracy\b.*\b(information|statements?)\b", r"\bby (checking|submitting|clicking)\b"], cat="legal", kinds=("checkbox", "checkbox_group", "radio_group", "unknown")),
]

BY_KEY = {s.key: s for s in SPECS}

SENSITIVE_KEY_TO_FIELD = {
    "sensitive.gender": SensitiveField.GENDER,
    "sensitive.race": SensitiveField.RACE,
    "sensitive.ethnicity": SensitiveField.ETHNICITY,
    "sensitive.hispanic_latino": SensitiveField.HISPANIC_LATINO,
    "sensitive.disability_status": SensitiveField.DISABILITY_STATUS,
    "sensitive.veteran_status": SensitiveField.VETERAN_STATUS,
    "sensitive.medical_accommodation": SensitiveField.MEDICAL_ACCOMMODATION,
}

_compiled: dict[str, dict[str, list[re.Pattern[str]]]] = {}


def patterns(spec: Spec) -> dict[str, list[re.Pattern[str]]]:
    if spec.key not in _compiled:
        _compiled[spec.key] = {
            "label": [re.compile(p) for p in spec.label],
            "attr": [re.compile(p) for p in spec.attr],
            "deny": [re.compile(p) for p in spec.deny],
        }
    return _compiled[spec.key]


def normalize(text: str | None) -> str:
    """Lowercase words: splits camelCase, snake_case, brackets and punctuation."""
    if not text:
        return ""
    t = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    t = re.sub(r"[^A-Za-z0-9&,]+", " ", t).lower()
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class Taxonomy:
    specs: list[Spec] = field(default_factory=lambda: SPECS)
