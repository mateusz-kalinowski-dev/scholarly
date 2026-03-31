import { Router, Request, Response } from "express";
import { getDriver } from "../services/neo4j";

const router = Router();

/**
 * GET /api/graph/papers
 * Returns graph nodes and edges for visualisation.
 */
router.get("/papers", async (_req: Request, res: Response) => {
  const session = getDriver().session();
  try {
    const result = await session.run(
      `MATCH (p:Paper)
       OPTIONAL MATCH (p)-[r]->(related)
       RETURN p, r, related LIMIT 200`,
    );

    const nodesMap = new Map<string, object>();
    const edges: Array<{ source: string; target: string; type: string }> = [];

    for (const record of result.records) {
      const paper = record.get("p");
      if (paper)
        nodesMap.set(paper.elementId, {
          id: paper.elementId,
          ...paper.properties,
          label: "Paper",
        });

      const related = record.get("related");
      const rel = record.get("r");
      if (related && rel) {
        const label = related.labels?.[0] ?? "Node";
        nodesMap.set(related.elementId, {
          id: related.elementId,
          ...related.properties,
          label,
        });
        edges.push({
          source: paper.elementId,
          target: related.elementId,
          type: rel.type,
        });
      }
    }

    res.json({ nodes: Array.from(nodesMap.values()), edges });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "Failed to fetch graph data" });
  } finally {
    await session.close();
  }
});

export default router;

/* 🕸️ Moduł Grafowy (Neo4j)
Te endpointy zasilą bibliotekę na frontendzie (np. react-force-graph), zwracając dane w formacie Węzłów (Nodes) i Krawędzi (Edges/Links).

GET /api/graph/paper/:id

Cel: Zwraca "pajęczynę" powiązań dla konkretnej pracy.

Zwraca: Kto ją napisał, jakiego ma promotora, do jakich tagów/tematów jest przypięta i jakie inne prace mają te same tagi.

GET /api/graph/author/:name

Cel: Zwraca graf danego autora.

Zwraca: Wszystkie prace, które napisał, z jakimi innymi autorami współpracował (tzw. co-authorship graph) oraz z jaką katedrą jest powiązany.

GET /api/graph/explore

Cel: Globalny widok (opcjonalny, ale robi świetne wrażenie). Zwraca największe klastry w Twojej bazie (np. najpopularniejsze tagi i powiązanych z nimi autorów).

🔍 Moduł Wyszukiwania
GET /api/search?q=query

Cel: Uniwersalna wyszukiwarka (szuka po tytułach prac w Postgresie lub po węzłach w Neo4j). */
