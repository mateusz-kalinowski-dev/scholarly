import dotenv from 'dotenv';
dotenv.config();

export const config = {
  /** Cron schedule for the scraper (default: every hour) */
  cronSchedule: process.env.CRON_SCHEDULE ?? '0 * * * *',

  arxiv: {
    /** Max results per scrape run */
    maxResults: parseInt(process.env.ARXIV_MAX_RESULTS ?? '20', 10),
    /** Search query, e.g. "cat:cs.AI" or "ti:machine+learning" */
    query: process.env.ARXIV_QUERY ?? 'cat:cs.AI',
    baseUrl: 'https://export.arxiv.org/api/query',
  },

  minio: {
    endPoint: process.env.MINIO_ENDPOINT ?? 'localhost',
    port: parseInt(process.env.MINIO_PORT ?? '9000', 10),
    useSSL: process.env.MINIO_USE_SSL === 'true',
    accessKey: process.env.MINIO_ACCESS_KEY ?? 'minioadmin',
    secretKey: process.env.MINIO_SECRET_KEY ?? 'minioadmin',
    bucket: process.env.MINIO_BUCKET ?? 'scholarly-pdfs',
  },

  redis: {
    url: process.env.REDIS_URL ?? 'redis://localhost:6379',
    /** Redis list key used as the processing queue */
    queueKey: process.env.REDIS_QUEUE_KEY ?? 'processor:queue',
    statusKey: process.env.REDIS_STATUS_KEY ?? 'scraper:status',
  },
} as const;
