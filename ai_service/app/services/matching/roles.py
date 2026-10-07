"""Understand job titles: what kind of job (function), what kind of engineering (specialty), which language.

"Sales Engineer, AI" contains "AI" and "Engineer" but is a sales job; "Backend Engineer (Python)" never says
"Python Developer" but is one. Comparing these parts, instead of counting shared words, is what keeps
unrelated jobs out and finds related ones under other names.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from rapidfuzz import fuzz

from ai_service.app.services.skills.catalog import specialties_from_skills

# ---- functions: first matching rule wins, so specific roles come before the generic "engineer" ----------
_FUNCTION_RULES: list[tuple[str, str]] = [
    ("annotation", r"annotat\w*|data label\w*|label(?:l)?ers?|\braters?\b|ai (?:code )?trainer|code trainer|ai tutor|"
                   r"training data|trainer for ai|"
                   r"(?:ai|llm|model) evaluator|search quality"),
    ("recruiting", r"recruit\w*|talent acquisition|sourcer|\bhr\b|human resources|people (?:partner|operations)|hrbp"),
    ("sales", r"\bsales\b|account executive|account manager|business development|\bbdr\b|\bsdr\b|pre-?sales|"
              r"solutions? (?:engineer|architect|consultant)|field engineer|customer engineer|partnerships?"),
    ("marketing", r"marketing|growth (?:manager|lead|hacker)|\bseo\b|\bsem\b|\bbrand\b|social media|demand gen|"
                  r"community manager|public relations|\bpr\b"),
    ("content", r"writer|copywriter|\beditor\b|content|journalist|documentation specialist"),
    ("design", r"designer|\bux\b(?! engineer)|user experience|graphic|illustrat\w*|visual design|creative director|"
               r"ui/ux|ux/ui|design lead"),
    ("product", r"product (?:manager|owner|lead|management|director|head)|\bapm\b|program manager|project manager|"
                r"scrum master|delivery manager|\btpm\b"),
    ("support", r"support|help ?desk|service desk|customer (?:service|success|care)|technician|\bnoc\b|it helpdesk"),
    ("qa", r"\bqa\b|quality (?:assurance|engineer|analyst)|\btest(?:er|ing)?\b|\bsdet\b|automation test"),
    ("devrel", r"developer (?:advocate|relations|evangelist)|devrel|evangelist"),
    ("data_science", r"data scien\w*|applied scientist|(?:ml|machine learning|ai) scientist|statistician|"
                     r"quantitative (?:analyst|researcher)|\bquant\b"),
    ("research", r"research(?!\s+engineer)(?:er| scientist| fellow| associate)?|\bphd\b|postdoc"),
    ("business_analysis", r"business (?:systems? )?analyst|business systems? (?:engineer|administrator|specialist)|"
                          r"functional analyst|requirements analyst|\bba\b"),
    ("analytics", r"data analyst|\bbi\b|business intelligence|analytics(?!\s+engineer)|\banalyst\b|reporting"),
    ("it_ops", r"system(?:s)? administrator|sysadmin|it administrator|network (?:engineer|administrator)|"
               r"\bit (?:engineer|specialist|manager|officer)"),
    ("finance", r"account(?:ant|ing)|finance|financial|auditor|\btax\b|payroll|controller|bookkeep\w*|treasury"),
    ("legal", r"legal|counsel|lawyer|attorney|paralegal|compliance officer"),
    ("education", r"instructor|teacher|tutor|faculty|professor|lecturer|teaching assistant|trainer|curriculum"),
    ("operations", r"operations (?:manager|associate|executive|analyst)|\bops (?:manager|associate)\b|coordinator|"
                   r"administrative|office manager|executive assistant|\bassistant\b(?! professor)"),
    ("management", r"engineering manager|head of|director|\bvp\b|vice president|\bcto\b|chief|\bmanager\b"),
    ("engineering", r"engineer\w*|developer|programmer|\bswe\b|\bsde\b|architect|devops|\bsre\b|coder|"
                    r"technologist|full ?-?stack|back ?-?end|front ?-?end|\bmts\b|member of technical staff"),
]  # fmt: skip
_FUNCTIONS = [(name, re.compile(pattern, re.I)) for name, pattern in _FUNCTION_RULES]

# How acceptable a job of one function is for a target of another (missing pairs: 0). Same function: 1.
_COMPATIBLE: dict[frozenset[str], float] = {
    frozenset({"engineering", "qa"}): 0.35,
    frozenset({"engineering", "data_science"}): 0.35,
    frozenset({"engineering", "research"}): 0.3,
    frozenset({"engineering", "it_ops"}): 0.35,
    frozenset({"engineering", "devrel"}): 0.25,
    frozenset({"engineering", "management"}): 0.3,
    frozenset({"engineering", "sales"}): 0.0,
    frozenset({"engineering", "support"}): 0.1,
    frozenset({"engineering", "analytics"}): 0.2,
    frozenset({"data_science", "research"}): 0.7,
    frozenset({"data_science", "analytics"}): 0.5,
    frozenset({"analytics", "product"}): 0.2,
    frozenset({"analytics", "business_analysis"}): 0.5,
    frozenset({"product", "business_analysis"}): 0.4,
    frozenset({"product", "management"}): 0.4,
    frozenset({"support", "it_ops"}): 0.5,
    frozenset({"qa", "support"}): 0.2,
}
# An AI engineer may fit an AI data-science or research role; the pair is only worth this much with AI in both.
_SPECIALTY_BRIDGES: dict[frozenset[str], tuple[str, float]] = {
    frozenset({"engineering", "data_science"}): ("ai", 0.65),
    frozenset({"engineering", "research"}): ("ai", 0.5),
}

# ---- specialties ---------------------------------------------------------------------------------
_SPECIALTY_RULES: list[tuple[str, str]] = [
    ("ai", r"machine learning|\bml\b|artificial intelligence|\bai\b|gen ?ai|generative|\bllms?\b|\bnlp\b|"
           r"natural language|deep learning|computer vision|\bcv\b|applied ai|agentic|\bagents?\b|prompt|ml ?ops|"
           r"\brag\b|conversational|speech|recommend\w*|ai/ml|ml/ai|\bmle\b"),
    ("frontend", r"front ?-?end|\bui\b|\breact\b|angular|\bvue\b|web developer|javascript developer"),
    ("backend", r"back ?-?end|server[- ]side|\bapi\b|\bapis\b"),
    ("mobile", r"mobile|android|\bios\b|flutter|react native"),
    ("devops", r"dev ?ops|site reliability|\bsre\b|infrastructure|\binfra\b|cloud|kubernetes|reliability|"
               r"platform engineer"),
    ("data_eng", r"data engineer\w*|\betl\b|data platform|big data|data pipelines?|analytics engineer|"
                 r"data warehouse"),
    ("security", r"security|appsec|devsecops|penetration|pentest|\bsoc\b|cyber"),
    ("embedded", r"embedded|firmware|hardware|fpga|asic|vlsi|robotics"),
    ("blockchain", r"blockchain|web3|solidity|smart contract|\bcrypto\b"),
    ("game", r"\bgame|unity|unreal"),
    ("enterprise", r"salesforce|\bsap\b|servicenow|dynamics 365|oracle (?:apps|ebs|fusion)|\berp\b|\bcrm\b"),
]  # fmt: skip
_SPECIALTIES = [(name, re.compile(pattern, re.I)) for name, pattern in _SPECIALTY_RULES]
_FULLSTACK = re.compile(r"full ?-?stack", re.I)
# Specialties close enough to share credit: a backend role is partly a platform role, and so on.
_ADJACENT: dict[frozenset[str], float] = {
    frozenset({"backend", "devops"}): 0.35,
    frozenset({"backend", "data_eng"}): 0.4,
    frozenset({"ai", "data_eng"}): 0.3,
    frozenset({"ai", "backend"}): 0.15,
    frozenset({"frontend", "mobile"}): 0.3,
    frozenset({"devops", "security"}): 0.3,
}

# ---- languages -----------------------------------------------------------------------------------
_LANGUAGE_RULES: list[tuple[str, str]] = [
    ("python", r"python|django|flask|fastapi"),
    ("java", r"\bjava\b(?!\s*script)|spring|\bj2ee\b|jvm"),
    ("javascript", r"javascript|typescript|node(?:\.?js)?|\bjs\b|\bts\b|mern|mean stack"),
    ("go", r"golang|\bgo\b"),
    ("rust", r"\brust\b"),
    ("cpp", r"c\+\+|\bcpp\b"),
    ("csharp", r"c#|\.net|dotnet|asp\.net"),
    ("ruby", r"\bruby\b|rails"),
    ("php", r"\bphp\b|laravel"),
    ("scala", r"\bscala\b"),
    ("kotlin", r"kotlin"),
    ("swift", r"\bswift\b"),
]  # fmt: skip
_LANGUAGES = [(name, re.compile(pattern, re.I)) for name, pattern in _LANGUAGE_RULES]
_LANGUAGE_FAMILIES = [{"java", "kotlin", "scala"}, {"javascript"}, {"swift"}, {"cpp"}, {"csharp"}]
_LANGUAGE_SKILLS = {
    "python": "Python", "java": "Java", "javascript": "JavaScript", "go": "Go", "rust": "Rust", "cpp": "C++",
    "csharp": "C#", "ruby": "Ruby", "php": "PHP", "scala": "Scala", "kotlin": "Kotlin", "swift": "Swift",
}  # fmt: skip

# Words that carry no meaning about which role it is once function/specialty/language are known.
_FILLER = re.compile(
    r"\b(senior|sr|junior|jr|staff|principal|lead|head|chief|i{1,3}|iv|v|level|l\d|mid|entry|associate|intern(?:ship)?|"
    r"trainee|fresher|graduate|remote|hybrid|on-?site|contract|contractor|freelance|part[- ]time|full[- ]time|"
    r"temporary|permanent|f|m|d|w|x|of|the|and|for|with|in|at|to|a|an|or|team|role|position|opening|job|"
    r"engineer\w*|developer|programmer|specialist|expert|professional|consultant|software|technical|tech|it)\b",
    re.I,
)
_TOKEN = re.compile(r"[a-z][a-z0-9+#.]*")


@dataclass(frozen=True)
class TitleProfile:
    function: str
    specialties: frozenset[str] = field(default_factory=frozenset)
    languages: frozenset[str] = field(default_factory=frozenset)
    keywords: frozenset[str] = field(default_factory=frozenset)  # remaining meaningful words, e.g. "payments"


@lru_cache(maxsize=4096)
def parse_title(title: str) -> TitleProfile:
    text = title.lower()
    function = next((name for name, pattern in _FUNCTIONS if pattern.search(text)), "other")
    specialties = {name for name, pattern in _SPECIALTIES if pattern.search(text)}
    if _FULLSTACK.search(text):
        specialties |= {"frontend", "backend"}
    if function in ("data_science", "research") and not specialties:
        specialties.add("ai")  # data scientists and researchers do modelling by default
    languages = {name for name, pattern in _LANGUAGES if pattern.search(text)}
    stripped = text
    for pattern in [p for _, p in _FUNCTIONS] + [p for _, p in _SPECIALTIES] + [p for _, p in _LANGUAGES]:
        stripped = pattern.sub(" ", stripped)
    keywords = {t for t in _TOKEN.findall(_FILLER.sub(" ", stripped)) if len(t) > 2}
    return TitleProfile(function, frozenset(specialties), frozenset(languages), frozenset(keywords))


def _function_fit(target: TitleProfile, job: TitleProfile) -> float:
    if target.function == job.function:
        return 1.0
    if "other" in (target.function, job.function):
        return 0.45  # a title we cannot classify ("Associate", "Member of Staff"): let the details decide
    pair = frozenset({target.function, job.function})
    bridge = _SPECIALTY_BRIDGES.get(pair)
    if bridge and bridge[0] in target.specialties and bridge[0] in job.specialties:
        return bridge[1]
    return _COMPATIBLE.get(pair, 0.0)


def _specialty_fit(target: TitleProfile, job: TitleProfile, inferred: frozenset[str]) -> float:
    """1.0 same kind of work, ~0.35 generic title with no evidence, ~0.1 clearly different kind."""
    if not target.specialties:
        return 1.0 if not job.specialties else 0.9  # "Software Engineer" covers backend, AI, ...
    wanted = target.specialties
    if job.specialties:
        best = len(wanted & job.specialties) / len(wanted)
        for w in wanted - job.specialties:
            best = max(best, max((_ADJACENT.get(frozenset({w, j}), 0.0) for j in job.specialties), default=0.0))
        if best < 1.0 and wanted <= inferred:
            best = max(best, 0.5)  # "Backend Engineer" whose description is mostly LLM work
        return best
    if wanted & inferred:
        return 0.75 if wanted <= inferred else 0.6  # generic title, but the description is about this work
    return 0.3  # generic title ("Software Engineer II"), nothing known about the work


def _language_fit(target: TitleProfile, job: TitleProfile, job_skills: frozenset[str]) -> float:
    if not target.languages:
        return 1.0
    if target.languages & job.languages:
        return 1.0
    wanted_skills = {_LANGUAGE_SKILLS[lang] for lang in target.languages}
    if wanted_skills & job_skills:
        return 0.9  # the description asks for it
    if job.languages:
        for family in _LANGUAGE_FAMILIES:
            if target.languages & family and job.languages & family:
                return 0.7
        return 0.1  # "Java Developer" for a Python developer
    if job_skills & set(_LANGUAGE_SKILLS.values()):
        return 0.2  # the description asks for other languages only
    return 0.5


def _keyword_fit(target: TitleProfile, job: TitleProfile, title: str) -> float:
    if not target.keywords:
        return 1.0
    text = title.lower()
    return sum(1 for k in target.keywords if k in job.keywords or k in text) / len(target.keywords)


def role_similarity(target: str, title: str, job_skills: list[str] | tuple[str, ...] | None = None) -> float:
    """0-100: how well a job title matches a target role. `job_skills` (from the description) lets a generic
    title like "Software Engineer" count as an AI role when the posting is all about LLMs."""
    wanted, have = parse_title(target), parse_title(title)
    skills = frozenset(job_skills or ())
    inferred = frozenset(specialties_from_skills(list(skills)))
    function = _function_fit(wanted, have)
    fuzzy = max(0.0, min(1.0, (fuzz.token_sort_ratio(target.lower(), title.lower()) - 40) / 50))
    if function == 0.0:
        return round(10 * fuzzy, 1)
    # A language-led target ("Python Developer") is mostly about the language; otherwise the kind of work leads.
    if wanted.languages and not wanted.specialties:
        weights = (0.3, 0.6, 0.1)
    elif wanted.languages:
        weights = (0.55, 0.35, 0.1)
    else:
        weights = (0.7, 0.2, 0.1)
    core = (
        weights[0] * _specialty_fit(wanted, have, inferred)
        + weights[1] * _language_fit(wanted, have, skills)
        + weights[2] * _keyword_fit(wanted, have, title)
    )
    return round(min(100.0, 100 * function * core * 0.88 + 12 * fuzzy), 1)


def describe(title: str) -> str:
    """Short human description of a title's kind, for match explanations."""
    profile = parse_title(title)
    label = {
        "engineering": "engineering", "data_science": "data science", "research": "research",
        "analytics": "analytics", "business_analysis": "business analysis", "qa": "QA / testing",
        "it_ops": "IT operations", "devrel": "developer relations",
        "management": "management", "product": "product / project management", "design": "design",
        "sales": "sales", "marketing": "marketing", "content": "writing / content", "support": "support",
        "recruiting": "recruiting / HR", "annotation": "data annotation / AI training", "finance": "finance",
        "legal": "legal", "education": "teaching / training", "operations": "operations", "other": "other",
    }[profile.function]  # fmt: skip
    if profile.specialties and profile.function in ("engineering", "data_science", "research", "qa"):
        names = {"ai": "AI/ML", "data_eng": "data", "devops": "DevOps/cloud"}
        kinds = ", ".join(sorted(names.get(s, s) for s in profile.specialties))
        return f"{kinds} {label}"
    return label


