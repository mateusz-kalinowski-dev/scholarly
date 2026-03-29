import express, { Request, Response } from 'express';
import cors from 'cors';
import morgan from 'morgan';
import { generate } from './ollamaClient';
import { config } from './config';

const app = express();
app.use(cors());
app.use(morgan('combined'));
app.use(express.json());

app.get('/health', (_req: Request, res: Response) => {
  res.json({ status: 'ok', model: config.ollama.model });
});

interface SummariseBody {
  text: string;
  title?: string;
}

/**
 * POST /summarise
 * Body: { text: string, title?: string }
 * Returns: { summary: string, keywords: string[] }
 */
app.post('/summarise', async (req: Request<object, object, SummariseBody>, res: Response) => {
  const { text, title } = req.body;

  if (!text || typeof text !== 'string') {
    res.status(400).json({ error: '"text" field is required' });
    return;
  }

  const titleLine = title ? `Title: ${title}\n\n` : '';
  const prompt = `${titleLine}You are a research assistant. Read the following academic text and:
1. Write a concise 3-5 sentence summary.
2. Extract 5-10 key topics/keywords as a JSON array.

Respond in valid JSON only, using this schema:
{"summary": "<summary text>", "keywords": ["keyword1", "keyword2", ...]}

Text:
${text}`;

  try {
    const raw = await generate(prompt);

    // Extract JSON from the model response (it may include surrounding text)
    const jsonMatch = /\{[\s\S]*\}/.exec(raw);
    if (!jsonMatch) {
      res.status(502).json({ error: 'LLM did not return valid JSON', raw });
      return;
    }

    const parsed = JSON.parse(jsonMatch[0]) as { summary?: string; keywords?: string[] };
    res.json({
      summary: parsed.summary ?? '',
      keywords: Array.isArray(parsed.keywords) ? parsed.keywords : [],
    });
  } catch (err) {
    console.error('[llm] Inference error:', err);
    res.status(500).json({ error: 'LLM inference failed' });
  }
});

app.listen(config.port, () => {
  console.log(`[llm] Serving on port ${config.port}, model: ${config.ollama.model}`);
});

export default app;
