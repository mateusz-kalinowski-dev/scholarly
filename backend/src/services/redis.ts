import Redis from 'ioredis';
import { config } from '../config';

export const redis = new Redis(config.redis.url);

redis.on('error', (err) => {
  console.error('Redis error:', err);
});
