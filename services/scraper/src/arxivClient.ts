import axios from 'axios';
import { config } from './config';

export interface ArxivEntry {
  id: string;
  title: string;
  summary: string;
  authors: string[];
  pdfUrl: string;
  published: string;
}

/**
 * Parses the Atom XML returned by the arXiv API into structured entries.
 */
function parseAtomXml(xml: string): ArxivEntry[] {
  const entries: ArxivEntry[] = [];

  const entryRegex = /<entry>([\s\S]*?)<\/entry>/g;
  let match: RegExpExecArray | null;

  while ((match = entryRegex.exec(xml)) !== null) {
    const block = match[1];

    const id = (/<id>https?:\/\/arxiv\.org\/abs\/([^<]+)<\/id>/.exec(block) ?? [])[1] ?? '';
    const title = (/<title[^>]*>([\s\S]*?)<\/title>/.exec(block) ?? [])[1]?.trim() ?? '';
    const summary = (/<summary[^>]*>([\s\S]*?)<\/summary>/.exec(block) ?? [])[1]?.trim() ?? '';
    const published = (/<published>([\s\S]*?)<\/published>/.exec(block) ?? [])[1]?.trim() ?? '';

    const authorRegex = /<author>[\s\S]*?<name>([\s\S]*?)<\/name>[\s\S]*?<\/author>/g;
    const authors: string[] = [];
    let authorMatch: RegExpExecArray | null;
    while ((authorMatch = authorRegex.exec(block)) !== null) {
      authors.push(authorMatch[1].trim());
    }

    const pdfUrl = `https://arxiv.org/pdf/${id}.pdf`;

    if (id) {
      entries.push({ id, title, summary, authors, pdfUrl, published });
    }
  }

  return entries;
}

/**
 * Fetches new paper entries from the arXiv API.
 */
export async function fetchArxivEntries(): Promise<ArxivEntry[]> {
  const params = new URLSearchParams({
    search_query: config.arxiv.query,
    max_results: String(config.arxiv.maxResults),
    sortBy: 'submittedDate',
    sortOrder: 'descending',
  });

  const response = await axios.get<string>(`${config.arxiv.baseUrl}?${params.toString()}`, {
    responseType: 'text',
  });

  return parseAtomXml(response.data);
}
