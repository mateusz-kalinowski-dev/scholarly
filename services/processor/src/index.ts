import Redis from 'ioredis';
import * as Minio from 'minio';
// eslint-disable-next-line @typescript-eslint/no-require-imports
const pdfParse = require('pdf-parse') as (buf: Buffer) => Promise<{ text: string }>;

import { config } from './config';
import { summarise } from './llmClient';
import { savePaper, closeDriver } from './graphStore';

const redis = new Redis(config.redis.url);
const minioClient = new Minio.Client({
  endPoint: config.minio.endPoint,
  port: config.minio.port,
  useSSL: config.minio.useSSL,
  accessKey: config.minio.accessKey,
  secretKey: config.minio.secretKey,
});

interface QueueJob {
  objectName: string;
  arxivId: string;
  title: string;
  summary: string;
  authors: string[];
  published: string;
}

async function downloadPdf(objectName: string): Promise<Buffer> {
  const chunks: Buffer[] = [];
  const stream = await minioClient.getObject(config.minio.bucket, objectName);
  await new Promise<void>((resolve, reject) => {
    stream.on('data', (chunk: Buffer) => chunks.push(chunk));
    stream.on('end', resolve);
    stream.on('error', reject);
  });
  return Buffer.concat(chunks);
}

async function processJob(job: QueueJob): Promise<void> {
  console.log(`[processor] Processing: ${job.arxivId} – ${job.title}`);

  let text = job.summary; // fallback to arXiv abstract

  try {
    const pdfBuffer = await downloadPdf(job.objectName);
    const parsed = await pdfParse(pdfBuffer);
    // Use first 4000 chars to stay within token limits
    text = parsed.text.slice(0, 4000);
  } catch (err) {
    console.warn(`[processor] PDF parse failed for ${job.objectName}, using abstract:`, err);
  }

  const llmResult = await summarise({ text, title: job.title });

  await savePaper({
    objectName: job.objectName,
    arxivId: job.arxivId,
    title: job.title,
    summary: job.summary,
    authors: job.authors,
    published: job.published,
    llmSummary: llmResult.summary,
    keywords: llmResult.keywords,
  });

  console.log(`[processor] Saved to graph: ${job.arxivId}`);
}

async function runWorker(): Promise<void> {
  console.log('[processor] Worker started, waiting for jobs...');

  while (true) {
    try {
      // Blocking pop with timeout
      const result = await redis.blpop(config.redis.queueKey, config.redis.pollTimeout);
      if (!result) continue;

      const [, payload] = result;
      const job: QueueJob = JSON.parse(payload);
      await processJob(job);
    } catch (err) {
      console.error('[processor] Error processing job:', err);
      // Brief pause to avoid tight error loops
      await new Promise((r) => setTimeout(r, 2_000));
    }
  }
}

runWorker().catch((err) => {
  console.error('[processor] Fatal error:', err);
  process.exit(1);
});

process.on('SIGTERM', async () => {
  console.log('[processor] SIGTERM received, shutting down...');
  await redis.quit();
  await closeDriver();
  process.exit(0);
});
