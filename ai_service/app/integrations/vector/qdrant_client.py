from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient as RawQdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from ai_service.app.core.config import settings


class QdrantVectorClient:
    def __init__(self, host: str = "localhost", port: int = 6333) -> None:
        try:
            url = settings.qdrant_url if settings.qdrant_url else f"http://{host}:{port}"
            self.client = RawQdrantClient(url=url)
        except Exception:
            self.client = None

    # Vector store initialization creating collection if it does not exist.
    def init_collection(self, collection_name: str = "jobs", vector_size: int = 384) -> None:
        if self.client:
            try:
                collections = self.client.get_collections().collections
                exists = any(c.name == collection_name for c in collections)
                if not exists:
                    self.client.create_collection(
                        collection_name=collection_name,
                        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                    )
            except Exception:
                pass

    # Method to upsert text embeddings into Qdrant collection.
    def upsert_job_vector(self, collection_name: str, job_id: str, vector: List[float], payload: Dict[str, Any]) -> None:
        if self.client:
            try:
                point = PointStruct(id=job_id, vector=vector, payload=payload)
                self.client.upsert(collection_name=collection_name, points=[point])
            except Exception:
                pass
