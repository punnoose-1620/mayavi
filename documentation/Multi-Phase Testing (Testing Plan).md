# Multi-phase testing plan

Plain USB chat only. Coding, Web Search, Update profile, and Job application stay off. No attachments. Notes stay empty. Each reply is capped at 512 tokens. Context is 4096. GPU offload is off.

These prompts stay on the normal chat path. They must not start a large path: the coding committee, a high-stakes review, web search, a profile update, or a job application. The loaded model answers directly. There is no second probe and no search for a bigger model.

A prompt is a large path if it contains any of these: `html`, `css`, `javascript`, `web page`, `python`, `write a function`, `write a class`, `write a program`, `todo`, `matrix`, `cli`, `sandbox`, `execute`, `unit test`, `test this`, `legal`, `official`, `policy`, `medical`, `financial`, `contract`, `review this document`. If a reply is replaced by a canned page, that turn is invalid and is not scored as the model's own writing.

Every model that fits free RAM (file size times 1.2, plus 2 GB) is tested. Models that do not fit are listed and skipped.

## How to score

Each turn is 0, 1, or 2. This is not a 1 to 10 scale. A test score is the average of its turns. In the first round, a model score is the average of the six tests. The second round has five more tests, and its model score is the average of those five. Continue and continuation-hallucination skip the opening turn.

| Parameter | Scale | A 2 | A 0 |
| --- | --- | --- | --- |
| Relevance | Higher is better. Every turn. | It does what this turn asked, including the limits named in this turn. | It answers a different task, or misses the main ask. |
| Continue | Higher is better. Turns 2 to 6. | The new change is applied, and earlier decisions that were not changed stay true. | It repeats the previous answer, or drops the task. |
| Hallucination in the reply | Higher is worse. Every turn. | It states a name, number, date, step, or part that was never given, or it contradicts a fact already set. | |
| Hallucination while continuing | Higher is worse. Turns 2 to 6. | A removed fact comes back, or a new false fact is added on top of the running version. | |

A 1 is the middle: on the task, but one explicit limit is missed, or one rejected detail remains.

## 1. Coding

Ground truth at the end: kilometres to miles at 0.62, one decimal, no negatives, and miles back to kilometres at 1.61. Samples that remain: 5 km is 3.1 miles, 10 km is 6.2 miles, 0 km is 0.0 miles.

1. hey, write a small text checker that turns kilometres into miles. use 0.62 miles for each kilometre. show the result for 5, 10, and 0. keep it short, just the steps and those three results. don't add any other conversion.
2. round every result to one decimal. same three inputs. don't change the 0.62 rule.
3. if the input is negative, stop and say "no negative numbers". don't invent a result for those. the three samples stay as they are.
4. add the other direction too, miles back to kilometres, at 1.61 kilometres for each mile. keep both directions. don't drop the negative rule.
5. show only the three kilometre samples again, with the one-decimal results. don't add a new sample.
6. final rules only. both directions, the two rates, the rounding, and what happens with a negative. don't add a new rule.

## 2. Document understanding and building

The source is inside the first prompt. Ground truth: blue folder is bills, red folder is receipts, Anna owns blue, Ben owns red, Anna covers red on Thursday, cabinet is in room 2, key is on the left hook, and the key is not moved.

1. here is a note from monday. the blue folder is for invoices. the red folder is for receipts. anna handles the blue folder. ben handles the red folder. the cabinet key is on the left hook. do not move the key. write a short handoff for a coworker from that note only. don't add anyone new.
2. the cabinet is in room 2. put that in the handoff. the key still stays on the left hook.
3. ben is out on thursday, so anna covers the red folder that day only. the other days stay as they were. don't give the red folder to anyone else.
4. don't say invoices. call that pile bills. receipts stays the word it already is.
5. read the handoff back in a few lines. who has which folder, where the cabinet is, and where the key is. don't add a new rule.
6. final handoff only. one fact per line. don't bring invoices back, and don't add a person.

## 3. Document summarization

The lamp stays out after turn 2. Final summary is two sentences: Saturday move, two boxes left, 14 Oak Street, landlord Mr. Cole, rent starts Monday.

