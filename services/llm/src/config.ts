import dotenv from 'dotenv';
dotenv.config();

export const config = {
  port: parseInt(process.env.PORT ?? '8000', 10),

  /**
   * Ollama base URL (default: local Ollama instance).
   * The LLM pod communicates with Ollama to run inference.
   */
  ollama: {
    baseUrl: process.env.OLLAMA_BASE_URL ?? 'http://ollama:11434',
    model: process.env.OLLAMA_MODEL ?? 'llama3.2',
  },
} as const;
