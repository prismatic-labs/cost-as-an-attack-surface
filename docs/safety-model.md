# Safety model

The workshop shows a resource-amplification failure without pointing it at infrastructure. The safety model is the set of constraints that keep it that way.

## Local simulation only

The package makes no network calls. The agent, the simulator, and the mock tools do not open sockets, do not accept a target URL, and do not call a model API. There are no model weights to download. A test scans the package source for network clients and model-loading calls.

## Why external services are not targeted

A Denial-of-Wallet demonstration against a real meter would spend money or quota that belongs to someone, often someone who did not consent. It would also teach the wrong lesson: that the interesting part is the outbound traffic. The interesting part is the loop that multiplies work after a request has already been accepted. That loop can be measured in-process.

The notes are fictional. The injected instructions in DOC-14 are aimed at the scripted classroom agent. They contain no payload for any real system.

The "your own agent" cell in the notebook is arithmetic over numbers the participant types. It runs no agent, and it sends nothing anywhere.

## The optional real-model cell

The last cell of the notebook is a sketch of the same loop with a model deciding each step. It is optional. As shipped it uses a stand-in function and calls no model, so the notebook still makes no network calls.

A reader who replaces the stand-in with a call to their own model is spending their own budget on their own account. Three things keep that bounded: the tools stay local mocks over the fictional notes, the same guard checks every step, and the hard ceilings below apply, so one run cannot pass 24 model calls or 50,000 estimated tokens. The cell says this, and says not to point it at anything that is not the reader's own.

## Global execution ceilings

`SafetyCeilings` in `config.py` is the non-bypassable bound:

| Ceiling | Value |
| --- | --- |
| Iterations per session | 24 |
| Requests per session | 6 |
| Tool calls per session | 64 |
| Total tokens | 50,000 |
| Context tokens | 8,000 |
| Output tokens per model call | 128 |
| Tool text per call | 512 |
| Stalled iterations before a stop | 24 (the progress check is effectively off at the ceiling) |
| Wall-clock per session | 180 seconds |
| Illustrative cost | 5.00 USD |

`clamp_workload` shrinks a requested schedule before the loop. `clamp_policy` shrinks a requested policy when the guard is constructed, and the challenge reports any field it reduced. Tests run oversized schedules with very large policies against all four note sets and assert that the measured run stays inside the table. The appendix pages of the bulky note set are 512 tokens, which is the ceiling for tool text per call: the sandbox cannot serve a larger page.

These values are classroom bounds. They are not a recommendation for a production agent.

## Two different limits

"No policy" in the notebook means the sandbox policy, which sits on the ceiling. It is the loosest policy this process will execute. The poisoned run under it stops at the agent's own iteration limit of 10 model calls, well inside the ceiling. The budget and progress-check runs add a tighter policy. Every run is bounded. None is an infinite loop.

## Repeated execution

Cells can be re-run freely. Every run builds a new guard and stays under the same ceiling, so a repeat cannot accumulate past it. Inside one guard, a trip opens the circuit until reset, and a nested session is refused.

## Safe demonstration parameters

The notebook's defaults stay well inside the ceilings. The challenge cell accepts any integers. Values above the ceiling are reduced to it, and invalid values print a message instead of running.

Do not raise the ceilings to make a more dramatic chart. The growth table shows larger loops as arithmetic, without running them.

## What participants should not be asked to do

- Point the pattern at an API key, an agent or a service that is not theirs.
- Plant instructions in documents that a real agent reads.
- Treat the illustrative USD column as evidence of a real loss.
