import dotenv from 'dotenv';
dotenv.config();

export const config = {
  port: parseInt(process.env.PORT ?? '3000', 10),
  neo4j: {
    uri: process.env.NEO4J_URI ?? 'bolt://localhost:7687',
    user: process.env.NEO4J_USER ?? 'neo4j',
    password: process.env.NEO4J_PASSWORD ?? 'password',
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
  },
} as const;
