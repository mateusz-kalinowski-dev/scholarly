"""SQL filters from query-router metadata (author, year, arxiv_id, category)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MetadataFilters:
    arxiv_id: str | None = None
    author: str | None = None
    year: int | None = None
    primary_category: str | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                self.arxiv_id,
                self.author,
                self.year is not None,
                self.primary_category,
            )
        )

    def sql_and(self, paper_alias: str = "p") -> tuple[str, list]:
        clauses: list[str] = []
        params: list = []
        if self.arxiv_id:
            clauses.append(f"{paper_alias}.arxiv_id = %s")
            params.append(self.arxiv_id.strip())
        if self.author:
            clauses.append(
                f"EXISTS (SELECT 1 FROM unnest({paper_alias}.authors) a "
                f"WHERE a ILIKE %s)"
            )
            params.append(f"%{self.author.strip()}%")
        if self.year is not None:
            clauses.append(
                f"EXTRACT(YEAR FROM {paper_alias}.published_at)::int = %s"
            )
            params.append(int(self.year))
        if self.primary_category:
            clauses.append(f"{paper_alias}.primary_category = %s")
            params.append(self.primary_category.strip())
        if not clauses:
            return "", []
        return " AND " + " AND ".join(clauses), params
