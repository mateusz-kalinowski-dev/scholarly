import axios from 'axios';
import * as Minio from 'minio';
import Redis from 'ioredis';
import { config } from './config';
import { ArxivEntry } from './arxivClient';

const minioClient = new Minio.Client({
  endPoint: config.minio.endPoint,
  port: config.minio.port,
  useSSL: config.minio.useSSL,
  accessKey: config.minio.accessKey,
  secretKey: config.minio.secretKey,
});

const redis = new Redis(config.redis.url);

async function ensureBucket(): Promise<void> {
  const exists = await minioClient.bucketExists(config.minio.bucket);
  if (!exists) {
    await minioClient.makeBucket(config.minio.bucket);
    console.log(`Bucket "${config.minio.bucket}" created`);
  }
}

/**
 * Downloads a PDF from the given URL and uploads it to MinIO.
 * Returns the object name on success, or null if already stored.
 */
async function downloadAndStore(entry: ArxivEntry): Promise<string | null> {
  const objectName = `${entry.id.replace(/\//g, '_')}.pdf`;

  // Skip if already in the bucket
  try {
    await minioClient.statObject(config.minio.bucket, objectName);
    return null; // already exists
  } catch {
    // object does not exist – proceed
  }

  const response = await axios.get<Buffer>(entry.pdfUrl, {
    responseType: 'arraybuffer',
    timeout: 30_000,
  });

  const buffer = Buffer.from(response.data);

  await minioClient.putObject(
    config.minio.bucket,
    objectName,
    buffer,
    buffer.length,
    { 'Content-Type': 'application/pdf', 'x-arxiv-id': entry.id },
  );

  return objectName;
}

/**
 * Pushes a processing job onto the Redis queue.
 */
async function enqueue(entry: ArxivEntry, objectName: string): Promise<void> {
  const job = JSON.stringify({
    objectName,
    arxivId: entry.id,
    title: entry.title,
    summary: entry.summary,
    authors: entry.authors,
    published: entry.published,
    enqueuedAt: new Date().toISOString(),
  });
  await redis.rpush(config.redis.queueKey, job);
}

/**
 * Processes a batch of arXiv entries: downloads PDFs and enqueues jobs.
 */
export async function processBatch(entries: ArxivEntry[]): Promise<void> {
  await ensureBucket();
  await redis.set(config.redis.statusKey, 'running');

  let stored = 0;
  for (const entry of entries) {
    try {
      const objectName = await downloadAndStore(entry);
      if (objectName) {
        await enqueue(entry, objectName);
        stored++;
        console.log(`[scraper] Stored and enqueued: ${entry.id}`);
      } else {
        console.log(`[scraper] Already exists, skipping: ${entry.id}`);
      }
    } catch (err) {
      console.error(`[scraper] Failed to process entry ${entry.id}:`, err);
    }
  }

  console.log(`[scraper] Batch done. New files stored: ${stored}`);
  await redis.set(config.redis.statusKey, 'idle');
}

export { redis };
