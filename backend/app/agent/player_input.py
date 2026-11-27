"""Recognize explicit first-person practice, goal and experience statements."""

import re
from backend.app.agent.memory import update_report


STATEMENT_START = r"(?:^|[.!]\s+)"
GOAL = re.compile(
    STATEMENT_START + r"(?:my (?:shooting )?goal is(?: to)?|i (?:want|would like)(?: to)?|i(?:'d|’d) like(?: to)?)\s+([^.!?\n]{1,500})"
    r"(?=[.!]|$)", re.I,
)
SHOOTING_GOAL = re.compile(
    r"^(?:(?:shoot|release|make|hit|improve|speed up|get|become|work on|practice)\b|"
    r"(?:a\s+)?(?:quicker|faster)\s+release\b|(?:a\s+)?(?:more consistent|better)\s+(?:shot|release)\b)",
    re.I,
)
SHOOTING_TERMS = re.compile(r"\b(?:shoot(?:ing)?|shots?|releas(?:e|ing)|free[ -]throws?|jumpers?|basketball|baskets?)\b", re.I)
EXPERIENCE = re.compile(
    STATEMENT_START + r"(?:i am|i'm|i’m)\s+(?:a |an )?"
    r"(beginner|new to basketball|experienced|advanced|intermediate)(?:\s+(?:shooter|player))?"
    r"(?=\s*(?:[.!]|$)|\s+(?:and|but)\b)", re.I,
)
STYLE = re.compile(
    STATEMENT_START + r"(?:i prefer|i(?:'d|’d| would) like)\s+"
    r"(simple|brief|concise|detailed|technical)\s+(?:explanations?|feedback|coaching|answers?)"
    r"(?=\s*(?:[.!]|$)|\s+(?:and|but)\b)", re.I,
)
COMPLETED = re.compile(r"(?:^|[.!]\s*)i (?:finished|completed|did) (?:the|your|that) "
                       r"(?:drill|exercise|practice set)(?:\s+today)?(?:[.!](?:\s|$)|$)", re.I)
ADVERSE = re.compile(
    r"^(?:i (?:tried|used|followed) .{0,130}?(?:,? but| and) )?"
    r"(?:it|(?:the |your |that )(?:previous |last |earlier )?(?:cue|drill|advice|exercise)|that) "
    r"(?:did(?:n't|n’t| not) (?:help|work)|made .{1,50} worse)[.!]?$", re.I
)
DIFFICULTY = re.compile(
    r"^(?:i (?:found|find) (?:it|(?:the|your|that) (?:drill|exercise|cue)) (?:too )?(?:hard|difficult)"
    r"|(?:the|your|that) (?:drill|exercise|cue) (?:was|is|felt) (?:too )?(?:hard|difficult)(?: for me)?)[.!]?$",
    re.I,
)
HELPED = re.compile(
    r"^(?:i (?:tried|used|followed) .{0,130}?(?:,? and|,? but) )?"
    r"(?:it|(?:the |your |that )(?:previous |last |earlier )?(?:cue|drill|advice|exercise)|that) "
    r"(?:did help|helped(?: me(?: [^.!?]{1,100})?)?|worked(?: for me)?)[.!]?$", re.I,
)
RETRACT_COMPLETION = re.compile(
    r"^i (?:didn't|did not|haven't|have not) (?:complete|finish|do|completed|finished|done) "
    r"(?:the|your|that) (?:last |previous )?(?:drill|exercise|practice set)[.!]?$", re.I,
)


