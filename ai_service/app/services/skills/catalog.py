"""Canonical skill catalogue shared by resume parsing, job normalisation and matching.

Each canonical name maps to the regex alternatives that should count as that skill. Keeping both
sides on the same vocabulary is what makes skill overlap scores meaningful.
"""

import re
from functools import lru_cache

SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    # Languages
    "Python": (r"python",),
    "Go": (r"golang", r"go(?=\s*(?:lang|developer|engineer|,|/|\)))"),
    "Java": (r"java(?!\s*script)",),
    "JavaScript": (r"javascript", r"\bjs\b"),
    "TypeScript": (r"typescript",),
    "C++": (r"c\+\+", r"cpp"),
    "C#": (r"c#", r"\.net", r"dotnet"),
    "Rust": (r"rust",),
    "Ruby": (r"ruby",),
    "PHP": (r"php",),
    "Kotlin": (r"kotlin",),
    "Swift": (r"swift",),
    "Scala": (r"scala",),
    "SQL": (r"sql",),
    "Bash": (r"bash", r"shell scripting"),
    # Web / backend
    "React": (r"react(?:\.js|js)?",),
    "Next.js": (r"next\.?js",),
    "Vue": (r"vue(?:\.js)?",),
    "Angular": (r"angular",),
    "Node.js": (r"node(?:\.js|js)?",),
    "FastAPI": (r"fastapi",),
    "Django": (r"django",),
    "Flask": (r"flask",),
    "Spring": (r"spring(?: boot)?",),
    "GraphQL": (r"graphql",),
    "REST APIs": (r"restful(?: apis?)?", r"rest ?apis?"),
    "gRPC": (r"grpc",),
    "Microservices": (r"micro-?services?",),
    # Data stores
    "PostgreSQL": (r"postgres(?:ql)?",),
    "MySQL": (r"mysql",),
    "MongoDB": (r"mongo(?:db)?",),
    "Redis": (r"redis",),
    "Elasticsearch": (r"elastic ?search",),
    "Kafka": (r"kafka",),
    "RabbitMQ": (r"rabbitmq",),
    "Snowflake": (r"snowflake",),
    "Spark": (r"(?:apache )?spark", r"pyspark"),
    "Airflow": (r"airflow",),
    "dbt": (r"dbt",),
    # Cloud / infra
    "AWS": (r"aws", r"amazon web services"),
    "GCP": (r"gcp", r"google cloud"),
    "Azure": (r"azure",),
    "Docker": (r"docker",),
    "Kubernetes": (r"kubernetes", r"k8s"),
    "Terraform": (r"terraform",),
    "CI/CD": (r"ci/cd", r"github actions", r"jenkins", r"gitlab ci"),
    "Linux": (r"linux",),
    "Git": (r"git(?!hub|lab)",),
    # AI / ML
    "Machine Learning": (r"machine learning", r"\bml\b"),
    "Deep Learning": (r"deep learning",),
    "NLP": (r"nlp", r"natural language processing"),
    "Computer Vision": (r"computer vision",),
    "LLMs": (r"llms?", r"large language models?", r"generative ai", r"gen ?ai"),
    "RAG": (r"rag", r"retrieval[- ]augmented"),
    "PyTorch": (r"pytorch", r"torch"),
    "TensorFlow": (r"tensorflow",),
    "scikit-learn": (r"scikit-?learn", r"sklearn"),
    "Pandas": (r"pandas",),
    "NumPy": (r"numpy",),
    "LangChain": (r"langchain",),
    "LangGraph": (r"langgraph",),
    "Hugging Face": (r"hugging ?face", r"transformers"),
    "Vector Databases": (r"vector (?:db|database|store)s?", r"qdrant", r"pinecone", r"weaviate", r"pgvector"),
    "MLOps": (r"mlops",),
    # Testing / automation
    "Playwright": (r"playwright",),
    "Selenium": (r"selenium",),
    "Pytest": (r"pytest",),
}


@lru_cache(maxsize=1)
def _compiled() -> dict[str, re.Pattern[str]]:
    return {
        name: re.compile(r"(?<![\w+#.])(?:" + "|".join(aliases) + r")(?![\w+#])", re.IGNORECASE)
        for name, aliases in SKILL_ALIASES.items()
    }


def extract_skills(text: str) -> list[str]:
    """Return canonical skills mentioned in `text`, in catalogue order."""
    if not text:
        return []
    return [name for name, pattern in _compiled().items() if pattern.search(text)]


def canonicalize(skill: str) -> str:
    """Map a free-text skill (e.g. 'postgres', 'K8s') to its canonical name, or return it trimmed."""
    cleaned = skill.strip()
    for name, pattern in _compiled().items():
        if pattern.fullmatch(cleaned):
            return name
    return cleaned


def normalize_skill_list(skills: list[str]) -> list[str]:
    return list(dict.fromkeys(canonicalize(s) for s in skills if s and s.strip()))


def skill_pattern(skill: str) -> re.Pattern[str]:
    """Regex for mentions of `skill`: its catalogue aliases, or the literal text for skills not in the catalogue."""
    name = canonicalize(skill)
    return _compiled().get(name) or re.compile(r"(?<![\w+#.])" + re.escape(name) + r"(?![\w+#])", re.IGNORECASE)
