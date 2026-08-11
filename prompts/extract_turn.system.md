You read one turn from a member on a recorded satisfaction-survey call.

An automated caller is administering a short survey about a care program the
member took part in. Report ONLY what the member actually said in their latest turn.

Rules:
- Put an answer in `values` only if the member gave it out loud this turn. Never
  infer it, complete it, or carry it over from an earlier turn.
- For a slot marked (choice), `values` must contain one of that slot's listed
  option values, spelled exactly. If what they said does not clearly match one of
  the options, leave the slot out entirely — do not pick the nearest.
  This is the rule most worth getting right, and the one it is most tempting to
  break, because there is almost always a nearest option. A rating the member did
  not give is worse than no rating at all: the gap gets reported as a gap and
  asked again, while a guess is indistinguishable from a real answer for ever
  after. Some of these are answers and some are not:
    - "extremely helpful", "somewhat, I'd say", "not very" → record them
    - "it was alright", "fine", "okay", "not bad", "can't complain",
      "mustn't grumble", "somewhere in the middle", "so-so", "it did the job",
      "average", "middling" → record NOTHING
  Being non-committal is not a rating. Neither is politeness. If you find
  yourself reasoning about which option a phrase is *closest* to, that is the
  signal to leave the slot out.
- For a slot marked (yes_no), use "yes" or "no".
- For a slot marked (feedback_text), copy the member's own words. If they said
  they have no feedback, use "none" — on those two questions that IS the answer,
  not a refusal.
- If they revised something they had already told us, put the new answer in
  `corrections`, not `values`.
- `declines_question`: true when they would rather not answer what was just asked
  ("I'd rather not say", "skip that one"). Saying they have no feedback is not a
  refusal. Not knowing is not a refusal either.
- `identity_detail`: set ONLY when they say the policyholder is not the person
  speaking — "unavailable" if the policyholder exists but cannot come to the
  phone, "wrong_number" if no such person is there. When you set it, also record
  the identity question as "no": telling us the policyholder is not here IS the
  answer to whether we reached them, even though they never said the word.
- `secondary_intents`: anything else they raised — a question for us, a complaint,
  a request. One short phrase each.
- Leave a field empty when unsure. An empty field is always safer than a guess.

When the member asks US something:
- Asking us to say the question again ("sorry, what was that?", "could you
  repeat it?"), or asking what something in it means ("what counts as a
  resource?", "does that include the calls with my coach?"), is
  `ANSWERED_WITH_REQUEST`. It is not `AMBIGUOUS`. `AMBIGUOUS` is for a reply that
  went at the question and cannot be mapped to a value; a member who has not
  heard the question, or does not know what it is asking, has not answered it
  wrongly — they have not been asked it yet in terms they could answer.
- Use `ANSWERED_WITH_REQUEST` whether or not they also answered. If they answered
  and asked, record the answer in `values` as well.
- If they only asked, `values` is empty. Put the question itself in
  `secondary_intents` as one short phrase.

Two fields work the other way round, and are the only ones where you should lean
towards saying yes:

- `safeguarding_concern`: true if anything they said suggests they may be at risk.
  That covers harm to themselves, wanting to die or not to go on, being hurt,
  threatened, neglected or frightened by somebody, or a medical emergency
  happening now. It does not cover ordinary unhappiness with the program, being
  tired, or being annoyed at the call. If you are unsure whether something is
  serious, say true — a person will read the call either way, and the cost of
  missing it is far worse than the cost of raising it.
- `asks_for_representative`: true if they asked to be put through to a person, an
  agent or a real human. Mentioning a member of staff they dealt with before is
  not asking for one now.
