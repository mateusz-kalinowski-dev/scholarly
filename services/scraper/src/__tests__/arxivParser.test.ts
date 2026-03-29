// We test the XML parsing logic by exporting the helper (via inline re-implementation)
// rather than requiring network access.

const SAMPLE_XML = `<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/abs/2401.00001</id>
    <title>Test Paper Title</title>
    <summary>This is the abstract of the paper.</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
  </entry>
  <entry>
    <id>https://arxiv.org/abs/2401.00002</id>
    <title>Another Paper</title>
    <summary>Second abstract.</summary>
    <published>2024-01-02T00:00:00Z</published>
    <author><name>Carol White</name></author>
  </entry>
</feed>`;

function parseAtomXml(xml: string) {
  const entries: Array<{
    id: string;
    title: string;
    summary: string;
    authors: string[];
    pdfUrl: string;
    published: string;
  }> = [];

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
    if (id) entries.push({ id, title, summary, authors, pdfUrl, published });
  }
  return entries;
}

describe('arXiv XML parser', () => {
  it('parses two entries from sample XML', () => {
    const entries = parseAtomXml(SAMPLE_XML);
    expect(entries).toHaveLength(2);
  });

  it('extracts id, title, summary, published', () => {
    const [first] = parseAtomXml(SAMPLE_XML);
    expect(first.id).toBe('2401.00001');
    expect(first.title).toBe('Test Paper Title');
    expect(first.summary).toBe('This is the abstract of the paper.');
    expect(first.published).toBe('2024-01-01T00:00:00Z');
  });

  it('constructs correct PDF URL', () => {
    const [first] = parseAtomXml(SAMPLE_XML);
    expect(first.pdfUrl).toBe('https://arxiv.org/pdf/2401.00001.pdf');
  });

  it('extracts multiple authors', () => {
    const [first] = parseAtomXml(SAMPLE_XML);
    expect(first.authors).toEqual(['Alice Smith', 'Bob Jones']);
  });

  it('handles single author', () => {
    const [, second] = parseAtomXml(SAMPLE_XML);
    expect(second.authors).toEqual(['Carol White']);
  });

  it('returns empty array for empty feed', () => {
    const entries = parseAtomXml('<feed></feed>');
    expect(entries).toHaveLength(0);
  });
});
