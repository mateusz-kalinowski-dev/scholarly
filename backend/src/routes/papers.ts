import { Router, Request, Response } from 'express';
import { getDriver } from '../services/neo4j';

const router = Router();

/**
 * GET /api/papers
 * Returns a list of all paper nodes from the graph database.
 */
router.get('/', async (_req: Request, res: Response) => {
  const session = getDriver().session();
  try {
    const result = await session.run(
      'MATCH (p:Paper) RETURN p ORDER BY p.createdAt DESC LIMIT 50',
    );
    const papers = result.records.map((r) => r.get('p').properties);
    res.json(papers);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to fetch papers' });
  } finally {
    await session.close();
  }
});

/**
 * GET /api/papers/:id
 * Returns a single paper with its related nodes (citations, topics, authors).
 */
router.get('/:id', async (req: Request, res: Response) => {
  const session = getDriver().session();
  try {
    const result = await session.run(
      `MATCH (p:Paper {id: $id})
       OPTIONAL MATCH (p)-[:AUTHORED_BY]->(a:Author)
       OPTIONAL MATCH (p)-[:HAS_TOPIC]->(t:Topic)
       OPTIONAL MATCH (p)-[:CITES]->(c:Paper)
       RETURN p,
              collect(DISTINCT a) AS authors,
              collect(DISTINCT t) AS topics,
              collect(DISTINCT c) AS citations`,
      { id: req.params.id },
    );
    if (result.records.length === 0) {
      res.status(404).json({ error: 'Paper not found' });
      return;
    }
    const record = result.records[0];
    const paper = record.get('p').properties;
    paper.authors = record.get('authors').map((n: { properties: unknown }) => n.properties);
    paper.topics = record.get('topics').map((n: { properties: unknown }) => n.properties);
    paper.citations = record.get('citations').map((n: { properties: unknown }) => n.properties);
    res.json(paper);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to fetch paper' });
  } finally {
    await session.close();
  }
});

export default router;
