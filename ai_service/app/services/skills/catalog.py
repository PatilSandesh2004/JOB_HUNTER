"""Canonical skill catalogue shared by resume parsing, job normalisation and matching.

Each skill has a canonical name, the regex alternatives that count as a mention, and a domain. Both sides of
a match use this vocabulary, which is what makes skill-overlap scores meaningful. Domains tell what kind of
work a posting is about when its title is generic ("Software Engineer" whose description is all LLMs and RAG).

Aliases are case-insensitive unless wrapped in `cs(...)`: words that are also ordinary English ("React to
incidents", "excel at", "Go to market", "Rust") only count in their technical spelling and context.
"""

import re
from dataclasses import dataclass
from functools import lru_cache


def cs(pattern: str) -> str:
    """A case-sensitive alias."""
    return f"(?-i:{pattern})"


# domain -> {canonical name: aliases}
CATALOG: dict[str, dict[str, tuple[str, ...]]] = {
    "language": {
        "Python": (r"python",),
        "Java": (r"java(?!\s*script)",),
        "JavaScript": (r"javascript", r"ecmascript", cs(r"JS") + r"(?=\s*[,/)]|\s+and\b)"),
        "TypeScript": (r"typescript",),
        "Go": (
            r"golang",
            cs(r"Go")
            + r"(?=\s*(?:lang\b|[,/)]|\s+(?:developers?|engineers?|programming|services|microservices|and)\b))",
        ),
        "Rust": (cs(r"Rust"),),
        "C++": (r"c\+\+", r"cpp"),
        "C#": (r"c#", r"\.net(?:\s*core)?", r"dotnet", r"asp\.net"),
        "C": (r"embedded c", cs(r"C") + r"(?=\s*(?:/\s*C\+\+|,\s*C\+\+|\s+programming\b))"),
        "Ruby": (cs(r"Ruby"),),
        "PHP": (r"php",),
        "Kotlin": (r"kotlin",),
        "Swift": (cs(r"Swift(?:UI)?"),),
        "Objective-C": (r"objective-?c",),
        "Scala": (cs(r"Scala"),),
        "Elixir": (r"elixir",),
        "Dart": (cs(r"Dart"),),
        "R": (cs(r"R") + r"(?=\s*(?:[,/);]|\.(?:\s|$)|$|\s+(?:programming|language|studio)\b))", r"rstudio"),
        "MATLAB": (r"matlab",),
        "SQL": (r"sql",),
        "Bash": (r"bash", r"shell scripting", r"shell scripts?"),
        "Solidity": (r"solidity",),
    },
    "backend": {
        "Node.js": (r"node(?:\.js|js)", cs(r"Node") + r"(?=\s*[,/)])"),
        "Express": (r"express(?:\.js|js)",),
        "NestJS": (r"nest\.?js",),
        "Django": (r"django",),
        "Flask": (r"flask",),
        "FastAPI": (r"fastapi",),
        "Spring": (
            cs(r"Spring") + r"(?:\s*boot|\s+framework|\s+mvc)?(?!\s+(?:\d{4}|semester|term|break|internship)\b)",
        ),
        "Ruby on Rails": (r"ruby on rails", cs(r"Rails")),
        "Laravel": (r"laravel",),
        "GraphQL": (r"graphql",),
        "gRPC": (r"grpc",),
        "REST APIs": (r"restful(?: apis?| services)?", r"rest ?apis?", r"rest(?:ful)? web services"),
        "Microservices": (r"micro-?services?",),
        "Distributed Systems": (r"distributed systems?",),
        "System Design": (r"system design", r"systems design"),
        "Event-Driven Architecture": (r"event[- ]driven",),
        "Message Queues": (r"message (?:queues?|brokers?)", r"pub/?sub", r"amazon sqs", r"\bsqs\b"),
        "Kafka": (r"kafka",),
        "RabbitMQ": (r"rabbitmq",),
        "Celery": (r"celery",),
        "WebSockets": (r"web ?sockets?",),
        "Asyncio": (r"asyncio", r"async(?:hronous)? programming", r"async/await"),
        "OAuth": (r"oauth2?", r"openid connect", r"\boidc\b"),
        "Caching": (r"caching",),
    },
    "databases": {
        "PostgreSQL": (r"postgres(?:ql)?",),
        "MySQL": (r"mysql",),
        "SQL Server": (r"sql server", r"mssql", r"t-sql"),
        "Oracle Database": (r"oracle (?:db|database)", r"pl/sql"),
        "SQLite": (r"sqlite",),
        "MongoDB": (r"mongo(?:db)?",),
        "Redis": (r"redis",),
        "Cassandra": (r"cassandra",),
        "DynamoDB": (r"dynamo ?db",),
        "Elasticsearch": (r"elastic ?search", r"opensearch"),
        "Neo4j": (r"neo4j",),
        "NoSQL": (r"nosql",),
    },
    "frontend": {
        "React": (
            cs(r"React(?:\.js|JS)?") + r"(?!\s+(?:native|to|quickly|fast|promptly|swiftly|calmly|appropriately)\b)",
            r"reactjs",
            r"react\.js",
        ),
        "Next.js": (r"next\.?js",),
        "Vue": (r"vue(?:\.js|js)?", r"nuxt(?:\.js)?"),
        "Angular": (r"angular(?:js)?",),
        "Svelte": (r"svelte(?:kit)?",),
        "Redux": (r"redux",),
        "HTML": (r"html5?",),
        "CSS": (r"css3?", r"\bsass\b", r"\bscss\b"),
        "Tailwind CSS": (r"tailwind(?:\s*css)?",),
        "Bootstrap": (cs(r"Bootstrap"),),
        "Webpack": (r"webpack", r"\bvite\b"),
        "jQuery": (r"jquery",),
        "Three.js": (r"three\.js",),
        "D3.js": (r"d3\.js", cs(r"D3") + r"(?=\s*[,/)])"),
        "Accessibility": (r"accessibility", r"\ba11y\b", r"wcag"),
        "Storybook": (r"storybook",),
    },
    "mobile": {
        "Android": (r"android",),
        "iOS": (cs(r"iOS"),),
        "Flutter": (r"flutter",),
        "React Native": (r"react native",),
        "Jetpack Compose": (r"jetpack compose",),
        "Xamarin": (r"xamarin",),
    },
    "ai": {
        "Machine Learning": (r"machine learning", cs(r"ML") + r"(?![-/]?ops)"),
        "Deep Learning": (r"deep learning", r"neural networks?"),
        "NLP": (r"nlp", r"natural language processing", r"natural language understanding"),
        "Computer Vision": (r"computer vision", r"image recognition", r"object detection"),
        "LLMs": (r"llms?", r"large language models?", r"generative ai", r"gen ?ai", r"foundation models?"),
        "RAG": (cs(r"RAG") + r"(?!\s+(?:status|rating|reporting)\b)", r"retrieval[- ]augmented(?: generation)?"),
        "AI Agents": (
            r"agentic(?: ai| workflows?| systems?)?",
            r"ai agents?",
            r"llm agents?",
            r"multi-agent",
            r"autonomous agents?",
        ),
        "Prompt Engineering": (r"prompt engineering", r"prompt design", r"prompting techniques"),
        "Fine-tuning": (r"fine[- ]?tuning", r"\blora\b", r"\bqlora\b", r"\bpeft\b", r"\brlhf\b"),
        "LLM Evaluation": (r"llm eval(?:uation)?s?", r"model evaluation", cs(r"evals")),
        "Embeddings": (r"embeddings", r"embedding models?", r"semantic search", r"vector search"),
        "Vector Databases": (
            r"vector (?:db|database|store)s?",
            r"qdrant",
            r"pinecone",
            r"weaviate",
            r"pgvector",
            r"milvus",
            r"\bfaiss\b",
            r"chromadb",
        ),
        "MCP": (cs(r"MCP"), r"model context protocol"),
        "Function Calling": (r"function[- ]calling", r"tool[- ]calling", r"tool use"),
        "PyTorch": (r"pytorch", cs(r"Torch")),
        "TensorFlow": (r"tensorflow", r"\bkeras\b"),
        "JAX": (cs(r"JAX"),),
        "scikit-learn": (r"scikit-?learn", r"sklearn"),
        "XGBoost": (r"xgboost", r"lightgbm", r"catboost"),
        "Hugging Face": (r"hugging ?face", cs(r"Transformers"), r"sentence[- ]transformers"),
        "LangChain": (r"langchain",),
        "LangGraph": (r"langgraph",),
        "LlamaIndex": (r"llama ?index",),
        "CrewAI": (r"crew ?ai", r"autogen"),
        "OpenAI API": (r"openai(?: api)?", r"gpt-4o?", r"chatgpt"),
        "Anthropic Claude": (r"anthropic", cs(r"Claude") + r"(?=\s*(?:api|models?|sonnet|opus|haiku|code|[,/)]))"),
        "Ollama": (r"ollama", r"\bvllm\b", r"llama\.cpp"),
        "MLOps": (r"ml-?ops", r"mlflow", r"kubeflow", r"model (?:deployment|serving)"),
        "SageMaker": (r"sagemaker",),
        "Vertex AI": (r"vertex ai",),
        "CUDA": (r"cuda",),
        "OpenCV": (r"opencv",),
        "Reinforcement Learning": (r"reinforcement learning",),
        "Recommender Systems": (r"recommend(?:er|ation) (?:systems?|engines?)",),
        "Time Series": (r"time[- ]series",),
        "Statistics": (r"statistics", r"statistical (?:modeling|modelling|analysis)", r"hypothesis testing"),
        "Data Science": (r"data science",),
        "Pandas": (r"pandas",),
        "NumPy": (r"numpy",),
        "Jupyter": (r"jupyter",),
    },
    "data_eng": {
        "Spark": (cs(r"(?:Apache )?Spark"), r"pyspark"),
        "Hadoop": (r"hadoop", r"\bhdfs\b"),
        "Hive": (cs(r"Hive"),),
        "Airflow": (r"airflow",),
        "dbt": (r"dbt",),
        "Snowflake": (cs(r"Snowflake"),),
        "BigQuery": (r"bigquery", r"big query"),
        "Redshift": (r"redshift",),
        "Databricks": (r"databricks",),
        "Flink": (r"flink",),
        "ETL": (r"etl", r"elt pipelines?", r"data pipelines?"),
        "Data Warehousing": (r"data ?warehous(?:e|es|ing)", r"data lakes?", r"lakehouse"),
        "Data Modeling": (r"data model(?:l)?ing", r"dimensional model(?:l)?ing"),
    },
    "analytics": {
        "Excel": (cs(r"(?:MS |Microsoft )?Excel"), r"spreadsheets?"),
        "Power BI": (r"power ?bi",),
        "Tableau": (r"tableau",),
        "Looker": (cs(r"Looker"),),
        "Google Analytics": (r"google analytics", r"\bga4\b"),
        "A/B Testing": (r"a/b test(?:s|ing)?", r"multivariate test(?:s|ing)"),
        "SAS": (cs(r"SAS"),),
        "SPSS": (r"spss",),
        "Data Visualization": (r"data visuali[sz]ation", r"dashboards?"),
    },
    "cloud_devops": {
        "AWS": (r"aws", r"amazon web services", r"\bec2\b", r"\bs3\b", r"aws lambda"),
        "GCP": (r"gcp", r"google cloud"),
        "Azure": (r"azure",),
        "Docker": (r"docker", r"containeri[sz]ation"),
        "Kubernetes": (r"kubernetes", r"k8s", r"\beks\b", r"\bgke\b", r"\baks\b"),
        "Helm": (cs(r"Helm"),),
        "Terraform": (r"terraform", r"infrastructure as code", r"\biac\b"),
        "Ansible": (r"ansible",),
        "CloudFormation": (r"cloudformation",),
        "CI/CD": (
            r"ci/cd",
            r"ci\s*/\s*cd",
            r"continuous (?:integration|delivery|deployment)",
            r"github actions",
            r"jenkins",
            r"gitlab ci",
            r"circleci",
            r"argo ?cd",
        ),
        "Prometheus": (r"prometheus",),
        "Grafana": (r"grafana",),
        "Datadog": (r"datadog",),
        "Observability": (r"observability", r"opentelemetry", cs(r"ELK"), r"monitoring and alerting"),
        "Linux": (r"linux", r"unix"),
        "Nginx": (r"nginx",),
        "Serverless": (r"serverless", r"cloud functions"),
        "Networking": (r"tcp/ip", r"computer networks?", r"networking protocols?", r"\bdns\b"),
        "OpenShift": (r"openshift",),
    },
    "security": {
        "Application Security": (r"application security", r"appsec", r"owasp", r"secure coding"),
        "Penetration Testing": (r"penetration testing", r"pen[- ]?test(?:ing)?", r"burp suite"),
        "SIEM": (cs(r"SIEM"), r"splunk"),
        "IAM": (cs(r"IAM"), r"identity and access management"),
        "Cryptography": (r"cryptography", r"encryption"),
        "Compliance": (r"soc ?2", r"iso ?27001", r"pci[- ]dss"),
    },
    "qa": {
        "Selenium": (r"selenium",),
        "Cypress": (r"cypress",),
        "Playwright": (r"playwright",),
        "Pytest": (r"pytest",),
        "JUnit": (r"junit", r"testng"),
        "Jest": (cs(r"Jest"),),
        "Appium": (r"appium",),
        "Postman": (r"postman",),
        "JMeter": (r"jmeter", r"load testing", r"performance testing"),
        "Test Automation": (r"test automation", r"automated testing", r"automation testing"),
        "Manual Testing": (r"manual testing",),
    },
    "design": {
        "Figma": (r"figma",),
        "Sketch": (cs(r"Sketch"),),
        "Adobe XD": (r"adobe xd",),
        "Photoshop": (r"photoshop",),
        "Illustrator": (cs(r"Illustrator"),),
        "UX Research": (r"ux research", r"user research", r"usability testing"),
        "Wireframing": (r"wireframes?", r"wireframing", r"prototyping"),
    },
    "product": {
        "Product Management": (r"product management", r"product roadmaps?", r"roadmapping"),
        "Agile": (r"agile", r"scrum", r"kanban"),
        "Jira": (r"jira",),
        "Confluence": (r"confluence",),
        "Stakeholder Management": (r"stakeholder management",),
    },
    "business": {
        "Salesforce": (r"salesforce",),
        "HubSpot": (r"hubspot",),
        "SAP": (cs(r"SAP"),),
        "SEO": (cs(r"SEO"), r"search engine optimi[sz]ation"),
        "CRM": (cs(r"CRM"),),
    },
    "general": {
        "Git": (r"git(?!hub|lab)", r"version control"),
        "GitHub": (r"github(?! actions)",),
        "Unit Testing": (r"unit test(?:s|ing)?", r"\btdd\b", r"test[- ]driven"),
        "Data Structures & Algorithms": (r"data structures", r"algorithms", r"\bdsa\b"),
        "Object-Oriented Programming": (r"object[- ]oriented", r"\boop\b", r"\booad\b"),
        "Design Patterns": (r"design patterns",),
        "Web Scraping": (r"web scraping", r"beautifulsoup", r"scrapy"),
    },
}

