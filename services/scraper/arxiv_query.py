from datetime import datetime

from config import CS_CATEGORIES


def build_all_cs_query() -> str:
    cat_queries = [f"cat:{cat}" for cat in CS_CATEGORIES]
    return "+OR+".join(cat_queries)


def build_search_query(
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> str:
    base = f"({build_all_cs_query()})"
    if date_from and date_to:
        start = date_from.strftime("%Y%m%d")
        end = date_to.strftime("%Y%m%d")
        return f"{base}+AND+submittedDate:[{start}+TO+{end}]"
    return base
