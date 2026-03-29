import { Router, Request, Response } from 'express';
import { redis } from '../services/redis';
import { minioClient } from '../services/minio';
import { config } from '../config';

const router = Router();

const SCRAPER_QUEUE_KEY = 'scraper:queue';
const SCRAPER_STATUS_KEY = 'scraper:status';

/**
 * GET /api/scraper/status
 * Returns the current scraper run status and queue length.
 */
router.get('/status', async (_req: Request, res: Response) => {
  try {
    const [status, queueLen] = await Promise.all([
      redis.get(SCRAPER_STATUS_KEY),
      redis.llen(SCRAPER_QUEUE_KEY),
    ]);
    res.json({ status: status ?? 'idle', queueLength: queueLen });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to fetch scraper status' });
  }
});

/**
 * GET /api/scraper/files
 * Lists PDF objects stored in MinIO.
 */
router.get('/files', async (_req: Request, res: Response) => {
  try {
    const objects: Array<{ name: string; size: number; lastModified: Date }> = [];
    await new Promise<void>((resolve, reject) => {
      const stream = minioClient.listObjectsV2(config.minio.bucket, '', true);
      stream.on('data', (obj) => {
        objects.push({
          name: obj.name ?? '',
          size: obj.size ?? 0,
          lastModified: obj.lastModified ?? new Date(0),
        });
      });
      stream.on('end', resolve);
      stream.on('error', reject);
    });
    res.json(objects);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to list files' });
  }
});

export default router;