SPECIALTY_DOMAINS: dict[str, tuple[str, ...]] = {
    # Which skill domains indicate which kind of engineering role.
    "ai": ("ai",),
    "backend": ("backend", "databases"),
    "frontend": ("frontend",),
    "mobile": ("mobile",),
    "devops": ("cloud_devops",),
    "data_eng": ("data_eng",),
    "security": ("security",),
    "qa": ("qa",),
    "analytics": ("analytics",),
}


@dataclass(frozen=True)
class SkillMention:
    name: str
    start: int


def _bounded(aliases: tuple[str, ...]) -> str:
    return r"(?<![\w+#.])(?:" + "|".join(aliases) + r")(?![\w+#])"


@lru_cache(maxsize=1)
def _skills() -> dict[str, tuple[str, tuple[str, ...]]]:
    """canonical name -> (domain, aliases)"""
    return {name: (domain, aliases) for domain, skills in CATALOG.items() for name, aliases in skills.items()}


@lru_cache(maxsize=512)
def _single(name: str) -> re.Pattern[str]:
    return re.compile(_bounded(_skills()[name][1]), re.IGNORECASE)


_LEADING_WORD = re.compile(r"[a-z0-9]+")


def _trigger(alias: str) -> str | None:
    """A lowercase word every match of `alias` must contain, or None when there is no reliable one.

    Only the alias's leading literal letters count (a trailing optional letter, as in "llms?", is dropped),
    so checking `trigger in text.lower()` before running the regex never skips a real mention.
    """
    plain = alias.removeprefix("(?-i:").removeprefix(r"\b").lower()
    match = _LEADING_WORD.match(plain)
    if not match:
        return None
    word = match.group()
    if plain[match.end() : match.end() + 1] in ("?", "*", "{"):
        word = word[:-1]
    return word if len(word) >= 2 else None


