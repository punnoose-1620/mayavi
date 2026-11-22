# Quality test results

Conversation continuity on the USB chat. Five short chats, six turns each. The runner uses the same message builder as the window, with empty notes and no attachments. Each reply is capped at 512 tokens. Context is 4096. GPU offload is off.

A turn score is 0, 1, or 2. This is not a 1 to 10 scale.

## Parameters

| Parameter | Scale | Counted on |
| --- | --- | --- |
| Relevance | 0 to 2, higher is better | Every turn |
| Continue | 0 to 2, higher is better | Turns 2 to 6 |
| Hallucination in the reply | 0 to 2, higher is worse | Every turn |
| Hallucination while continuing | 0 to 2, higher is worse | Turns 2 to 6 |

Relevance is whether that reply does what the turn asked. Continue is whether it keeps the earlier decisions and applies the new instruction. A hallucination is an invented fact, or a fact the user already ruled out. The second hallucination score is that same problem on a later turn: a rejected fact brought back, or a new false fact added while the chat goes on.

A test score is the average of its turns. A model score is the average of the five tests.

The five chats are a grocery list, a birthday plan, a landlord note, a running total, and watering steps. Each one starts with a short request and then corrects the reply: a headcount, a forbidden item, a number, or a step that no longer fits.

## Model comparison

Same five chats on each model. DeepSeek Coder 6.7B is the 8 October run. That file is no longer on the stick. The six larger files were not loaded, so they have no average.

| Model | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Qwen2.5 3B Instruct | 1.4 | 1.5 | 0.9 | 1.0 |
| Qwen2.5 1.5B Instruct | 1.3 | 1.2 | 1.1 | 1.2 |
| DeepSeek Coder 6.7B | 0.3 | 0.4 | 1.8 | 1.6 |

## 9 October 2026

Free RAM was about 6.4 to 6.9 GB. The chat loads a GGUF only when free RAM is at least file size times 1.2, plus 2 GB. Qwen2.5 1.5B and Qwen2.5 3B fit. The six larger files on the stick did not.

### Qwen2.5 3B Instruct Q4_K_M

Overall: relevance 1.4, continue 1.5, reply hallucination 0.9, continuation hallucination 1.0.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Pasta dinner | 1.2 | 1.6 | 1.0 | 1.0 |
| Birthday plan | 1.0 | 1.0 | 2.0 | 2.0 |
| Heater note | 1.8 | 1.8 | 0.2 | 0.2 |
| Week costs | 2.0 | 2.0 | 0.0 | 0.0 |
| Desk plant | 1.0 | 1.0 | 1.2 | 1.6 |

The week-cost lines stayed exact, including the first total of 1800. The heater note kept apartment 4B and added Thursday. The birthday plan kept Ravi, 30, Saturday, his apartment, 6 people, and 400 kronor, and still offered cake after the request said he does not want one.

### Qwen2.5 1.5B Instruct Q4_K_M

Overall: relevance 1.3, continue 1.2, reply hallucination 1.1, continuation hallucination 1.2.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Pasta dinner | 1.2 | 1.2 | 1.0 | 1.6 |
| Birthday plan | 0.8 | 0.8 | 2.0 | 2.0 |
| Heater note | 1.7 | 1.8 | 0.5 | 0.2 |
| Week costs | 1.7 | 1.4 | 0.3 | 0.4 |
| Desk plant | 1.0 | 1.0 | 1.7 | 1.8 |

The running totals were kept, except the reply called the pre-coffee total 2000 when the question asked for the first total of 1800. Salt, pepper, and oil stayed on the grocery list after they were excluded. The birthday reply kept the cake.

### Not loaded

| Model | RAM the chat requires |
| --- | --- |
| Qwen2.5 7B Instruct Q4_K_S | 7.5 GB |
| Llama 3.1 8B Instruct Q4_K_M | 8.1 GB |
| Qwen3 8B Q4_K_M | 8.2 GB |
| Gemma 2 9B Instruct Q4_K_M | 9.1 GB |
| Qwen2.5 14B Instruct Q4_K_M | 12.9 GB |
| Qwen3 14B Q4_K_M | 13.0 GB |

## 8 October 2026

DeepSeek Coder 6.7B Q4_K_M was the file the window loaded before the stick was replaced. That file is no longer on the stick. Same five chats, same four parameters.

Overall: relevance 0.3, continue 0.4, reply hallucination 1.8, continuation hallucination 1.6.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Pasta dinner | 0.2 | 0.0 | 2.0 | 2.0 |
| Birthday plan | 0.2 | 0.4 | 2.0 | 1.8 |
| Heater note | 0.0 | 0.0 | 2.0 | 2.0 |
| Week costs | 0.8 | 1.4 | 1.2 | 0.4 |
| Desk plant | 0.5 | 0.4 | 2.0 | 1.6 |
