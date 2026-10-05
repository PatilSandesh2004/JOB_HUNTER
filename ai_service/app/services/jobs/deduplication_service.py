from typing import List
from rapidfuzz import fuzz
from ai_service.app.schemas.job import NormalizedJob


class JobDeduplicationService:
    
    # Deduplication method using exact application URL filtering followed by title & company fuzzy matching.
    def deduplicate(self, jobs: List[NormalizedJob], similarity_threshold: float = 85.0) -> List[NormalizedJob]:
        unique_jobs: List[NormalizedJob] = []
        seen_urls = set()
        
        for job in jobs:
            # 1. Exact match on URL
            if job.application_url in seen_urls:
                continue
                
            # 2. Fuzzy match on title + company combination
            is_duplicate = False
            for target in unique_jobs:
                combo1 = f"{job.title} {job.company}".lower()
                combo2 = f"{target.title} {target.company}".lower()
                
                score = fuzz.token_sort_ratio(combo1, combo2)
                if score >= similarity_threshold:
                    is_duplicate = True
                    break
                    
            if not is_duplicate:
                seen_urls.add(job.application_url)
                unique_jobs.append(job)
                
        return unique_jobs