@lru_cache(maxsize=1)
def _triggers() -> dict[str, tuple[str, ...] | None]:
    """name -> trigger words (None: always run the regex, some alias has no reliable trigger)."""
    result: dict[str, tuple[str, ...] | None] = {}
    for name, (_, aliases) in _skills().items():
        words = [_trigger(a) for a in aliases]
        result[name] = None if None in words else tuple(dict.fromkeys(words))
    return result


def find_skills(text: str) -> list[SkillMention]:
    """Every catalogue skill mention in `text`, in order of appearance."""
    if not text:
        return []
    lowered = text.lower()
    mentions = []
    for name, words in _triggers().items():
        if words is not None and not any(w in lowered for w in words):
            continue  # cheap substring pre-check: most skills are absent from any one posting
        mentions += [SkillMention(name, m.start()) for m in _single(name).finditer(text)]
    return sorted(mentions, key=lambda m: m.start)


def extract_skills(text: str) -> list[str]:
    """Canonical skills mentioned in `text`, in catalogue order."""
    found = {m.name for m in find_skills(text)}
    return [name for name in _skills() if name in found]


def skill_domain(name: str) -> str | None:
    entry = _skills().get(name)
    return entry[0] if entry else None


def in_catalog(name: str) -> bool:
    return name in _skills()


