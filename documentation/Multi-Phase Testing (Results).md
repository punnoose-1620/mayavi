# Multi-phase testing results

Same six chats as the testing plan. Selectors for Coding, Web Search, Update profile, and Job application stayed off. Scores are 0 to 2. Relevance and continue are better when higher. Both hallucination scores are worse when higher. Continue and continuation-hallucination skip the opening turn.

A model score is the average of the six tests. Runs are added below as each model finishes.

## Not loaded

These files were on the stick and did not fit free RAM when the run started (about 8.4 GB free). After the smaller models finished, free RAM was about 9.3 GB, so Gemma 2 9B (needs 9.1 GB) was loaded and is scored below. Both 14B files still need about 12.9 GB and were not loaded.

| Model | RAM the chat requires |
| --- | --- |
| Qwen2.5 14B Instruct | 12.9 GB |
| Qwen3 14B | 13.0 GB |

## Qwen3 8B Q4_K_M

No turn left the plain chat path. Thinking was on, so several replies filled the token cap inside the thinking block and never reached an answer. Those turns score 0 on relevance.

Overall: relevance 1.6, continue 1.6, reply hallucination 0.4, continuation hallucination 0.4.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Coding | 1.0 | 0.8 | 0.0 | 0.0 |
| Document building | 2.0 | 2.0 | 0.0 | 0.0 |
| Summarization | 2.0 | 2.0 | 0.0 | 0.0 |
| Report | 2.0 | 2.0 | 0.0 | 0.0 |
| Static UI | 2.0 | 2.0 | 1.0 | 1.0 |
| Planning | 0.7 | 0.8 | 1.3 | 1.4 |

The handoff, the summary, and the shelf report kept every correction. The screen layout did too, and it kept an example tea name and a sample minute that were never given. The kilometre checker was right when an answer appeared, and turns 2, 4, and 5 stopped inside the thinking block. The study plan's first three turns did the same. The later plan named Thursday, 20 cards, 30 minutes, the desk, and no music, then scheduled more than 30 minutes and offered extra cards.

## Llama 3.1 8B Instruct Q4_K_M

No turn left the plain chat path.

Overall: relevance 1.7, continue 1.7, reply hallucination 0.5, continuation hallucination 0.7.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Coding | 1.8 | 1.8 | 0.2 | 0.2 |
| Document building | 1.5 | 1.4 | 0.3 | 1.0 |
| Summarization | 1.7 | 1.6 | 0.0 | 0.4 |
| Report | 1.8 | 2.0 | 0.2 | 0.2 |
| Static UI | 2.0 | 2.0 | 0.8 | 0.8 |
| Planning | 1.3 | 1.6 | 1.5 | 1.4 |

The kilometre rules, the shelf report, and the final screen order stayed intact. The handoff lost Anna's Thursday cover in the readback. The move summary dropped Mr. Cole until the spelling turn put him back. The study plan kept Thursday, 20 cards, 30 minutes, the desk, the break, and no music, and it added scientific names and extra study steps that were never asked for.

## Qwen2.5 7B Instruct Q4_K_S

No turn left the plain chat path.

Overall: relevance 1.6, continue 1.5, reply hallucination 0.4, continuation hallucination 0.6.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Coding | 1.7 | 1.6 | 0.2 | 0.2 |
| Document building | 1.8 | 1.8 | 0.0 | 0.2 |
| Summarization | 1.5 | 1.4 | 0.0 | 0.6 |
| Report | 1.7 | 1.6 | 0.0 | 0.4 |
| Static UI | 1.8 | 1.6 | 0.3 | 0.4 |
| Planning | 1.2 | 1.2 | 2.0 | 2.0 |

The handoff kept bills, Thursday, room 2, and the left hook. The kilometre rates stayed 0.62 and 1.61. The shelf report dropped the Tuesday drill once Nina was added. The final move summary dropped Mr. Cole. The study plan invented plant families and habitats, its 30 minutes did not add up, and the recap said the no-music rule was not stated.