# ---- related titles for searching ------------------------------------------------------------------
_RELATED_TITLES: dict[str, list[str]] = {
    "ai": ["AI Engineer", "Machine Learning Engineer", "LLM Engineer", "Generative AI Engineer", "Applied AI Engineer",
           "AI/ML Engineer", "NLP Engineer", "MLOps Engineer"],
    "backend": ["Backend Engineer", "Backend Developer", "Software Engineer (Backend)", "API Developer"],
    "frontend": ["Frontend Engineer", "Frontend Developer", "React Developer", "UI Engineer"],
    "fullstack": ["Full Stack Engineer", "Full Stack Developer"],
    "mobile": ["Mobile Engineer", "Android Developer", "iOS Developer", "Flutter Developer"],
    "devops": ["DevOps Engineer", "Site Reliability Engineer", "Platform Engineer", "Cloud Engineer"],
    "data_eng": ["Data Engineer", "Big Data Engineer", "Analytics Engineer", "ETL Developer"],
    "security": ["Security Engineer", "Application Security Engineer", "Cloud Security Engineer"],
    "data_science": ["Data Scientist", "Applied Scientist", "Machine Learning Scientist"],
    "analytics": ["Data Analyst", "BI Analyst", "Product Analyst", "Reporting Analyst"],
    "qa": ["QA Engineer", "SDET", "Test Automation Engineer"],
}  # fmt: skip
_LANGUAGE_TITLES = {
    "python": ["Python Developer", "Python Engineer", "Backend Engineer (Python)"],
    "java": ["Java Developer", "Java Backend Engineer", "Spring Boot Developer"],
    "javascript": ["JavaScript Developer", "Node.js Developer", "TypeScript Engineer"],
    "go": ["Golang Developer", "Go Backend Engineer"],
}


def related_titles(role: str, limit: int = 6) -> list[str]:
    """Other names the same job is posted under: "AI Engineer" -> "Machine Learning Engineer", "LLM Engineer"..."""
    profile = parse_title(role)
    pools: list[list[str]] = []
    if profile.function in ("data_science", "analytics", "qa"):
        pools.append(_RELATED_TITLES[profile.function])
    if {"frontend", "backend"} <= profile.specialties:
        pools.append(_RELATED_TITLES["fullstack"])
    pools += [_RELATED_TITLES[s] for s in sorted(profile.specialties) if s in _RELATED_TITLES]
    if not profile.specialties:
        pools += [_LANGUAGE_TITLES[lang] for lang in sorted(profile.languages) if lang in _LANGUAGE_TITLES]
    titles: list[str] = []
    for pool in pools:
        titles += [t for t in pool if t.lower() != role.lower()]
    return list(dict.fromkeys(titles))[:limit]
