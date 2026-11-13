# Production mapping worksheet

Fill this in after the notebook, on your own or with your team. The classroom agent is a local sandbox. The questions are about the agent you actually operate.

**ILLUSTRATIVE SIMULATED COST. NOT AN ACTUAL API BILL.** The USD figures from the notebook do not transfer. The questions do.

## The five questions

| Question | LangChain / LlamaIndex / similar | Hosted assistants (OpenAI, Azure, Vertex, Bedrock) | The agent we actually run |
| --- | --- | --- | --- |
| 1. Do we know the cost of one agent execution (tokens, tool calls, time)? | | | |
| 2. Can we attribute that cost to a user, an agent, a tool, and the document that drove it? | | | |
| 3. Can we enforce a hard limit *during* the execution, before the next model or tool call? | | | |
| 4. Can we see unusual consumption when the request rate looks normal? | | | |
| 5. Can we stop one runaway execution without taking down the service? | | | |

## Your iteration limit

The classroom agent stopped at 10 model calls. Find the limit on yours. These are documented defaults, checked on 13 November 2026, with sources in [presentation/references.md](../presentation/references.md).

| Framework | Setting | Documented default |
| --- | --- | --- |
| OpenAI Agents SDK (Python) | `max_turns` | 10 |
| LangChain `AgentExecutor` | `max_iterations` | 15 |
| CrewAI | `max_iter` | 20 |
| smolagents | `max_steps` | 20 |
| LangGraph | `recursion_limit` | 10,007 super-steps from version 1.1.4 |
| The agent we actually run | | |

An iteration limit is not a budget. It is the amount an attacker gets on every request that reads a tampered document.

## Your exposure

Copy these from notebook section 9, after replacing the classroom numbers with your own.

| | Model calls | Tokens | USD per run | USD per day |
| --- | --- | --- | --- | --- |
| A normal run | | | | |
| A run that loops to our iteration limit | | | | |
| The same loop, stopped by a budget of 3× a normal run | | | | |

Numbers we had to guess, and who can give us the real ones:

## What the classroom run measured

Copy the numbers from your notebook.

| Run | Model calls | Total tokens | Stopped by |
| --- | --- | --- | --- |
| Normal request | | | |
| Poisoned note, no policy | | | |
| Poisoned note, budget | | | |
| Long task, budget | | | |
| Poisoned note, progress check | | | |
| Long task, progress check | | | |

## Your challenge policy

| Knob | Value |
| --- | --- |
| max_iterations | |
| max_tool_calls | |
| max_total_tokens | |
| max_context_tokens | |
| max_stalled_iterations | |

| | Real tasks finished | Attack tokens let through |
| --- | --- | --- |
| Round one, best attempt | of 2 | |
| Round two, same policy | of 3 | |
| Round two, after fixing it | of 3 | |

Which limit stopped each attack? Which real task did your round-one policy break, and which limit broke it? How much headroom would your longest legitimate task need, and what does that headroom cost you?

## Notes

- An per-request iteration limit is not a budget. An attacker who triggers the loop gets all of it, every time.
- A budget fitted exactly to the longest task you have seen will break the next longer one. Size limits from measured runs, add headroom, and review them when the work changes.
- A limit that counts calls does not see how large each call is. Keep a token or context limit next to it.
- A monthly cloud budget is a backstop. It is not the answer to question 3 if it lags or kills every workload at once.
- Content your agent reads is input. If someone else can edit it, they can steer your spend.
- A tool that calls a model on its own spends budget the application guard cannot see.
- Shared API keys make question 2 unanswerable.

This page is for you. Nobody collects it.