## Qwen2.5 3B Instruct Q4_K_M

No turn left the plain chat path.

Overall: relevance 1.0, continue 0.8, reply hallucination 1.2, continuation hallucination 1.5.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Coding | 0.5 | 0.6 | 2.0 | 2.0 |
| Document building | 0.8 | 0.8 | 1.5 | 1.6 |
| Summarization | 0.8 | 0.6 | 0.7 | 1.0 |
| Report | 1.5 | 1.0 | 0.0 | 1.0 |
| Static UI | 1.2 | 1.0 | 1.0 | 1.6 |
| Planning | 1.0 | 0.8 | 2.0 | 2.0 |

The kilometre checker used 0.621371 instead of 0.62, and the reverse direction divided by that number instead of multiplying by 1.61. The handoff kept saying invoices after the rename to bills, and the final note dropped Ben's Thursday cover. The screen never moved the tea name above the number. The study plan added descriptions, a matching game, and a schedule that ran past 30 minutes, and the recap treated no music as unstated.

## Qwen2.5 1.5B Instruct Q4_K_M

No turn left the plain chat path.

Overall: relevance 1.3, continue 1.3, reply hallucination 0.8, continuation hallucination 0.9.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Coding | 1.3 | 1.2 | 0.2 | 0.2 |
| Document building | 0.3 | 0.4 | 1.8 | 2.0 |
| Summarization | 1.8 | 2.0 | 0.0 | 0.0 |
| Report | 2.0 | 2.0 | 0.0 | 0.0 |
| Static UI | 1.2 | 1.0 | 1.0 | 1.6 |
| Planning | 1.0 | 1.0 | 1.7 | 1.6 |

The shelf report and the move summary kept the corrections, including 2 brackets, Tuesday, Nina on Thursday only, Saturday, 14 Oak Street, Cole, and Monday. The kilometre samples were 3.1, 6.2, and 0.0, and the final rules named both rates and the negative stop, though the miles sample of 5 was shown as 8.0. The handoff swapped who holds which folder and then renamed the red pile to bills. The screen listed the tea name under the buttons after it was asked to sit under the title, and the final list dropped it. The study plan invented a 4:00 start and plant descriptions, put the break after the cards, and the Thursday fix never appeared until the recap.

## Gemma 2 9B Instruct Q4_K_M

No turn left the plain chat path. Free RAM had risen enough to load this file after the smaller models finished.

Overall: relevance 1.8, continue 1.7, reply hallucination 0.5, continuation hallucination 0.5.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Coding | 2.0 | 2.0 | 0.0 | 0.0 |
| Document building | 1.8 | 1.6 | 0.3 | 0.6 |
| Summarization | 1.8 | 2.0 | 0.2 | 0.0 |
| Report | 2.0 | 2.0 | 0.0 | 0.0 |
| Static UI | 1.7 | 1.4 | 0.8 | 1.0 |
| Planning | 1.2 | 1.2 | 1.7 | 1.6 |

The kilometre rules stayed at 0.62 and 1.61, with one decimal, the negative stop, and 5 miles shown as 8.1. The shelf report kept the wall, 2 brackets, Tuesday, Thursday, and Nina. The move summary kept Saturday, the two boxes, 14 Oak Street, Cole, and Monday. The final handoff dropped Anna's Thursday cover of the red folder. The screen moved the tea-name line above the number, then the final list left that line blank. The study blocks added up to 35 minutes inside a 30-minute session and invented plant features. The recap itself named Thursday, 20 cards, 30 minutes, the desk, the break, and no music.

## Model comparison

Average of the six tests. Relevance and continue are better when higher. Both hallucination scores are worse when higher.

