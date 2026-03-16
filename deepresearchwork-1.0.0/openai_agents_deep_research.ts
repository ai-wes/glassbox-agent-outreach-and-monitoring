import { Agent, run, tool, webSearchTool } from '@openai/agents';
import { z } from 'zod';

const sourceSchema = z.object({
  title: z.string(),
  url: z.string().url(),
  whyItMatters: z.string(),
  sourceType: z.enum(['primary', 'secondary', 'expert', 'news', 'reference']),
  credibility: z.number().min(0).max(1),
  publishedAt: z.string().optional(),
});

const researchPlanSchema = z.object({
  topic: z.string(),
  researchQuestions: z.array(z.string()).min(3).max(8),
  searchTerms: z.array(z.string()).min(4).max(10),
  objectives: z.array(z.string()).min(3).max(6),
  inclusionCriteria: z.array(z.string()).min(3).max(6),
  exclusions: z.array(z.string()).min(2).max(6),
});

const initialInvestigationSchema = z.object({
  keyConcepts: z.array(z.string()).min(3).max(12),
  preliminaryFindings: z.array(z.string()).min(3).max(10),
  prioritizedSources: z.array(sourceSchema).min(5).max(12),
  gapsToInvestigate: z.array(z.string()).min(2).max(8),
});

const deepDiveSourceSchema = z.object({
  source: sourceSchema,
  summary: z.string(),
  keyPoints: z.array(z.string()).min(2).max(8),
  quotationsOrFacts: z.array(z.string()).min(1).max(6),
  credibilityNotes: z.array(z.string()).min(1).max(5),
});

const deepDiveSchema = z.object({
  detailedContent: z.array(deepDiveSourceSchema).min(3).max(8),
  crossReferences: z.array(z.object({
    topic: z.string(),
    agreementLevel: z.number().min(0).max(1),
    notes: z.string(),
  })).min(2).max(10),
  expertSources: z.array(sourceSchema).min(1).max(6),
  comparativeAnalysis: z.array(z.string()).min(2).max(8),
});

const verifiedClaimSchema = z.object({
  claim: z.string(),
  verified: z.boolean(),
  confidence: z.number().min(0).max(1),
  supportingSources: z.array(z.string().url()).min(1).max(6),
  notes: z.string(),
});

const synthesisSchema = z.object({
  patterns: z.array(z.string()).min(2).max(10),
  contradictions: z.array(z.string()).min(0).max(8),
  verifiedClaims: z.array(verifiedClaimSchema).min(3).max(12),
  biasAssessment: z.object({
    overallBiasRisk: z.enum(['low', 'medium', 'high']),
    notes: z.array(z.string()).min(1).max(8),
  }),
  confidenceLevels: z.array(z.object({
    area: z.string(),
    confidence: z.number().min(0).max(1),
    rationale: z.string(),
  })).min(2).max(10),
});

const reportSchema = z.object({
  executiveSummary: z.string(),
  detailedFindings: z.array(z.object({
    title: z.string(),
    finding: z.string(),
    evidence: z.array(z.string()).min(1).max(6),
    confidence: z.enum(['low', 'medium', 'high']),
  })).min(3).max(10),
  sourceEvaluation: z.object({
    averageCredibility: z.number().min(0).max(1),
    sourceDiversity: z.enum(['poor', 'fair', 'good', 'excellent']),
    strongestSources: z.array(z.string().url()).min(1).max(5),
    weakestSources: z.array(z.string().url()).max(5),
  }),
  remainingQuestions: z.array(z.string()).min(1).max(8),
  researchMethodology: z.array(z.string()).min(3).max(8),
});

type ResearchPlan = z.infer<typeof researchPlanSchema>;
type InitialInvestigation = z.infer<typeof initialInvestigationSchema>;
type DeepDive = z.infer<typeof deepDiveSchema>;
type Synthesis = z.infer<typeof synthesisSchema>;
type Report = z.infer<typeof reportSchema>;

export type DeepResearchContext = {
  topic: string;
  requestedQuestions: string[];
  startedAt: string;
  fetchedUrls: string[];
};

const pageFetchTool = tool<DeepResearchContext>({
  name: 'fetch_page_text',
  description: 'Fetch a public web page and return compact readable text. Use this to inspect sources after web search finds them.',
  parameters: z.object({
    url: z.string().url(),
    maxChars: z.number().int().min(1000).max(50000).default(12000),
  }),
  execute: async ({ url, maxChars }, context) => {
    const res = await fetch(url, {
      headers: {
        'user-agent': 'deep-research-agent/1.0',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      },
    });

    if (!res.ok) {
      throw new Error(`Failed to fetch ${url}: ${res.status} ${res.statusText}`);
    }

    const html = await res.text();
    const text = html
      .replace(/<script[\s\S]*?<\/script>/gi, ' ')
      .replace(/<style[\s\S]*?<\/style>/gi, ' ')
      .replace(/<noscript[\s\S]*?<\/noscript>/gi, ' ')
      .replace(/<[^>]+>/g, ' ')
      .replace(/&nbsp;/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, maxChars);

    context?.context?.fetchedUrls?.push(url);

    return {
      url,
      text,
      charCount: text.length,
    };
  },
  timeoutMs: 20000,
});

