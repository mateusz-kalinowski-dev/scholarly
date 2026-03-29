import * as Minio from 'minio';
import { config } from '../config';

export const minioClient = new Minio.Client({
  endPoint: config.minio.endPoint,
  port: config.minio.port,
  useSSL: config.minio.useSSL,
  accessKey: config.minio.accessKey,
  secretKey: config.minio.secretKey,
});

export async function ensureBucketExists(): Promise<void> {
  const exists = await minioClient.bucketExists(config.minio.bucket);
  if (!exists) {
    await minioClient.makeBucket(config.minio.bucket);
    console.log(`Bucket "${config.minio.bucket}" created.`);
  }
}