| Model | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Gemma 2 9B | 1.8 | 1.7 | 0.5 | 0.5 |
| Llama 3.1 8B | 1.7 | 1.7 | 0.5 | 0.7 |
| Qwen3 8B | 1.6 | 1.6 | 0.4 | 0.4 |
| Qwen2.5 7B | 1.6 | 1.5 | 0.4 | 0.6 |
| Qwen2.5 1.5B | 1.3 | 1.3 | 0.8 | 0.9 |
| Qwen2.5 3B | 1.0 | 0.8 | 1.2 | 1.5 |

Qwen2.5 14B and Qwen3 14B still need about 12.9 GB and were not loaded.

## Second round

Five more chats: search queries, search-result isolation, page reading, feature planning, and debugging. Same 0 to 2 scores. Selectors stayed off, and none of these prompts is allowed to start a large path. A model score for this round is the average of these five tests. The first-round table above stays as it is. Sections are added as each model finishes.

Qwen2.5 14B and Qwen3 14B were tried again for this round. Free RAM was about 10.2 GB. They need 12.9 GB and 13.0 GB, so they were not loaded.

## Gemma 2 9B Instruct Q4_K_M

No turn left the plain chat path.

Overall: relevance 1.7, continue 1.6, reply hallucination 0.1, continuation hallucination 0.0.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Search queries | 1.5 | 1.4 | 0.0 | 0.0 |
| Search results | 2.0 | 2.0 | 0.0 | 0.0 |
| Page reading | 2.0 | 2.0 | 0.0 | 0.0 |
| Feature planning | 1.7 | 1.4 | 0.2 | 0.0 |
| Debugging | 1.2 | 1.4 | 0.3 | 0.2 |

The library answer stayed Sunday 10-17 at Kung Oscars väg 11, and the story kept Lena Voss, 3 March 2024, Marta, Limhamn, 2 cups, rainwater, and 4 minutes. The last query list dropped Holm & Berg. The final four features dropped the same-week return. The ticket listing fixed the empty total, the negative check, and the last-row loop, left mira on the skip list, and never named the rate of 3.

## Qwen3 8B Q4_K_M

No turn left the plain chat path. Thinking was on. A turn that ends inside the thinking block, with no answer, scores 0 on relevance.

Overall: relevance 1.4, continue 1.6, reply hallucination 0.1, continuation hallucination 0.1.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Search queries | 1.8 | 2.0 | 0.0 | 0.0 |
| Search results | 1.8 | 1.8 | 0.0 | 0.0 |
| Page reading | 1.8 | 2.0 | 0.0 | 0.0 |
| Feature planning | 0.7 | 0.8 | 0.3 | 0.4 |
| Debugging | 1.0 | 1.2 | 0.0 | 0.0 |

The final queries kept Nordform, K-14, glide, and Holm & Berg. The library final was Sunday 10:00–17:00 at Kung Oscars väg 11. The story final kept Lena Voss, 3 March 2024, Marta, Limhamn, 2 cups, rainwater, and 4 minutes. Three feature turns never left the thinking block. The final four did include the same-week return. Debugging fixed the empty total, the negative check, and the last-row loop on the turns that answered. The opening, the mira turn, and the final mistake list stopped inside the thinking block.

## Llama 3.1 8B Instruct Q4_K_M

No turn left the plain chat path.

Overall: relevance 1.6, continue 1.5, reply hallucination 0.6, continuation hallucination 0.6.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Search queries | 1.8 | 1.8 | 0.0 | 0.0 |
| Search results | 2.0 | 1.8 | 0.0 | 0.0 |
| Page reading | 1.8 | 2.0 | 0.7 | 0.6 |
| Feature planning | 1.7 | 1.4 | 0.5 | 0.4 |
| Debugging | 0.8 | 0.4 | 1.7 | 2.0 |

The queries kept Nordform, K-14, glide, and Holm & Berg. The library final was Sunday 10-17 at Kung Oscars väg 11. The story final kept Lena Voss, 3 March 2024, Marta, Limhamn, 2 cups, rainwater, and 4 minutes, after adding that she waits and then does something. The final four features dropped the same-week return. Debugging named the rate of 3, the empty total of 1, and the hours-above-100 check, then put otto and noor on the skip list and left mira there.

