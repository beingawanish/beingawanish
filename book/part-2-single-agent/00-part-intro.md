# Part 2 — Single-agent reasoning

> In Part 2, **one model decides what happens next**. The code supplies tools, limits and checks, and the model chooses the sequence.

That one change, moving control flow from your code to the model, is what people usually mean by *agent*. It buys flexibility: the agent can take a path you did not anticipate, react to a tool's surprising answer, or decide it needs more evidence. It costs predictability. You can no longer write the number of calls in advance, only bound it.

So every pattern in this part has the same shape: **a model in a loop, and a host that owns the loop's edges**. The host validates what the model asks for, executes it, decides what counts as done, and stops the loop when it is not converging.

| Pattern | The model decides… | The host owns… |
|---|---|---|
| [6. ReAct](06-react.md) | the next thought and action | parsing, tool execution, repeat and step guards |
| [7. Plan-and-execute](07-plan-and-execute.md) | the whole plan, and when to re-plan | plan validation, step execution, re-plan budget |
| [8. Reflection](08-reflection.md) | what is wrong with its own answer | the number of rounds |
| [9. Tool-use loop](09-tool-use-loop.md) | which tool to call, with what arguments | schemas, confirmations, errors-as-observations, stop conditions |
| [10. Agentic RAG](10-agentic-rag.md) | whether, what and how often to retrieve | retrieval, citation checking, abstention |
| [11. Guardrailed generation](11-guardrailed-generation.md) | the content | every validity rule, the repair budget, the fallback |

Two patterns here are *runtimes* rather than strategies. The [tool-use loop](09-tool-use-loop.md) is the machinery every agent in this book runs on, and [guardrailed generation](11-guardrailed-generation.md) is the generate–check–repair discipline that keeps any single output valid. The other four are *reasoning strategies* that run on top of them.

**When to come here from Part 1:** when you cannot write the sequence of steps down, because it depends on what the agent finds. If you can write it down, stay in Part 1: it is cheaper, faster and easier to test.

The part closes with the [deep-research capstone](../capstones/deep-research.md), which composes plan-and-execute, agentic RAG and reflection with evaluator–optimizer (#5) and memory tiers (#19).