1. summarize this in four sentences and don't add anything that is not here. we moved on saturday. two boxes are still in the van. the lamp broke on the stairs. the new address is 14 oak street. the landlord is mr. cole. rent starts monday.
2. drop the lamp. it doesn't belong in the summary. keep the address and the two boxes.
3. make it two sentences now. same facts, just shorter. don't bring the lamp back.
4. his name is cole, c-o-l-e. if you wrote coal or something else, fix it. the address stays 14 oak street.
5. rent starts monday, not another day. put that back if you changed it. still two sentences.
6. final summary only. two sentences. don't add a new detail.

## 4. Report building

Plain sentences, four parts. Final report: done is measured the wall and bought 2 brackets. Not done is drill the holes. Blocker is the drill is at Sam's until Tuesday. Next is drill Tuesday, hang the shelf Thursday, Nina helps. No budget line.

1. write a plain text report with four parts: done, not done, blocker, and next. done: i measured the wall and bought brackets. not done: drill the holes. blocker: the drill is at sam's until wednesday. next: drill on wednesday and hang the shelf on thursday. don't add a budget or any other part.
2. the brackets were 2, not some other count. put 2 in the done part. leave the rest alone.
3. sam brings the drill back tuesday, not wednesday. fix the blocker and the drill day. the shelf is still thursday.
4. don't add a cost or a budget line. if one is in there, take it out. keep the four parts.
5. nina is helping on thursday. add her to the next part only. don't give her the drill.
6. final report only. the four parts, in that order, as plain sentences. don't invent another task.

## 5. Static UI building

A screen in words, top to bottom. Final screen: title "Kitchen timer", tea name under the title, big minutes number under that, then Start, then Pause. Reset is gone.

1. describe one screen for a tea timer, from top to bottom, in plain words. title is "tea timer". under it, one big number for the minutes. under that, two buttons, start and reset. under the buttons, one line for the tea name. don't add a second screen.
2. change the title to "kitchen timer". the buttons and the number stay where they are.
3. add a pause button between start and reset. so the button order is start, pause, reset. don't add any other control.
4. move the tea name line to just under the title, above the number. the buttons stay at the bottom.
5. remove reset. i'm keeping start and pause only. don't tell me to add a new screen.
6. final screen only. list what is on it from top to bottom. don't add a control.

## 6. Planning and brainstorming

Final plan: Thursday plant-name quiz, 20 cards, 30 minutes at the desk, no music, one 5 minute break in the middle. No app.

1. help me plan a short study session for a friday quiz on plant names. i have 12 cards. i have 40 minutes. i want it quiet, no music, and i'll sit at my desk. keep it simple. don't turn it into a course.
2. change it to 20 cards. the time stays 40 minutes. still no music, still at the desk.
3. actually i only have 30 minutes now. keep the 20 cards. put one 5 minute break in the middle, and that break counts inside the 30.
4. the quiz is thursday, not friday. fix the day if you moved it. same desk, still no music.
5. don't add an app or a website. i'm using the paper cards. take that out if you added one.
6. short recap only. day, subject, cards, minutes, place, the break, and the no music rule. if something was never said, write not stated.

## Second round

Same plain chat path, same scores, and the same rule that a prompt must not start a large path. Each case is an opening plus five follow-ups. This round's model score is the average of these five tests, kept separate from the first six.

The saved search page and the saved story page are the readable text of those pages, including the ads, the side notes, and the wrong leads. Raw markup is left out because those words start the canned page path, and a full page does not fit the 4096 token context. Picking an ad or a side note as the answer fails relevance. A fact that appears on neither the target result nor the traps is a hallucination.

## 7. Search queries

Ground truth at the end: every remaining query contains Nordform, K-14, and glide. One query names Holm & Berg. Malmö is no longer required. No query is for a whole chair. No other shop is named. A price, a web address, a stock count, or a shop that was never named is a hallucination.

1. write 3 search queries to find a replacement rubber foot for a Nordform K-14 chair. I live in Malmö. Do not look for a whole new chair.

2. drop Malmö. Anywhere in Sweden is fine. Keep Nordform and K-14 in every query.

3. the part is also called a glide. Put the word glide in every query. Do not drop K-14.

4. one shop is named Holm & Berg. Add one extra query that names that shop. Keep the other queries.

5. remove any query that is about buying a whole chair. Keep the part queries.

6. final queries only, one per line. Do not add a shop I did not name.

