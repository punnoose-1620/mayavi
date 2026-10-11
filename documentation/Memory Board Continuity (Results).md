# Memory board continuity

Same five chats as the quality bench, six turns each. Each model kept one named test board for all five chats. The same loaded model answered, checked the topic, and wrote the summaries. The router did not switch models.

A turn score is 0, 1, or 2. Relevance and continue are higher-is-better. Hallucination is higher-is-worse. The scale matches `Quality Test Results.md`.

Boards live under `E:\logs\test-boards\`. A copy of each board is also in `outputs/continuity/<model>/board.json`.

## Comparison

Qwen2.5 1.5B and Qwen2.5 3B are the only models in the 9 October quality run. The other models had no earlier continuity average.

| Model | Board | Relevance | Continue | Reply hallucination | Continuation hallucination | Old relevance | Old continue |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Qwen2.5 1.5B | continuity-qwen2.5-1.5b-instruct-q4_k_m | 1.0 | 0.7 | 1.2 | 1.3 | 1.3 | 1.2 |
| Qwen2.5 3B | continuity-qwen2.5-3b-instruct-q4_k_m | 1.2 | 1.0 | 1.2 | 1.2 | 1.4 | 1.5 |
| Qwen2.5 7B | continuity-qwen2.5-7b-instruct-q4_k_s | 1.5 | 1.5 | 0.8 | 0.8 |  |  |
| Llama 3.1 8B | continuity-meta-llama-3.1-8b-instruct-q4_k_m | 1.2 | 1.0 | 1.0 | 1.1 |  |  |
| Qwen3 8B | continuity-qwen3-8b-q4_k_m | 1.0 | 0.8 | 0.3 | 0.2 |  |  |
| Gemma 2 9B | continuity-gemma-2-9b-it-q4_k_m | 1.6 | 1.6 | 0.5 | 0.5 |  |  |

Gemma did not fit at the start (free RAM about 8.7 GB, the chat requires about 9.1 GB). It fit after the earlier models unloaded. Both 14B files were skipped. They need about 12.9 GB. Free RAM at the end was about 10.6 GB.

Relevance and continuity did not rise from the start of a chat to the end. On the two models with an old score, both numbers went down. The early turns are often the clean ones. The later turns are where a summary from another topic comes back.

## Boards

Five topics should have produced at least five summaries, with a topic row when the subject changed and a routine row only when one subject ran long. That is not what the files contain.

| Model | Summaries | Routine | Topic | What the board actually did |
| --- | --- | --- | --- | --- |
| Qwen2.5 1.5B | 4 | 4 | 0 | Never accepted a topic change. The stored topic stayed the first grocery sentence. The last routine row mixes the week costs with the plant. |
| Qwen2.5 3B | 12 | 5 | 7 | Split follow-ups inside one grocery chat. The stored topic became the instruction line "a short phrase for the new message". |
| Qwen2.5 7B | 10 | 1 | 9 | Split several corrections into their own rows. The heater note and the running total stayed exact. |
| Llama 3.1 8B | 12 | 0 | 12 | A topic row on many follow-ups. The heater replies after the first one lead with the pasta list. |
| Qwen3 8B | 24 | 6 | 18 | A new row on most turns. Thinking used the 512 reply cap, so many visible answers are empty or cut off. |
| Gemma 2 9B | 19 | 0 | 19 | A topic row on most corrections. The running total stayed exact. The last plant reply recalls the grocery list. |

No board has one summary per topic. The 1.5B board is short of five rows. The others are over five because a correction inside the same chat was treated as a new topic.

## Per test

### Qwen2.5 1.5B

Overall: relevance 1.0, continue 0.7, reply hallucination 1.2, continuation hallucination 1.3.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Pasta dinner | 0.8 | 0.2 | 2.0 | 2.0 |
| Birthday plan | 1.0 | 1.0 | 2.0 | 2.0 |
| Heater note | 1.5 | 1.4 | 0.2 | 0.2 |
| Week costs | 1.2 | 1.0 | 0.8 | 1.0 |
| Desk plant | 0.3 | 0.0 | 1.2 | 1.2 |

Salt, pepper, and oil stayed on the grocery list. The birthday cake stayed. The first three cost totals were exact, then the groceries reverted and the recalled first total became 2100. Asked what the plant chat started with, the reply named the bus card.

### Qwen2.5 3B

Overall: relevance 1.2, continue 1.0, reply hallucination 1.2, continuation hallucination 1.2.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Pasta dinner | 0.8 | 0.4 | 1.8 | 2.0 |
| Birthday plan | 1.2 | 0.8 | 2.0 | 2.0 |
| Heater note | 1.7 | 1.8 | 0.5 | 0.4 |
| Week costs | 1.5 | 1.4 | 0.7 | 0.8 |
| Desk plant | 1.0 | 0.8 | 0.8 | 1.0 |

The rice dinner's final list still had olive oil, salt, and pepper, and it did not say how many people. Saturday was marked "not specified". The cost lines were exact through coffee, then the final list put groceries back at 900. The plant's last reply described the week costs.

### Qwen2.5 7B

Overall: relevance 1.5, continue 1.5, reply hallucination 0.8, continuation hallucination 0.8.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Pasta dinner | 1.0 | 1.0 | 1.0 | 1.0 |
| Birthday plan | 1.0 | 1.0 | 2.0 | 2.0 |
| Heater note | 2.0 | 2.0 | 0.2 | 0.2 |
| Week costs | 2.0 | 2.0 | 0.0 | 0.0 |
| Desk plant | 1.3 | 1.4 | 0.7 | 0.6 |

The heater note kept 4B and added Thursday. Every cost line stayed exact, including the first total of 1800 and the final total of 2150. The grocery list kept invented meat and two sauces, and the final line called a rice list a pasta dinner. The birthday plan kept cake-or-decoration extras until late, and the cost estimate stayed above 400 kronor. The plant's last reply did name the plant, not an earlier topic.

### Llama 3.1 8B

Overall: relevance 1.2, continue 1.0, reply hallucination 1.0, continuation hallucination 1.1.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Pasta dinner | 1.0 | 1.0 | 1.2 | 1.2 |
| Birthday plan | 1.0 | 0.8 | 1.8 | 1.8 |
| Heater note | 0.5 | 0.0 | 1.7 | 2.0 |
| Week costs | 2.0 | 2.0 | 0.0 | 0.0 |
| Desk plant | 1.3 | 1.0 | 0.3 | 0.4 |

The first heater note was a clean 4B note. Every later heater reply opened with the pasta list. The running total stayed exact. Saturday was marked "not stated". Asked how the plant chat started, the reply described the grocery list.

### Qwen3 8B

Overall: relevance 1.0, continue 0.8, reply hallucination 0.3, continuation hallucination 0.2.

Thinking filled most of the 512-token reply, so the visible answer is often empty or cut off mid-line. Empty text was scored as a missed reply, not as an invented fact. That is why hallucination is low while relevance is low.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Pasta dinner | 0.7 | 0.6 | 0.3 | 0.2 |
| Birthday plan | 0.2 | 0.2 | 0.3 | 0.4 |
| Heater note | 1.2 | 0.8 | 0.5 | 0.6 |
| Week costs | 1.8 | 1.6 | 0.0 | 0.0 |
| Desk plant | 1.0 | 1.0 | 0.2 | 0.0 |

The cost lines through turn 5 were exact. The final cost list dropped coffee and the total. The birthday's name-and-age turn answered with the pasta summary. The plant's last visible line did recall the desk plant.

### Gemma 2 9B

Overall: relevance 1.6, continue 1.6, reply hallucination 0.5, continuation hallucination 0.5.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Pasta dinner | 1.7 | 1.6 | 0.3 | 0.4 |
| Birthday plan | 1.5 | 1.6 | 1.0 | 0.8 |
| Heater note | 1.8 | 1.8 | 0.2 | 0.2 |
| Week costs | 2.0 | 2.0 | 0.0 | 0.0 |
| Desk plant | 0.8 | 0.8 | 1.2 | 1.2 |

The grocery list left out salt, pepper, and oil, swapped to rice, and the final line said three people. The running total stayed exact. The birthday recap kept Ravi, 30, Saturday, the apartment, and 400 kronor, and counted the headcount as 6 guests plus Ravi. The plant steps kept a drainage instruction after the pot was said to have no hole. Asked how the plant chat started, the reply described the pasta list.

## 11 October rerun

The topic check no longer uses word overlap. A summary of the working log is triggered when continuity is at or below 0.3 and independence is at or above 0.7. The same five chats were run again. Reply scores above are from the earlier run. This section is only the boards.

Both 14B files were skipped again. Free RAM at the end was about 11.2 GB. They need about 12.9 GB.

| Model | Before | After | Mixed rows before | Mixed rows after |
| --- | --- | --- | --- | --- |
| Qwen2.5 1.5B | 4 routine, 0 topic | 4 routine, 0 topic | 3 | 3 |
| Qwen2.5 3B | 5 routine, 7 topic | 7 routine, 0 topic | 3 | 2 |
| Qwen2.5 7B | 1 routine, 9 topic | 3 routine, 6 topic | 2 | 1 |
| Llama 3.1 8B | 0 routine, 12 topic | 3 routine, 3 topic | 1 | 1 |
| Qwen3 8B | 6 routine, 18 topic | 9 routine, 4 topic | 0 | 1 |
| Gemma 2 9B | 0 routine, 19 topic | 1 routine, 2 topic | 1 | 1 |

A mixed row covers more than one of the five chats. Qwen3's earlier board was almost all one-turn rows, so the chats were split rather than merged.

Gemma now keeps the whole grocery chat in one row: rice, lettuce, one tomato, no mushrooms. The whole cost chat is one row: 1800, then 1100 and 2000, then coffee and 2150. The plant is still the open working log. The birthday and the heater share one routine row, and that row adds raita and sparkling wine.

Llama keeps the grocery chat in one row. The birthday is three rows of the same party, and those rows still include a dessert. The heater and the costs share one row. The last cost row then lists groceries as 900 and the total as 1950. The plant is the open working log.

The 7B keeps the costs exact in one row: 600, 1100, 300, 150, first total 1800, final total 2150. The grocery chat is two rows, both about that dinner. The birthday is still split turn by turn, and one of those rows also contains the heater. The headcount in those rows moves between 8, 6, and 7.

The 3B never crossed the score line, so every row is a size fold. The heater note is its own five-turn row. The last row still joins the rest of the heater, the costs, and the first plant step, and the summary text only describes watering.

The 1.5B board matches the earlier one. The stored topic is still the opening grocery sentence. Three of the four rows cross chats, and the last row still joins the heater, the costs, and the plant.