def canonicalize(skill: str) -> str:
    """Map a free-text skill (e.g. 'postgres', 'K8s') to its canonical name, or return it trimmed."""
    cleaned = skill.strip()
    if cleaned in _skills():
        return cleaned
    for name in _skills():
        if _single(name).fullmatch(cleaned):
            return name
    return cleaned


def normalize_skill_list(skills: list[str]) -> list[str]:
    return list(dict.fromkeys(canonicalize(s) for s in skills if s and s.strip()))


def skill_variants(skill: str) -> list[str]:
    """Ways a free-text skill may be written in a posting: 'Asynchronous Programming (asyncio)' ->
    ['Asynchronous Programming (asyncio)', 'Asynchronous Programming', 'asyncio']."""
    text = skill.strip()
    variants = [text]
    inner = re.findall(r"\(([^)]{2,40})\)", text)
    outer = re.sub(r"\s*\([^)]*\)", "", text).strip()
    variants += [outer, *inner]
    return [v for v in dict.fromkeys(variants) if len(v) >= 2]


@lru_cache(maxsize=2048)
def skill_pattern(skill: str) -> re.Pattern[str]:
    """Regex for mentions of `skill`: its catalogue aliases, or its literal variants for skills not in the catalogue."""
    name = canonicalize(skill)
    if name in _skills():
        return _single(name)
    alternatives = "|".join(re.escape(v) for v in skill_variants(name))
    return re.compile(r"(?<![\w+#.])(?:" + alternatives + r")(?![\w+#])", re.IGNORECASE)


def specialties_from_skills(skills: list[str], minimum: int = 2, share: float = 0.25) -> set[str]:
    """Kinds of engineering a skill list points at: {'ai'} for [LLMs, RAG, PyTorch, Python].

    A kind counts when at least `minimum` skills, and at least `share` of all the skills, belong to it, so a
    posting that mentions "LLMs" once among twelve other skills is not taken for an AI role."""
    counts: dict[str, int] = {}
    for skill in skills:
        domain = skill_domain(skill)
        for specialty, domains in SPECIALTY_DOMAINS.items():
            if domain in domains:
                counts[specialty] = counts.get(specialty, 0) + 1
    total = len(set(skills)) or 1
    return {specialty for specialty, n in counts.items() if n >= minimum and n / total >= share}
