import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import morgan from 'morgan';
import rateLimit from 'express-rate-limit';

import { config } from './config';
import { errorHandler } from './middleware/errorHandler';
import papersRouter from './routes/papers';
import scraperRouter from './routes/scraper';
import graphRouter from './routes/graph';

const app = express();

app.use(helmet());
app.use(cors());
app.use(morgan('combined'));
app.use(express.json());

const apiLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 100,
  standardHeaders: true,
  legacyHeaders: false,
});

app.get('/health', (_req, res) => {
  res.json({ status: 'ok' });
});

app.use('/api', apiLimiter);
app.use('/api/papers', papersRouter);
app.use('/api/scraper', scraperRouter);
app.use('/api/graph', graphRouter);

app.use(errorHandler);

app.listen(config.port, () => {
  console.log(`Backend listening on port ${config.port}`);
});

export default app;
