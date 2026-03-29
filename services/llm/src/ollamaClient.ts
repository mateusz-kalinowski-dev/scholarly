import axios from 'axios';
import { config } from './config';

interface OllamaGenerateResponse {
  response: string;
}

/**
 * Calls the Ollama /api/generate endpoint with the given prompt.
 */
export async function generate(prompt: string): Promise<string> {
  const response = await axios.post<OllamaGenerateResponse>(
    `${config.ollama.baseUrl}/api/generate`,
    {
      model: config.ollama.model,
      prompt,
      stream: false,
    },
    { timeout: 120_000 },
  );
  return response.data.response.trim();
}
