import cron from 'node-cron';
import { config } from './config';
import { fetchArxivEntries } from './arxivClient';
import { processBatch, redis } from './storage';

async function runScrape(): Promise<void> {
  console.log(`[scraper] Starting scrape run at ${new Date().toISOString()}`);
  try {
    const entries = await fetchArxivEntries();
    console.log(`[scraper] Fetched ${entries.length} entries from arXiv`);
    await processBatch(entries);
  } catch (err) {
    console.error('[scraper] Scrape run failed:', err);
  }
}

console.log(`[scraper] Scheduling with cron: "${config.cronSchedule}"`);
cron.schedule(config.cronSchedule, () => {
  runScrape().catch((err) => console.error('[scraper] Unhandled error:', err));
});

// Run once immediately on startup
runScrape().catch((err) => console.error('[scraper] Startup run failed:', err));

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('[scraper] SIGTERM received, shutting down...');
  await redis.quit();
  process.exit(0);
});
