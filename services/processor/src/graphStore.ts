import neo4j, { Driver } from 'neo4j-driver';
import { config } from './config';
import { v4 as uuidv4 } from 'uuid';

let driver: Driver | null = null;

function getDriver(): Driver {
  if (!driver) {
    driver = neo4j.driver(
      config.neo4j.uri,
      neo4j.auth.basic(config.neo4j.user, config.neo4j.password),
    );
  }
  return driver;
}

export async function closeDriver(): Promise<void> {
  if (driver) {
    await driver.close();
    driver = null;
  }
}

export interface PaperRecord {
  objectName: string;
  arxivId: string;
  title: string;
  summary: string;
  authors: string[];
  published: string;
  llmSummary: string;
  keywords: string[];
}

/**
 * Writes a paper node with author and topic relationships into Neo4j.
 *
 * Graph model:
 *   (Paper)-[:AUTHORED_BY]->(Author)
 *   (Paper)-[:HAS_TOPIC]->(Topic)
 */
export async function savePaper(record: PaperRecord): Promise<void> {
  const session = getDriver().session();
  try {
    const paperId = record.arxivId || uuidv4();

    await session.run(
      `MERGE (p:Paper {id: $id})
       SET p.title        = $title,
           p.arxivSummary = $arxivSummary,
           p.llmSummary   = $llmSummary,
           p.published    = $published,
           p.objectName   = $objectName,
           p.createdAt    = coalesce(p.createdAt, $now)`,
      {
        id: paperId,
        title: record.title,
        arxivSummary: record.summary,
        llmSummary: record.llmSummary,
        published: record.published,
        objectName: record.objectName,
        now: new Date().toISOString(),
      },
    );

    for (const author of record.authors) {
      await session.run(
        `MERGE (a:Author {name: $name})
         WITH a
         MATCH (p:Paper {id: $paperId})
         MERGE (p)-[:AUTHORED_BY]->(a)`,
        { name: author, paperId },
      );
    }

    for (const keyword of record.keywords) {
      await session.run(
        `MERGE (t:Topic {name: $name})
         WITH t
         MATCH (p:Paper {id: $paperId})
         MERGE (p)-[:HAS_TOPIC]->(t)`,
        { name: keyword.toLowerCase(), paperId },
      );
    }
  } finally {
    await session.close();
  }
}
