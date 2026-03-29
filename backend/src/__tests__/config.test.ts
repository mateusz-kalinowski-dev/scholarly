import { config } from '../config';

describe('config', () => {
  it('should have default port 3000', () => {
    expect(config.port).toBe(3000);
  });

  it('should have neo4j defaults', () => {
    expect(config.neo4j.uri).toBeDefined();
    expect(config.neo4j.user).toBeDefined();
  });

  it('should have minio bucket defined', () => {
    expect(config.minio.bucket).toBe('scholarly-pdfs');
  });
});
