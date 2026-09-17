// JSONL bridge to TypeSafe Jev through Vercel AI Gateway (evaluation is AI SDK-only).
// stdin:  {"id": "...", "state": <string|object>, "questions": {...}}
// stdout: {"id": "...", "answers": {...}, "confidence": {...}, "usage": {...}} or {"id": "...", "error": "..."}
// Env: AI_GATEWAY_API_KEY (read from the repo .env by the Python caller), JEV_CONCURRENCY (default 16).
import { experimental_evaluate as evaluate } from "ai";

const concurrency = Number(process.env.JEV_CONCURRENCY ?? 16);
const model = process.env.JEV_MODEL ?? "typesafe-ai/jev";

async function one(line: string): Promise<string> {
  const req = JSON.parse(line);
  for (let attempt = 0; ; attempt++) {
    try {
      const result = await evaluate({
        model,
        state: req.state,
        questions: req.questions,
        // Request-level ZDR needs a Vercel Pro plan; Jev itself is listed as ZDR/no-training.
        ...(process.env.JEV_ZDR === "1" ? { providerOptions: { gateway: { zeroDataRetention: true } } } : {}),
      });
      return JSON.stringify({
        id: req.id,
        answers: result.answers,
        confidence: result.providerMetadata?.typesafe?.confidence ?? null,
        usage: result.usage,
      });
    } catch (err) {
      const message = String((err as Error)?.message ?? err);
      if (attempt >= 3 || !/429|rate|timeout|ECONNRESET|5\d\d/i.test(message)) {
        return JSON.stringify({ id: req.id, error: message.slice(0, 300) });
      }
      await new Promise((r) => setTimeout(r, 2000 * 2 ** attempt));
    }
  }
}

const lines = (await Bun.stdin.text()).split("\n").filter((l) => l.trim());
let next = 0;
async function worker() {
  while (next < lines.length) {
    const line = lines[next++];
    process.stdout.write((await one(line)) + "\n");
  }
}
await Promise.all(Array.from({ length: Math.min(concurrency, lines.length) }, worker));
