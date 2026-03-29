import axios from 'axios';
import { config } from './config';

interface SummariseRequest {
  text: string;
  title?: string;
}

interface SummariseResponse {
  summary: string;
  keywords: string[];
}

/**
 * Sends text to the LLM pod and returns a structured summary.
 */
export async function summarise(req: SummariseRequest): Promise<SummariseResponse> {
  const response = await axios.post<SummariseResponse>(
    `${config.llm.baseUrl}/summarise`,
    req,
    { timeout: 120_000 },
  );
  return response.data;
}