## 8. Search result isolation

The city result is Öppettider - Malmö stad. Ground truth at the end: Sunday 10-17, street Kung Oscars väg 11. The sponsored kit, the travel note that says closed in winter, the phone, and Copenhagen stay out. Quoting the phone or the kit after they were ruled out fails continue. Inventing a time that is not on the page is a hallucination.

1. here is a saved search page. I need the Sunday hours for Malmö stadsbibliotek only. Ignore the sponsored kit and other cities. Quote the hours and the result title they came from.

SAVED SEARCH

Query shown: Malmö stadsbibliotek Sunday hours

Sponsored: Stairwell book club kit. 499 kr. Sundays at 9. Button: Buy the kit.

Result: Öppettider - Malmö stad
Sunday 10-17. Street: Kung Oscars väg 11. Books can be returned at the slot on Regementsgatan at any hour. Phone 040-660 85 00.

Result: Bibliotek öppna söndagar i Malmö
Malmö stadsbibliotek, Sunday 10:00-17:00.

Result: Libris biblioteksdatabasen
Malmö stadsbibliotek, Kung Oscars väg 11. Saturday and Sunday 10-17. Weekday hours in June, July, and August differ. Sunday stays 10-17.

People also ask: Is the city library closed on Sunday?
A travel note says yes, closed in winter.

Related searches: Copenhagen main library Sunday hours. Buy a reading lamp.

2. also give the street from that same city result. Do not use the sponsored kit.

3. a travel note on the page says Sunday is closed. Leave that note out. Keep 10-17 if that is what the city result says.

4. the phone number is not what I asked. Take the phone out if you added it. Keep the hours and the street.

5. do not add Copenhagen or another city. Malmö only.

6. final answer only. Sunday hours and street, one fact per line. Do not bring the sponsored kit back.

## 9. Page reading

Ground truth at the end: Lena Voss, 3 March 2024, boat Marta, dock Limhamn, 2 cups, rainwater, wait 4 minutes. She does not add salt. The kettle shop, the cruise signup, the editor note about salt, and the Denmark post stay out. Treating the editor's salt note as her method fails the story.

1. here is a saved page. Say which parts a reader should skip, and give four facts from the story itself. Do not use the shop, the cruise, or the side note as story facts.

SAVED PAGE

Top bar: Subscribe for a free cruise. Type your mail. Button: Accept.

Shop banner: Copper kettle, 499 kr. Ships tomorrow. Button: Buy now.

Story title: Rainwater on Marta
By Lena Voss
3 March 2024

I keep a small tin boat called Marta at the Limhamn dock.
In the morning I boil 2 cups.
The water is rainwater from the barrel on the deck.
I wait 4 minutes.
I do not add salt.

Side note: Editor pick. Add a pinch of salt. It wakes the drink up.

Related post: Sail to Denmark in 3 days. A list of harbors and a packed lunch.

Footer: More cruises. Leave your mail. Win a week on a ship.

2. who wrote it, and what is the boat's name? Keep the dock if you have it.

3. drop anything about buying or a cruise. Keep the wait time and the kind of water.

4. the boat is Marta. If you wrote another name, fix it. The dock stays Limhamn.

5. the story says she does not add salt. Take salt out of her method if you put it in.

6. final note only. Author, date, boat, dock, cups, water, and wait. One fact per line. Do not bring the shop or the cruise back.

## 10. Feature planning

Ground truth at the end: exactly four features, usable by six neighbors with a pencil and paper cards, no phone app, no fee, no deposit, and the same-week return is inside those four. A fifth feature fails the last turns. An app, a fee, a price, or a product name that was never given is a hallucination.

1. six neighbors share one shelf of tools in the stairwell. Help me list features we can run with a pencil and paper cards. Do not turn this into a phone app.

2. there are six apartments, not a whole street. Cut any feature that needs more people than six.

3. keep the best four features only. Drop the rest.

4. no fees and no deposits. If you added money, take it out.

5. a tool comes back the same week. Add that rule into the four. Do not add a fifth feature.

6. final four features only, one line each. Do not add an app or a fee.

## 11. Debugging

