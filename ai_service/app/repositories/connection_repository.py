import csv
import io

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.models.connection import ConnectionModel


class ConnectionCsvError(ValueError):
    pass


def parse_connections_csv(data: bytes) -> list[dict[str, str]]:
    """Rows of LinkedIn's Connections.csv export (Settings → Data privacy → Get a copy of your data).

    The export starts with a few "Notes:" lines before the real header, so reading starts at the header.
    """
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if "first name" in line.lower() and "company" in line.lower()), None
    )
    if start is None:
        raise ConnectionCsvError("This is not LinkedIn's Connections.csv (no 'First Name' and 'Company' columns)")
    rows = []
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        clean = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if clean.get("first name") and clean.get("company"):
            rows.append(clean)
    return rows


class ConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def import_csv(self, candidate_id: str, data: bytes) -> int:
        """Replace the stored connections with those in the CSV. Returns how many were imported."""
        rows = parse_connections_csv(data)
        await self.session.execute(delete(ConnectionModel).where(ConnectionModel.candidate_id == candidate_id))
        self.session.add_all(
            ConnectionModel(
                candidate_id=candidate_id,
                first_name=row["first name"][:100],
                last_name=row.get("last name", "")[:100],
                company=row["company"][:200],
                position=row.get("position", "")[:200],
                connected_on=row.get("connected on", "")[:50] or None,
            )
            for row in rows
        )
        await self.session.commit()
        return len(rows)

    async def count(self, candidate_id: str) -> int:
        stmt = select(func.count()).select_from(ConnectionModel).where(ConnectionModel.candidate_id == candidate_id)
        return await self.session.scalar(stmt) or 0

    async def find_by_company(self, candidate_id: str, company: str) -> list[ConnectionModel]:
        """Connections whose company contains `company` (case-insensitive)."""
        stmt = select(ConnectionModel).where(
            ConnectionModel.candidate_id == candidate_id, ConnectionModel.company.ilike(f"%{company.strip()}%")
        )
        return list(await self.session.scalars(stmt.limit(50)))
