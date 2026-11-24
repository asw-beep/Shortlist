"""Stage A extraction: what a posting says, read with rules alone (no LLM).

Every new or changed posting goes through here. The output decides whether the posting is
relevant to the batch at all (the gate in is_relevant), and whether Stage B, the LLM, has
anything to add (`confident`).
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from app.extract.taxonomy import SkillMatcher

RemoteScope = Literal["onsite", "hybrid", "remote_country", "remote_global", "unknown"]
RELEVANT_FAMILIES = ("software", "ml", "data")
REMOTE_SCOPES_ELIGIBLE = ("remote_country", "remote_global")
MAX_YEARS_RELEVANT = 3

# Canonical Indian city -> spellings seen in postings.
INDIAN_CITIES: dict[str, tuple[str, ...]] = {
    "Bengaluru": ("bengaluru", "bangalore", "blr"),
    "Mumbai": ("mumbai", "bombay", "navi mumbai"),
    "Delhi": ("new delhi", "delhi", "delhi ncr"),
    "Gurugram": ("gurugram", "gurgaon"),
    "Noida": ("noida", "greater noida"),
    "Hyderabad": ("hyderabad", "secunderabad"),
    "Chennai": ("chennai", "madras"),
    "Pune": ("pune",),
    "Kolkata": ("kolkata", "calcutta"),
    "Ahmedabad": ("ahmedabad",),
    "Kochi": ("kochi", "cochin"),
    "Thiruvananthapuram": ("thiruvananthapuram", "trivandrum"),
    "Jaipur": ("jaipur",),
    "Chandigarh": ("chandigarh", "mohali"),
    "Indore": ("indore",),
    "Coimbatore": ("coimbatore",),
    "Mysuru": ("mysuru", "mysore"),
    "Bhubaneswar": ("bhubaneswar",),
}
INDIA_WORDS = (
    "india",
    "karnataka",
    "maharashtra",
    "telangana",
    "tamil nadu",
    "haryana",
    "kerala",
    "uttar pradesh",
    "west bengal",
    "gujarat",
    "rajasthan",
    "andhra pradesh",
    "odisha",
    "punjab",
    "madhya pradesh",
)
# Enough of the rest of the world to tell "not India" from "unknown".
FOREIGN: dict[str, str] = {
    "united states": "US",
    "usa": "US",
    "us": "US",
    "san francisco": "US",
    "new york": "US",
    "seattle": "US",
    "austin": "US",
    "boston": "US",
    "chicago": "US",
    "los angeles": "US",
    "mountain view": "US",
    "palo alto": "US",
    "denver": "US",
    "atlanta": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "london": "GB",
    "canada": "CA",
    "toronto": "CA",
    "vancouver": "CA",
    "germany": "DE",
    "berlin": "DE",
    "munich": "DE",
    "ireland": "IE",
    "dublin": "IE",
    "singapore": "SG",
    "netherlands": "NL",
    "amsterdam": "NL",
    "france": "FR",
    "paris": "FR",
    "australia": "AU",
    "sydney": "AU",
    "japan": "JP",
    "tokyo": "JP",
    "brazil": "BR",
    "colombia": "CO",
    "argentina": "AR",
    "chile": "CL",
    "peru": "PE",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "switzerland": "CH",
    "austria": "AT",
    "belgium": "BE",
    "italy": "IT",
    "portugal": "PT",
    "czech republic": "CZ",
    "romania": "RO",
    "ukraine": "UA",
    "turkey": "TR",
    "south africa": "ZA",
    "nigeria": "NG",
    "kenya": "KE",
    "egypt": "EG",
    "saudi arabia": "SA",
    "south korea": "KR",
    "korea": "KR",
    "china": "CN",
    "hong kong": "HK",
    "taiwan": "TW",
    "vietnam": "VN",
    "indonesia": "ID",
    "malaysia": "MY",
    "thailand": "TH",
    "new zealand": "NZ",
    "latam": "XL",
    "mexico": "MX",
    "poland": "PL",
    "spain": "ES",
    "israel": "IL",
    "uae": "AE",
    "dubai": "AE",
    "philippines": "PH",
    "emea": "EU",
    "europe": "EU",
    "apac": "XA",
    "americas": "XU",
}
US_STATE = re.compile(r",\s*(?:[A-Z]{2})\s*$")


@dataclass(frozen=True)
class Location:
    country: str | None
    city: str | None
    remote_scope: RemoteScope


@dataclass(frozen=True)
class RuleFeatures:
    role_family: str
    seniority: str
    is_internship: bool
    is_new_grad: bool
    min_years: Decimal | None
    location: Location
    skills: set[str]
    confident: bool
    # Skills named in the title: precise, unlike description matches ("Go above and beyond").
    title_skills: set[str] = field(default_factory=set)


def _has(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text) is not None


def _india_city(text: str) -> str | None:
    for city, spellings in INDIAN_CITIES.items():
        if any(_has(text, s) for s in spellings):
            return city
    return None


def _country(part: str) -> str | None:
    lower = part.lower().strip()
    # "IN" counts as India only as a whole location part ("IN", "Remote, IN"), never mid-text.
    bare_code = re.fullmatch(r"(remote[\s,()–-]*)?in\)?", lower) is not None
    if _india_city(lower) or any(_has(lower, w) for w in INDIA_WORDS) or bare_code:
        return "IN"
    for word, code in FOREIGN.items():
        if _has(lower, word):
            return code
    if US_STATE.search(part):
        return "US"
    return None


def _title_country(title: str) -> str | None:
    """A country named as the last part of a title: "… - Sweden", "… (Remote, Brazil)".

    Only a part that is exactly a place counts, so "Software Engineer, US Payments" names none.
    """
    tail = re.split(r"\s[-–—|]\s", title)[-1]
    pieces = (
        re.sub(r"\bremote\b", " ", p, flags=re.I).strip(" .").lower()
        for p in re.split(r"[,()]", tail)
    )
    place = next((p for p in reversed(list(pieces)) if p), "")
    if place in FOREIGN:
        return FOREIGN[place]
    if place in INDIA_WORDS or any(place in spellings for spellings in INDIAN_CITIES.values()):
        return "IN"
    return None


def parse_location(raw: str, *, is_remote_flag: bool | None = None) -> Location:
    """Country, canonical Indian city and remote scope from a free-text location.

    Multi-location strings ("San Francisco; Bengaluru") prefer India: the question is
    whether this batch can take the job, not where most of the team sits.
    """
    parts = [p for p in re.split(r"[;|]|\s/\s", raw) if p.strip()]
    lower = raw.lower()
    remote = _has(lower, "remote") or bool(is_remote_flag)
    hybrid = _has(lower, "hybrid")
    countries = [c for c in (_country(p) for p in parts) if c]
    city = _india_city(lower)
    country = "IN" if (city or "IN" in countries) else (countries[0] if countries else None)
    if remote and not hybrid:
        scope: RemoteScope = "remote_country" if country else "remote_global"
    elif hybrid:
        scope = "hybrid"
    elif country or city:
        scope = "onsite"
    else:
        scope = "unknown"
    return Location(country, city if country == "IN" else None, scope)


_ML = re.compile(
    r"machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|\bnlp\b|"
    r"computer vision|\bllm|applied scientist|research scientist|gen ?ai|mlops",
    re.I,
)
_DATA = re.compile(
    r"data (engineer|scientist|analyst|platform)|analytics engineer|business intelligence|"
    r"\bbi (engineer|developer|analyst)|data science",
    re.I,
)
_SOFTWARE = re.compile(
    r"software|\bsde\b|\bswe\b|developer|engineer|programmer|devops|\bsre\b|full[ -]?stack|"
    r"back[ -]?end|front[ -]?end",
    re.I,
)
# "Engineer" in these titles means a customer-facing or non-software role.
_CUSTOMER_FACING = re.compile(
    r"customer success|\bsales\b|account (executive|manager)|\bsupport\b|recruit|marketing|"
    r"solutions (consultant|engineer)|implementation (engineer|consultant|specialist)",
    re.I,
)
_INTERN = re.compile(r"\bintern(ship)?\b|\bco-?op\b|apprentice|trainee", re.I)
_NEW_GRAD = re.compile(
    r"new grad|graduate|campus|fresher|university|early career|class of 20\d\d", re.I
)
_SENIOR = re.compile(
    r"\bsenior\b|\bsr\.?\b|\bstaff\b|principal|\blead\b|manager|head of|director|architect|"
    r"\b(iii|iv)\b|\bvp\b",
    re.I,
)
_MID = re.compile(r"\b(ii|2)\b|intermediate|\bmid\b", re.I)
_ENTRY = re.compile(
    r"junior|\bjr\.?\b|entry[ -]level|associate (software|engineer|developer|data)|"
    r"\b(sde|swe|engineer|developer)\s*(i|1)\b",
    re.I,
)
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b", re.I)


def _family(title: str) -> str:
    if _CUSTOMER_FACING.search(title):
        return "other"
    if _ML.search(title):
        return "ml"
    if _DATA.search(title):
        return "data"
    if _SOFTWARE.search(title):
        return "software"
    return "other"


def _seniority(title: str) -> str:
    if _INTERN.search(title):
        return "intern"
    if _NEW_GRAD.search(title):
        return "new_grad"
    if _SENIOR.search(title):
        return "senior"
    if _ENTRY.search(title):
        return "entry"
    if _MID.search(title):
        return "mid"
    return "unknown"


def _min_years(text: str) -> Decimal | None:
    """The smallest years figure tied to experience; else the smallest plausible one."""
    tied, loose = [], []
    for match in _YEARS.finditer(text):
        value = int(match.group(1))
        if value > 15:
            continue
        loose.append(value)
        if re.search(r"exp", text[match.end() : match.end() + 60], re.I):
            tied.append(value)
    pick = tied or loose
    return Decimal(min(pick)) if pick else None


def is_relevant(
    *,
    role_family: str,
    seniority: str,
    min_years: Decimal | float | None,
    country: str | None,
    remote_scope: str,
) -> bool:
    """The batch's gate: India or remote-for-India, a software/ML/data role, not senior."""
    in_reach = country == "IN" or (remote_scope in REMOTE_SCOPES_ELIGIBLE and country is None)
    return (
        in_reach
        and role_family in RELEVANT_FAMILIES
        and seniority != "senior"
        and (min_years is None or min_years <= MAX_YEARS_RELEVANT)
    )


def _with_title_country(location: Location, title: str) -> Location:
    """The location field wins; the title fills in a country it left out."""
    if location.country is not None:
        return location
    country = _title_country(title)
    if country is None:
        return location
    scope = location.remote_scope
    if scope == "remote_global":
        scope = "remote_country"
    elif scope == "unknown":
        scope = "onsite"
    return Location(country, None, scope)


def extract_rules(
    title: str,
    location_raw: str,
    description: str,
    matcher: SkillMatcher,
    *,
    is_remote_flag: bool | None = None,
) -> RuleFeatures:
    family, seniority = _family(title), _seniority(title)
    skills = matcher.match(f"{title}\n{description}")
    years = _min_years(description)
    confident = not (
        (family == "other" and skills)
        or (years is None and seniority not in ("intern", "new_grad"))
    )
    return RuleFeatures(
        role_family=family,
        seniority=seniority,
        is_internship=seniority == "intern",
        is_new_grad=seniority == "new_grad",
        min_years=years,
        location=_with_title_country(
            parse_location(location_raw, is_remote_flag=is_remote_flag), title
        ),
        skills=skills,
        confident=confident,
        title_skills=matcher.match(title),
    )