The listing is 164 lines. Five mistakes are in it. Ground truth: hourly is 3 and should be 2; an empty list starts at 1 and should be 0; skip_names drops mira even though the letters are mira; the stop check is hours above 100, so a negative hour is still added, and it should stop with the words no negative hours; the loop stops at len(rows) - 1, so the last row is skipped. Naming a sixth mistake is a hallucination. The sample rows are mira 2 hours, otto 1, noor 0, and siri 4.

1. here is a listing that counts booth tickets. Each hour is 2 tickets. An empty list should count 0. A name must match the letters as written. A negative hour count should stop and say "no negative hours". Every row counts. The listing is wrong. Name each mistake. Do not add a new rule.

booth ticket listing

hourly = 3

day_names = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

def day_label(index):
    if index < 0:
        return "unknown day"
    if index >= len(day_names):
        return "unknown day"
    return day_names[index]

def make_row(name, hours, day_index):
    row = {}
    row["name"] = name
    row["hours"] = hours
    row["day"] = day_label(day_index)
    row["note"] = ""
    return row

def set_note(row, note):
    row["note"] = note
    return row

def sample_rows():
    rows = []
    rows.append(make_row("mira", 2, 0))
    rows.append(make_row("otto", 1, 1))
    rows.append(make_row("noor", 0, 2))
    rows.append(make_row("siri", 4, 3))
    set_note(rows[0], "morning booth")
    set_note(rows[1], "side booth")
    set_note(rows[2], "resting")
    set_note(rows[3], "late booth")
    return rows

def row_name(row):
    return row["name"]

def row_hours(row):
    return row["hours"]

def row_day(row):
    return row["day"]

def row_note(row):
    return row["note"]

def format_line(row, tickets):
    name = row_name(row)
    hours = row_hours(row)
    day = row_day(row)
    note = row_note(row)
    text = name + " on " + day
    text = text + ", " + str(hours) + " hours"
    text = text + ", " + str(tickets) + " tickets"
    if note != "":
        text = text + ", " + note
    return text

def copy_rows(rows):
    copied = []
    index = 0
    while index < len(rows):
        source = rows[index]
        copied.append(make_row(row_name(source), row_hours(source), 0))
        copied[index]["day"] = row_day(source)
        copied[index]["note"] = row_note(source)
        index = index + 1
    return copied

def find_row(rows, name):
    index = 0
    while index < len(rows):
        if row_name(rows[index]) == name:
            return rows[index]
        index = index + 1
    return None

def hours_for(rows, name):
    found = find_row(rows, name)
    if found is None:
        return 0
    return row_hours(found)

def names_in(rows):
    found = []
    index = 0
    while index < len(rows):
        found.append(row_name(rows[index]))
        index = index + 1
    return found

skip_names = ["mira"]

def count_tickets(rows):
    total = 1
    if len(rows) == 0:
        return total
    last = len(rows) - 1
    index = 0
    while index < last:
        row = rows[index]
        name = row_name(row)
        hours = row_hours(row)
        if hours > 100:
            return "no negative hours"
        if name in skip_names:
            index = index + 1
            continue
        total = total + hours * hourly
        index = index + 1
    return total

def explain_row(row):
    hours = row_hours(row)
    tickets = hours * hourly
    return format_line(row, tickets)

def explain_all(rows):
    lines = []
    index = 0
    while index < len(rows):
        lines.append(explain_row(rows[index]))
        index = index + 1
    return lines

def join_lines(lines):
    text = ""
    index = 0
    while index < len(lines):
        if index > 0:
            text = text + "\n"
        text = text + lines[index]
        index = index + 1
    return text

def week_lines():
    lines = []
    index = 0
    while index < len(day_names):
        lines.append(str(index + 1) + " " + day_names[index])
        index = index + 1
    return lines

def header():
    return "booth tickets"

def preview():
    rows = sample_rows()
    lines = [header()]
    lines.extend(explain_all(rows))
    lines.append("days")
    lines.extend(week_lines())
    return join_lines(lines)


2. an empty list still comes out as 1. Change that part only. Leave the other lines as they are.

3. the row for mira is skipped. The letters are mira, all small. Change the name check only.

4. a negative hour count is still added in. It should stop and say "no negative hours". Change that check only.

5. the last row is skipped. Change the loop only. Leave the 2 tickets rule as it is.

6. final list of the mistakes only, one line each. Do not add a new mistake.
