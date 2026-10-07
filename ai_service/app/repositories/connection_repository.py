import csv
import io
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ai_service.app.models.connection import ConnectionModel
from ai_service.app.models.candidate import CandidateModel

class ConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def import_csv(self, candidate_id: str, file_contents: bytes) -> int:
        """Parses LinkedIn Connections CSV and stores them. Returns count."""
        # Read file
        text = file_contents.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        
        # Clear existing connections for candidate
        # Using a simple approach for now, normally we'd delete in batches or use delete() statement
        stmt = select(ConnectionModel).where(ConnectionModel.candidate_id == candidate_id)
        existing = await self.session.scalars(stmt)
        for c in existing:
            await self.session.delete(c)
            
        count = 0
        for row in reader:
            first_name = row.get("First Name", "").strip()
            last_name = row.get("Last Name", "").strip()
            company = row.get("Company", "").strip()
            position = row.get("Position", "").strip()
            connected_on = row.get("Connected On", "").strip()
            
            if not first_name or not company:
                continue
                
            conn = ConnectionModel(
                candidate_id=candidate_id,
                first_name=first_name,
                last_name=last_name,
                company=company,
                position=position,
                connected_on=connected_on
            )
            self.session.add(conn)
            count += 1
            
        await self.session.commit()
        return count

    async def find_by_company(self, candidate_id: str, company: str) -> list[ConnectionModel]:
        """Finds connections at a specific company (case insensitive)."""
        stmt = select(ConnectionModel).where(
            ConnectionModel.candidate_id == candidate_id,
            ConnectionModel.company.ilike(f"%{company}%")
        )
        return list(await self.session.scalars(stmt))