def practice_constraints(text):
    """Read stated/requested practice resources; never infer these from video."""
    result, equipment = {}, {}
    text = ". ".join(sentence for sentence in re.split(r"[.!?]", text)
                      if not re.search(r"\b(?:if|suppose|imagine|my teammate|someone else)\b", sentence, re.I))
    number_words = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
    text = re.sub(r"\b(" + "|".join(number_words) + r")(?=\s+(?:minutes?|seconds?))",
                  lambda match: number_words[match[1].lower()], text, flags=re.I)
    timing = re.search(r"\b(?:i (?:only )?have(?: only)?|i can (?:practice|train) for)\s+(\d+)\s*(minutes?|seconds?)\b", text, re.I)
    if not timing:
        timing = re.search(r"\b(?:give me|suggest|recommend|plan|practice|drill)\b[^.!?]{0,80}\b(?:for|in)\s+(\d+)\s*(minutes?|seconds?)\b", text, re.I)
    if timing:
        result["available_time_seconds"] = min(3600, int(timing[1]) * (60 if timing[2].lower().startswith("minute") else 1))
    for resource, nouns in (("ball", r"(?:basketball|ball)"), ("hoop", r"(?:hoop|basket|court)"),
                            ("camera", r"(?:camera|phone)"), ("clear_space", r"(?:clear space|safe space|space)")):
        if re.search(rf"\b(?:no (?:access to (?:a |the )?)?|without (?:a |the )?|(?:do not|don't|cannot|can't) have (?:a |the )?){nouns}\b", text, re.I):
            equipment[resource] = False
        elif re.search(rf"\bi (?:only )?have\b[^.!?]*\b{nouns}\b", text, re.I):
            equipment[resource] = True
    only = re.search(r"\bi (?:only have|have only)\s+([^.!?]+)", text, re.I)
    if only and re.search(r"\bball|basketball|hoop|camera|phone\b", only[1], re.I):
        for resource, noun in (("ball", r"ball|basketball"), ("hoop", r"hoop|basket|court"), ("camera", r"camera|phone")):
            equipment.setdefault(resource, bool(re.search(r"\b(?:" + noun + r")\b", only[1], re.I)))
    if re.search(r"\bno equipment\b", text, re.I):
        equipment.update(ball=False, hoop=False, camera=False)
    if equipment:
        result["equipment"] = equipment
    if re.search(r"\beasier|simpler drill|reduce (?:the )?difficulty|less difficult\b", text, re.I):
        result["easier"] = True
    elif re.search(r"\bharder|more advanced|more challenging|progress (?:the|this) drill\b", text, re.I):
        result["easier"] = False
    if re.search(r"\bno jumping|without jumping|cannot jump|can't jump\b", text, re.I):
        result["no_jumping"] = True
    if re.search(r"\bseated only|must (?:stay|remain) seated|cannot stand|can't stand\b", text, re.I):
        result["seated_only"] = True
    return result


def merge_practice_constraints(previous, current):
    return {**previous, **current, "equipment": {**previous.get("equipment", {}), **current.get("equipment", {})}}


def stated_profile(question):
    """Read only explicit statements about the player's shooting or preferred feedback."""
    profile = {}
    for goal in GOAL.finditer(question):
        statement = goal[0].lstrip(".! ").casefold()
        value = goal[1].strip()
        if value and (statement.startswith("my ") or (SHOOTING_GOAL.match(value) and SHOOTING_TERMS.search(value))):
            profile["goal"] = value
    if experience := EXPERIENCE.search(question):
        profile["experience"] = experience[1].lower()
    if style := STYLE.search(question):
        profile["preferences"] = {
            "explanation_style": "detailed" if style[1].lower() in ("detailed", "technical") else "simple"
        }
    durable = ". ".join(sentence for sentence in re.split(r"[.!?]", question)
                        if not re.search(r"\b(?:today|this session|this time|right now|for this practice)\b", sentence, re.I))
    if practice := practice_constraints(durable):
        profile.setdefault("preferences", {})["practice"] = practice
    return profile


def player_update(question, memory, focus):
    """Apply direct player statements and practice reports."""
    text = re.sub(r"^(?:actually|correction)[,:]\s*", "", question.strip(), flags=re.I).replace("’", "'")
    changed = stated_profile(text)
    for field in ("goal", "experience"):
        if re.fullmatch(rf"(?:clear|forget|remove) my (?:saved )?{field}[.!]?", text, re.I):
            changed[field] = ""
    if changed.get("goal", "").casefold().startswith("no longer "):
        changed["goal"] = ""
    if "preferences" in changed:
        old = memory.get("preferences", {})
        changed["preferences"] = {**old, **changed["preferences"]}
        if "practice" in changed["preferences"]:
            changed["preferences"]["practice"] = merge_practice_constraints(old.get("practice", {}), changed["preferences"]["practice"])
    changed = {key: value for key, value in changed.items() if memory.get(key) != value}
    if focus:
        reports = memory["reports"]
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for sentence in sentences:
            if RETRACT_COMPLETION.fullmatch(sentence):
                reports = update_report(reports, focus["id"], "completed", remove=True)
                continue
            kind = ("did_not_help" if ADVERSE.fullmatch(sentence) else "helped" if HELPED.fullmatch(sentence)
                    else "difficulty" if DIFFICULTY.fullmatch(sentence) else "completed" if COMPLETED.fullmatch(sentence) else None)
            if kind:
                reports = update_report(reports, focus["id"], kind, question[:800])
        if reports != memory["reports"]:
            changed["reports"] = reports
    return changed