## Qwen2.5 7B Instruct Q4_K_S

No turn left the plain chat path.

Overall: relevance 1.6, continue 1.5, reply hallucination 0.2, continuation hallucination 0.2.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Search queries | 1.7 | 1.4 | 0.0 | 0.0 |
| Search results | 2.0 | 2.0 | 0.0 | 0.0 |
| Page reading | 1.8 | 2.0 | 0.0 | 0.0 |
| Feature planning | 1.5 | 1.2 | 0.3 | 0.2 |
| Debugging | 1.0 | 0.8 | 0.7 | 1.0 |

The library final was Sunday 10-17 at Kung Oscars väg 11. The story kept Lena Voss, 3 March 2024, Marta, Limhamn, 2 cups, rainwater, and 4 minutes, and left salt out. The last query list dropped Holm & Berg. The six-apartment turn kept all ten features, and the final four dropped the same-week return. Debugging named the rate of 3, the empty total, the negative check, and the loop. The mira change still skipped mira.

## Qwen2.5 3B Instruct Q4_K_M

No turn left the plain chat path.

Overall: relevance 1.4, continue 1.4, reply hallucination 0.4, continuation hallucination 0.4.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Search queries | 1.5 | 1.0 | 0.0 | 0.0 |
| Search results | 2.0 | 2.0 | 0.0 | 0.0 |
| Page reading | 1.7 | 1.8 | 0.0 | 0.0 |
| Feature planning | 1.0 | 1.0 | 1.2 | 1.2 |
| Debugging | 1.0 | 1.2 | 0.8 | 1.0 |

The library final was Sunday 10-17 at Kung Oscars väg 11. The story final kept Lena Voss, 3 March 2024, Marta, Limhamn, 2 cups, rainwater, and 4 minutes. The query list lost Holm & Berg. The fee turn said fees should be handled, and the final features were not one line each. Debugging fixed the empty total, the negative check, and the loop, then the final list denied the negative-hours message and said mira should stay skipped.

## Qwen2.5 1.5B Instruct Q4_K_M

No turn left the plain chat path.

Overall: relevance 1.1, continue 0.9, reply hallucination 0.6, continuation hallucination 0.8.

| Test | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Search queries | 1.3 | 0.6 | 0.0 | 0.6 |
| Search results | 2.0 | 1.8 | 0.0 | 0.0 |
| Page reading | 1.0 | 1.0 | 0.5 | 1.0 |
| Feature planning | 0.7 | 0.6 | 1.0 | 1.2 |
| Debugging | 0.3 | 0.4 | 1.5 | 1.4 |

The library final was Sunday 10:00–17:00 at Kung Oscars väg 11. The story final kept the planted facts, after treating the editor's salt note as part of the story. The glide word disappeared, and Malmö came back on the shop queries. The fee turn invented a fund, and the same-week rule was added as a fifth feature with a cost. The empty-list fix left the total at 1 and called that correct.

## Second-round comparison

Average of these five tests. Relevance and continue are better when higher. Both hallucination scores are worse when higher.

| Model | Relevance | Continue | Reply hallucination | Continuation hallucination |
| --- | --- | --- | --- | --- |
| Gemma 2 9B | 1.7 | 1.6 | 0.1 | 0.0 |
| Qwen2.5 7B | 1.6 | 1.5 | 0.2 | 0.2 |
| Llama 3.1 8B | 1.6 | 1.5 | 0.6 | 0.6 |
| Qwen3 8B | 1.4 | 1.6 | 0.1 | 0.1 |
| Qwen2.5 3B | 1.4 | 1.4 | 0.4 | 0.4 |
| Qwen2.5 1.5B | 1.1 | 0.9 | 0.6 | 0.8 |

No model held feature planning or debugging through the last turn. Qwen2.5 14B and Qwen3 14B were not loaded.