const plannerAgent = new Agent<DeepResearchContext, ResearchPlan>({
  name: 'Research Planner',
  model: 'gpt-5.4',
  instructions: `You create concise, high-quality research plans.
Return a structured plan for the topic.
If the user supplied research questions, preserve them and add only what is needed.
Search terms should be web-search friendly and varied.
Objectives should reflect multi-source verification, contradiction detection, and synthesis.`,
  outputType: researchPlanSchema,
});

const searchAgent = new Agent<DeepResearchContext, InitialInvestigation>({
  name: 'Initial Investigator',
  model: 'gpt-5.4',
  instructions: `Use web search to map the topic landscape.
Find a diverse set of high-value sources.
Prefer official docs, reputable institutions, recognized experts, and strong reference material.
Return prioritized sources with credibility scores between 0 and 1.`,
  tools: [webSearchTool()],
  outputType: initialInvestigationSchema,
});

const sourceAnalyzerAgent = new Agent<DeepResearchContext, DeepDive>({
  name: 'Source Analyzer',
  model: 'gpt-5.4',
  instructions: `Inspect the most relevant sources in detail.
Use the page fetch tool to read the actual pages when possible.
Extract key points, notable factual statements, and credibility notes.
Compare sources and identify areas of agreement.`,
  tools: [pageFetchTool],
  outputType: deepDiveSchema,
});

const validatorAgent = new Agent<DeepResearchContext, Synthesis>({
  name: 'Validator',
  model: 'gpt-5.4',
  instructions: `Synthesize the source analysis.
Identify patterns, contradictions, and validated claims.
Be conservative with confidence scores.
Mark a claim verified only when the available evidence clearly supports it.`,
  outputType: synthesisSchema,
});

const writerAgent = new Agent<DeepResearchContext, Report>({
  name: 'Research Writer',
  model: 'gpt-5.4',
  instructions: `Create a structured research report.
Base the report only on the provided prior results.
Keep the executive summary compact and the findings evidence-backed.
For source evaluation, score diversity realistically and identify strongest and weakest sources by URL.`,
  outputType: reportSchema,
});

function average(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function calculateConfidence(synthesis: Synthesis): number {
  const claimConfidence = average(synthesis.verifiedClaims.map((c) => c.confidence));
  const areaConfidence = average(synthesis.confidenceLevels.map((c) => c.confidence));
  const contradictionPenalty = Math.min(synthesis.contradictions.length * 0.03, 0.15);
  return Math.max(0, Math.min(1, (claimConfidence * 0.65 + areaConfidence * 0.35) - contradictionPenalty));
}

export class OpenAIAgentsDeepResearch {
  constructor(private readonly opts: { maxSources?: number } = {}) {}

  async conductResearch(topic: string, researchQuestions: string[] = []) {
    const context: DeepResearchContext = {
      topic,
      requestedQuestions: researchQuestions,
      startedAt: new Date().toISOString(),
      fetchedUrls: [],
    };

    const plannerInput = JSON.stringify({
      topic,
      requestedQuestions: researchQuestions,
      constraints: {
        desiredSearchTerms: 6,
        desiredQuestions: researchQuestions.length > 0 ? researchQuestions.length : 5,
      },
    });

    const planResult = await run(plannerAgent, plannerInput, { context });
    const researchPlan = planResult.finalOutput;

    const searchInput = JSON.stringify({
      topic,
      researchPlan,
      instruction: 'Use web search to identify the best sources for the plan. Prioritize diversity and authority.',
      maxSources: this.opts.maxSources ?? 8,
    });

    const initialResult = await run(searchAgent, searchInput, { context });
    const phase1 = initialResult.finalOutput;

    const selectedSources = phase1.prioritizedSources.slice(0, this.opts.maxSources ?? 5);
    const analysisInput = JSON.stringify({
      topic,
      researchPlan,
      selectedSources,
      instruction: 'Read and analyze these sources in depth. Use the fetch tool for page text when useful.',
    });

    const deepDiveResult = await run(sourceAnalyzerAgent, analysisInput, { context });
    const phase2 = deepDiveResult.finalOutput;

    const validationInput = JSON.stringify({
      topic,
      researchPlan,
      phase1,
      phase2,
      instruction: 'Synthesize the analysis, assess contradictions, and produce calibrated confidence scores.',
    });

    const validationResult = await run(validatorAgent, validationInput, { context });
    const phase3 = validationResult.finalOutput;

    const reportInput = JSON.stringify({
      topic,
      researchQuestions: researchPlan.researchQuestions,
      objectives: researchPlan.objectives,
      phase1,
      phase2,
      phase3,
      fetchedUrls: context.fetchedUrls,
    });

    const reportResult = await run(writerAgent, reportInput, { context });
    const report = reportResult.finalOutput;

    return {
      topic,
      researchPlan,
      findings: {
        phase1,
        phase2,
        phase3,
      },
      report,
      confidence: Number(calculateConfidence(phase3).toFixed(3)),
      metadata: {
        startedAt: context.startedAt,
        fetchedUrls: [...new Set(context.fetchedUrls)],
      },
    };
  }
}

async function main() {
  const researcher = new OpenAIAgentsDeepResearch({ maxSources: 5 });

  const result = await researcher.conductResearch('Artificial intelligence in healthcare', [
    'How is AI currently being used in healthcare?',
    'What benefits are most supported by evidence?',
    'What risks and limitations matter most?',
  ]);

  console.dir(result, { depth: null });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
