# References

Links below were checked while this workshop was prepared in November 2026. Prefer the publisher's current page if a site moves.

## OWASP

- OWASP Top 10 for LLM Applications 2025, including LLM01:2025 Prompt Injection, LLM06:2025 Excessive Agency, and LLM10:2025 Unbounded Consumption: <https://genai.owasp.org/llm-top-10/>
- LLM01:2025 Prompt Injection, which covers indirect injection through content the model reads: <https://genai.owasp.org/llmrisk/llm01-prompt-injection/>
- LLM10:2025 Unbounded Consumption, which names Denial of Wallet as operations that exploit pay-per-use AI pricing: <https://genai.owasp.org/llmrisk/llm102025-unbounded-consumption/>
- OWASP GenAI Security Project, *Agentic AI: Threats and Mitigations*. Its list of agent threats includes one called Resource Overload (T4): <https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/>

This workshop does not reproduce those documents. It uses them as the public framing for a local, bounded experiment.

## Research and incident reports

These are the evidence that real systems behave this way. Papers are cited by title and arXiv number, and their authors are listed on each paper's page. The workshop's own agent is scripted, so it cannot be.

- *OverThink: Slowdown Attacks on Reasoning LLMs*, arXiv:2502.02542, first submitted February 2025. Decoy reasoning problems are injected into content a model retrieves. The abstract reports reasoning-token increases of 13×, 46× and 12× on three datasets, and up to 17× when decoys are placed in the skills, README files and code that coding agents read: <https://arxiv.org/abs/2502.02542>
- *Breaking Agents: Compromising Autonomous LLM Agents Through Malfunction Amplification*, arXiv:2407.20859, July 2024. Agents are misled into repetitive or irrelevant actions. The abstract reports failure rates above 80% in multiple scenarios. Those come from instructions placed in the user's request: placed in content the agent reads, the loop attack succeeded 20% of the time on a Gmail agent and 0% on a CSV agent (Table 4): <https://arxiv.org/abs/2407.20859>
- *Denial of Wallet: Defining a Looming Threat to Serverless Computing*, arXiv:2104.08031, April 2021. The paper that defines Denial of Wallet as forced financial exhaustion, for serverless platforms: <https://arxiv.org/abs/2104.08031>
- Sysdig Threat Research Team, *LLMjacking: Stolen Cloud Credentials Used in New AI Attack*, 6 May 2024. A different trigger (credential theft) with the same impact. The figure of more than 46,000 USD a day is the article's worst-case calculation at quota limits. It is not a measured loss: <https://sysdig.com/blog/llmjacking-stolen-cloud-credentials-used-in-new-ai-attack/>

## Tokens and billing

Checked on 17 November 2026.

- The example on the basics slide was split with OpenAI's open-source tokenizer, `tiktoken`, using its `o200k_base` encoding: 16 tokens for 10 words. Other tokenizers split text differently: <https://github.com/openai/tiktoken>
- Output tokens cost more than input tokens. In Anthropic's price list, output costs five times input on every listed model: <https://platform.claude.com/docs/en/about-claude/pricing>
- Hidden thinking tokens are billed as output. OpenAI says reasoning tokens "are not visible via the API" and are "billed as output tokens": <https://developers.openai.com/api/docs/guides/reasoning>. Anthropic reports thinking as part of the billed output tokens: <https://platform.claude.com/docs/en/build-with-claude/extended-thinking>

## Iteration limits in agent frameworks

The classroom agent stops at 10 model calls. These are the documented defaults of five frameworks, checked on 13 November 2026. Check the version you run.

| Framework | Setting | Default | Source |
| --- | --- | --- | --- |
| OpenAI Agents SDK (Python) | `max_turns` | 10 | `DEFAULT_MAX_TURNS` in <https://github.com/openai/openai-agents-python/blob/main/src/agents/run_config.py> |
| LangChain `AgentExecutor` | `max_iterations` | 15 | <https://github.com/langchain-ai/langchain/blob/master/libs/langchain/langchain_classic/agents/agent.py> |
| CrewAI | `max_iter` | 20 | <https://docs.crewai.com/en/concepts/agents> |
| smolagents | `max_steps` | 20 | <https://github.com/huggingface/smolagents/blob/main/src/smolagents/agents.py> |
| LangGraph | `recursion_limit` | 10,007 super-steps from version 1.1.4 (10,000 in versions 1.0.6 to 1.1.3) | <https://docs.langchain.com/oss/python/langgraph/graph-api> |

The units differ. A turn or an iteration is roughly one model call. In LangGraph, nodes that run in sequence each use one super-step, so a model call followed by a tool call uses two.

## NIST

- NIST AI Risk Management Framework: <https://www.nist.gov/itl/ai-risk-management-framework>
- NIST AI 100-1, *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*, January 2023: <https://doi.org/10.6028/NIST.AI.100-1>
- NIST AI 600-1, *Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile*, July 2024: <https://doi.org/10.6028/NIST.AI.600-1>

NIST AI 100-1 organises risk work into Govern, Map, Measure, and Manage. NIST AI 600-1 treats operating generative models as resource-intensive. Neither document is a definition of Denial of Wallet. The framework is cited because cost and resource use have to be measured and managed, not only described after an incident.

## Compute

Participants who use Google Colab are using Google's service. Free runtime availability is not part of this project and is not guaranteed. See Google's current Colab FAQ: <https://research.google.com/colaboratory/faq.html>.
