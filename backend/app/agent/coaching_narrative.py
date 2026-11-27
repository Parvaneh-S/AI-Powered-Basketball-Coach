"""Ground the practice plan and verify optional model-authored coaching language."""

import json
import re

from pydantic import ValidationError

from backend.app.agent.evidence import MEASUREMENTS, number
from backend.app.agent.knowledge import KNOWLEDGE, supporting_context
from backend.app.agent.response import CoachAnswer, CoachingResponse, Decision, Practice
from backend.app.agent.resources import named_resources

PHASE_LABELS = {
    "knee_dip": "deepest knee bend", "knee_max": "straightest knee position",
    "elbow_min": "most bent elbow position", "elbow_max": "peak elbow extension",
    "post_release_extension": "peak early follow-through extension",
    "preparation": "start of preparation", "release": "estimated release",
}
MOVEMENT = {
    "min_knee_angle": ("a slightly straighter knee at the bottom of your dip",
                       "a slightly deeper, comfortable knee bend before you lift the ball"),
    "knee_angle_range": ("a slightly larger knee bend-to-rise movement",
                         "a smaller knee bend-to-rise movement"),
    "release_elbow_angle": ("a slightly straighter shooting arm as the ball leaves your hand",
                            "a slightly softer bend in your shooting arm as the ball leaves your hand"),
    "max_elbow_angle": ("letting your shooting arm straighten a little farther",
                        "letting your shooting elbow stay a little softer as you finish"),
    "elbow_angle_range": ("a slightly larger bend-to-extension movement in your shooting arm",
                          "a slightly smaller bend-to-extension movement in your shooting arm"),
    "elbow_extension_after_release": ("letting your arm straighten a little farther after release",
                                      "finishing with a little less extra straightening after release"),
    "shooting_motion_ms": ("giving yourself a little more time to lift and release the ball",
                           "flowing into the release with a slightly quicker, smooth lift"),
}


class NarrativeValidationError(ValueError):
    """Safe actionable feedback, never raw provider text or player content."""

    def __init__(self, message, *, allowed_values=None, evidence_ids=None, kind="substantive"):
        super().__init__(message)
        self.field = message.partition(":")[0]
        self.allowed_values = allowed_values
        self.evidence_ids = evidence_ids
        self.kind = kind


FACT_TOKEN = re.compile(r"\{\{fact:(\d+)\}\}")
# Units that count shooting repetitions in a proposed dose.
SHOT_UNITS = ("shot", "free", "jump", "attempt")
# "2 sets of 10" names the shots per set without repeating the unit.
SETS_OF = re.compile(r"\b(\d+\s+sets?\s+of\s+\d+)\b(?!\s*(?:shots?|free[- ]throws?|jump[- ]shots?|attempts?|reps?|"
                     r"repetitions?|seconds?|minutes?)\b)|"
                     r"\b((?:shoot|take|try)\s+\d+)\b(?!\s*(?:sets?|shots?|free[- ]throws?|jump[- ]shots?|attempts?|reps?|"
                     r"repetitions?|seconds?|minutes?|percent|%|degrees?)\b)", re.I)
def with_shot_units(text):
    """Make an implied shot count explicit ("2 sets of 10", "shoot 5 from the line")."""
    return SETS_OF.sub(lambda match: (match[1] or match[2]) + " shots", text)


SINGLE_CLIP_SCOPE = re.compile(
    r"\b(?:(?:this|that|it)\s+(?:is|was)\s+(?:just\s+|only\s+)?(?:one|a single)|(?:just|only)\s+one|"
    r"(?:from|in|on|after)\s+(?:just\s+|only\s+)?(?:one|a single))\s+"
    r"(?:shot|attempt|clip|miss|make)\b|\bone\s+(?:shot|attempt|clip|miss|make)\s+(?:alone\s+)?"
    r"(?:can[’']?t|cannot|doesn[’']?t|won[’']?t|isn[’']?t|is not|does not)\b", re.I)
# A causal word is acceptable when the sentence negates or hedges it ("I wouldn't conclude X caused it").
NEGATED_OR_HEDGED = re.compile(r"\b(?:not|no|never|neither|nor|cannot|\w+n't|may|might|could|possibl[ey]|"
                               r"hypothes[ie]s|whether|unclear|unknown|"
                               r"without (?:assuming|claiming|concluding|proving|knowing|establishing))\b", re.I)
DOSE = re.compile(
    r"\b(\d+)\s+(?:(?:comfortable|easy|gentle|controlled|close-range|slow|unhurried)\s+)?"
    r"(shots?|free[- ]throws?|jump[- ]shots?|attempts?|reps?|repetitions?|sets?|seconds?|minutes?)\b", re.I,
)
SMALL_NUMBERS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
WORD_VALUES = dict(zip(SMALL_NUMBERS, range(20)))
for tens_index, tens in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2):
    WORD_VALUES[tens] = tens_index * 10
    WORD_VALUES.update({f"{tens} {word}": tens_index * 10 + index for index, word in enumerate(SMALL_NUMBERS[1:10], 1)})
WORD_VALUES.update({"a hundred": 100, "a thousand": 1000})
WORD_VALUES.update({f"{word} hundred": 100 * index for index, word in enumerate(SMALL_NUMBERS[1:10], 1)})
WORD_VALUES.update({f"{word} thousand": 1000 * index for index, word in enumerate(SMALL_NUMBERS[1:10], 1)})
WORD_NUMBER = re.compile(r"\b(?:" + "|".join(
    word.replace(" ", "[- ]") for word in sorted(WORD_VALUES, key=len, reverse=True)) + r")\b", re.I)
NO_EXERCISE = re.compile(
    r"\bno (?:drills?|exercises?)\b|\b(?:don't|do not) (?:give|suggest|recommend)\b[^.!?]*\b(?:drills?|exercises?)\b",
    re.I,
)
EXTERNAL_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\n]+\)|<?(?:https?://|www\.)[^\s<>]+>?",
                           re.I)
MEDIA_RECOMMENDATION = re.compile(
    r"\b(?:recommend|suggest|check out|watch|look up|read|try)\b[^!?]*\b"
    r"(?:video|tutorial|article|channel|YouTube|Vimeo|TikTok)\b|"
    r"\b(?:watch|read|check out|look up)\s+[\"“]", re.I,
)
VISUAL_FINISH_CLAIM = re.compile(
    r"\b(?:follow[ -]through|post.release)\b[^.!?]*\b(?:shows?|see|visible)\b"
    r"[^.!?]*\b(?:arm|elbow)\b[^.!?]*\b(?:extend\w*|straighten\w*|locks? out)\b", re.I,
)
VISUAL_DIRECTION = re.compile(
    r"\b(?:watch|see|look at)\s+(?:how\s+)?(?:your|the)\s+(?:shooting(?:-side)?\s+)?"
    r"(arm|elbow|knee)\s+(straighten\w*|bend\w*)\b", re.I,
)
VISUAL_COMPARISON_DIRECTION = re.compile(
    r"\b(?:your|the)\s+(?:shooting(?:-side)?\s+)?(arm|elbow|knee)\s+(straighten\w*|bend\w*)"
    r"\s+between\b[^.!?]*\bframes?\b", re.I,
)


def quantified_words(text):
    """Normalize written numbers only in phrases that describe a count or measurement."""
    def normalize(match):
        before, after = text[:match.start()], text[match.end():]
        if (re.search(r"\b(?:made|missed|took|recorded|attempted|out of|of)\s+$", before, re.I)
                and (re.search(r"\b(?:made|missed|took|recorded|attempted)\b[^.!?]*$", before, re.I)
                     or re.match(r"\s+(?:shots?|attempts?)\b", after, re.I))
                or re.match(r"\s+(?:(?:comfortable|easy|gentle|controlled|close-range|slow|unhurried|"
                            r"known|labelled|labeled)\s+)?(?:makes?|misses?|shots?|attempts?|"
                            r"reps?|repetitions?|sets?|seconds?|minutes?|degrees?|milliseconds?|percent(?:age points?)?)\b",
                            after, re.I)):
            return str(WORD_VALUES[match[0].casefold().replace("-", " ")])
        return match[0]
    return WORD_NUMBER.sub(normalize, text)
class AnswerValidationError(ValueError):
    def __init__(self, issues):
        self.details = [dict(field=issue.field, reason=str(issue), kind=issue.kind,
                             allowed_values=issue.allowed_values, evidence_ids=issue.evidence_ids or [])
                        for issue in issues]
        super().__init__(" ".join(str(issue) for issue in issues))


def parse_answer(raw, discarded):
    """Parse the message first. A malformed optional field cannot erase the reply."""
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return CoachAnswer.model_validate(payload)
    answer = CoachAnswer.model_validate({"message": payload.get("message")})
    dose = (payload.get("practice") or {}).get("dose") if isinstance(payload.get("practice"), dict) else None
    if isinstance(dose, dict) and type(dose.get("sets")) is int and type(dose.get("repetitions")) is int and not (
        type(dose.get("duration_seconds")) is int and dose["duration_seconds"] >= 1
    ):
        # A missing time allowance is filled conservatively; validate_practice still checks it fits.
        dose["duration_seconds"] = min(600, max(1, dose["sets"] * dose["repetitions"] * 15))
    for field in CoachAnswer.model_fields.keys() - {"message"}:
        if field not in payload:
            continue
        try:
            component = CoachAnswer.model_validate({"message": answer.message, field: payload[field]})
        except ValidationError:
            discarded.append({"field": field, "reason": "Invalid optional field shape"})
        else:
            setattr(answer, field, getattr(component, field))
    return answer


def validate_text(text, field, ctx):
    """Return all independently actionable local errors and the unbound numeric text."""
    issues = []
    if not text.strip():
        issues.append(NarrativeValidationError(f"{field}: provide readable coaching text."))
    if re.search(r"[<>\x00-\x08\x0b-\x1f]|https?://|www\.|\[[^\]]*\]\(", text, re.I):
        issues.append(NarrativeValidationError(f"{field}: use plain coaching text without links or markup."))
    # Literal doses are instructions, not fabricated player measurements.
    scrubbed = FACT_TOKEN.sub("", text).replace("2D", "").replace("3D", "")
    # "This is one shot, so it can't show..." scopes the selected clip; it is not a counted claim.
    scrubbed = quantified_words(SINGLE_CLIP_SCOPE.sub("this clip", scrubbed))
    scrubbed = re.sub(r"(\d)-of-(\d)", r"\1 of \2", scrubbed)  # "7-of-10" is a count, not minus ten
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", scrubbed):
        if re.search(r"\b(?:push|play|shoot|train|practice) through (?:the |your )?pain\b", sentence, re.I) and not re.search(
            r"\b(?:do not|don't|never|avoid)\b[^.!?]*\bthrough\b", sentence, re.I,
        ):
            issues.append(NarrativeValidationError(f"{field}: do not advise training through pain."))
        if re.search(r"\byou missed\b[^.!?]*\bbecause\b", sentence, re.I) and not re.search(
            r"\b(?:cannot|can't|don't|not)\b[^.!?]*\byou missed\b", sentence, re.I,
        ):
            issues.append(NarrativeValidationError(f"{field}: recorded outcomes and associations cannot establish why shots missed."))
        causal_text = re.sub(
            r"\b(?:stop|pause|avoid)\b[^.!?]*?\b(?:if|when)\b[^.!?]*?\bcauses?\s+(?:you\s+)?(?:pain|discomfort)\b",
            "", sentence, flags=re.I,
        )
        if re.search(r"\b(caused?|causes|guarantee\w*|will (?:fix|improve|prevent)|reason you miss\w*)\b", causal_text, re.I):
            if not NEGATED_OR_HEDGED.search(causal_text.replace("’", "'")):
                issues.append(NarrativeValidationError(f"{field}: replace an unsupported causal claim or promise with an evidence-grounded observation or experiment."))
        if re.search(r"\byour wrist (?:collapsed|snapped|flicked|bent)\b", sentence, re.I):
            issues.append(NarrativeValidationError(f"{field}: wrist motion is not verified by the shooting measurements."))
        if re.search(r"\b(?:you (?:used|put) too much (?:power|force)|your (?:ball )?"
                     r"(?:launch angle|release speed|power) (?:was|is) too\b)", sentence, re.I) and not re.search(
            r"\b(?:if|whether|can't|cannot|not)\b", sentence, re.I,
        ):
            issues.append(NarrativeValidationError(f"{field}: the evidence does not verify launch angle, speed or power."))
        if re.search(r"\bto (?:rehabilitate|treat) your\b[^.!?]*\b(?:shoulder|injury|pain)\b",
                     sentence, re.I) and not re.search(r"\b(?:not|don't|avoid)\b", sentence, re.I):
            issues.append(NarrativeValidationError(f"{field}: do not prescribe treatment or aggravating practice."))
        if (ctx.feedback and ctx.feedback["kind"] == "did_not_help"
                and re.search(r"\b(?:continue|repeat|keep doing)\s+(?:the same|that|your previous)\s+(?:drill|cue|exercise)\b", sentence, re.I)
                and not re.search(r"\b(?:not|don't|avoid|instead of)\b", sentence, re.I)):
            issues.append(NarrativeValidationError(f"{field}: reconsider the exercise the player reported did not help."))
        if (field == "message" and (ctx.review_requested or ctx.progress_records)
                and re.search(r"\b(?:you(?:'ve| have)? (?:have )?improved|your (?:shooting|form) (?:is more consistent|"
                              r"has improved|improved)|the (?:cue|drill|adjustment) (?:helped|worked))\b", sentence, re.I)
                and not re.search(r"\b(?:reported|said|felt|can't|cannot|whether|if|may|might|not)\b", sentence, re.I)):
            consistent = bool(re.search(r"\bmore consistent\b", sentence, re.I))
            scoped = bool(re.search(r"\b(?:across|in|between)\b[^.!?]{0,45}\b(?:sets?|sessions?|samples?)\b", sentence, re.I))
            support = any(record.get("assessment", {}).get("consistency" if consistent else "overall") ==
                          ("higher" if consistent else "favorable") for record in ctx.progress_records.values())
            if not (scoped and support) or re.search(r"\bthe (?:cue|drill|adjustment) (?:helped|worked)\b", sentence, re.I):
                issues.append(NarrativeValidationError(
                    "message: describe the compared samples or attribute the reported effect to the player.",
                    evidence_ids=list(ctx.progress_records),
                ))

    def proposed_dose(match):
        prefix = re.split(r"[.!?;\n]|\band\s+(?=(?:you|your|we)\b)", scrubbed[:match.start()], flags=re.I)[-1]
        return (re.search(r"\b(?:take|shoot|try|practice|complete|do|start|rest|pause|rehearse|use|record|film|repeat|begin|limit|allow|aim for|target)\b", prefix, re.I)
                and not re.search(r"\b(?:you (?:made|missed|took|completed)|last session|recorded|measured)\b", prefix, re.I))

    scrubbed = with_shot_units(scrubbed)
    doses = [match for match in DOSE.finditer(scrubbed) if proposed_dose(match)]
    if doses:
        sets = sum(int(match[1]) for match in doses if match[2].casefold().startswith("set")) or 1
        repetitions = sum(int(match[1]) for match in doses if match[2].casefold().startswith(SHOT_UNITS + ("rep",))) or 1
        seconds = sum(int(match[1]) * (60 if match[2].casefold().startswith("minute") else 1)
                      for match in doses if match[2].casefold().startswith(("minute", "second")))
        time_limit = ctx.practice_context.get("available_time_seconds", 600)
        equipment = ctx.practice_context.get("equipment", {})
        shooting = any(match[2].casefold().startswith(SHOT_UNITS) for match in doses)
        if NO_EXERCISE.search(ctx.question):
            issues.append(NarrativeValidationError(f"{field}: the player declined an exercise."))
        if sets < 1 or repetitions < 1 or sets > 3 or sets * repetitions > 30 or any(int(match[1]) < 1 for match in doses):
            issues.append(NarrativeValidationError(f"{field}: keep any practice dose small and comfortable."))
        if max(seconds, sets * repetitions * (15 if shooting else 5)) > time_limit:
            issues.append(NarrativeValidationError(f"{field}: the suggested practice exceeds available time."))
        if equipment.get("clear_space") is False or shooting and any(equipment.get(item) is False for item in ("hoop", "ball")):
            issues.append(NarrativeValidationError(f"{field}: the shooting practice requires equipment or space the player lacks."))
        for match in reversed(doses):
            scrubbed = scrubbed[:match.start()] + scrubbed[match.end():]
    return issues, scrubbed


def numeric_fields(value, prefix=""):
    """Index finite numbers by their source path, with no model-supplied values."""
    if number(value) and prefix:
        return {prefix: value}
    if isinstance(value, dict):
        children = value.items()
    elif isinstance(value, list):
        children = enumerate(value)
    else:
        return {}
    return {key: amount for name, child in children
            for key, amount in numeric_fields(child, f"{prefix}.{name}" if prefix else str(name)).items()}


NUMERAL = re.compile(r"[+−-]?\d+(?:[,.]\d+)*")
OUTCOME_SCOPE = re.compile(
    r"\b(?:last|previous|prior|next|another|different|earlier|later)\s+(?:session|set|practice|drill|week)\b|"
    r"\b(?:before|after)\b[^.!?]{0,25}\b(?:cue|drill|adjustment|practice)\b|"
    r"\b(?:teammate|friend|other player|history|career|lately|yesterday|tomorrow|left[- ]handed|"
    r"right[- ]handed|three[- ]pointers?|in a row|consecutive|warm[- ]?up|from the corner|from close range)\b", re.I,
)
KNOWN_OUTCOMES = re.compile(r"\b(?:known|labelled|labeled|confirmed)\s+(?:outcomes?|attempts?|shots?)\b", re.I)
SHOTS = r"(?:shots?|attempts?|free[- ]throws?)"
COUNTED_OUTCOMES = rf"(?:(?:known|labelled|labeled|confirmed)\s+(?:outcomes?|{SHOTS})|{SHOTS})"
PERCENT = r"(?:%|percent\b)"
MEASURED_AMOUNT = {
    "release_elbow_angle": r"(?:estimated[- ]release elbow angle|release elbow angle|elbow angle at (?:estimated )?release)",
    "min_knee_angle": r"(?:smallest|minimum) knee angle|knee (?:bend|angle) at (?:the |your )?deepest (?:dip|bend)",
    "max_elbow_angle": r"(?:largest|maximum) elbow angle",
    "elbow_angle_range": r"elbow angle range",
    "knee_angle_range": r"knee angle (?:range|change)",
    "shooting_motion_ms": r"(?:time|duration) from (?:detected )?start to (?:estimated )?release",
}


def measurement_unit(metric):
    return r"(?:ms|milliseconds?)\b" if metric == "shooting_motion_ms" else r"(?:degrees?\b|°)"


def scoped_average(before, after, ledger):
    """Only accept averages tied to one qualified current-session metric and outcome group."""
    for metric, name in MEASURED_AMOUNT.items():
        if not re.search(rf"\b{name}\s+(?:averaged|was an average of)\s+$", before):
            continue
        group = re.match(rf"^\s*{measurement_unit(metric)}\s+(?:on|for)\s+(?:your\s+)?"
                         r"(makes|made shots|misses|missed shots)\b", after)
        if not group:
            return None
        field = "mean_made" if group[1].startswith(("made", "makes")) else "mean_missed"
        matches = [(key, ledger.facts[key][field]) for key, record in ledger.records.items()
                   if key.startswith("pattern:") and record["technical"].get("field") == metric
                   and field in ledger.facts[key]]
        if len(matches) == 1:
            key, expected = matches[0]
            return key, expected, f"{MEASUREMENTS[metric]['name'].lower()} average on {group[1]}"
        return None
    return None


LONGITUDINAL_SCOPE = re.compile(r"\b(?:sessions?|first|latest|earlier|previous|so far|recorded|across|overall|"
                                r"in total|all (?:your|of your)|goal|aim|target|working toward)\b", re.I)
LONGITUDINAL_TOOLS = ("retrieve_progress", "retrieve_history", "retrieve_profile", "retrieve_historical_profile")


# Which recorded fields a number may come from, judged by the words around it.
LONGITUDINAL_FIELDS = {
    "rate": ("accuracy_pct",), "angle": ("mean",), "made": ("made", "manual_made"), "missed": ("missed",),
    "count": ("shot_count", "manual_labels", "total_shots", "labelled_shots", "measurement_count"),
}


def longitudinal_kind(before, after):
    if re.match(r"^\s*(?:%|percent\b)", after) or re.search(r"\baccuracy\b[^.!?]{0,30}$", before):
        return "rate"
    if re.match(r"^\s*(?:°|degrees?\b)", after):
        return "angle"
    if re.search(r"\d\s+(?:of|out of)\s*$|\b(?:in|across)\s*$", before):  # "3 of 10", "in 10 attempts"
        return "count"
    if re.match(r"^\s*(?:of|out of|/)\s*\d|^\s*(?:recorded |labell?ed )?(?:makes?|made)\b", after):
        return "made"
    if re.match(r"^\s*(?:recorded |labell?ed )?(?:misses|missed)\b", after):
        return "missed"
    if re.match(r"^\s*(?:recorded |labell?ed )?(?:attempts?|shots?|free[- ]throws?)\b", after):
        return "count"
    return None


def longitudinal_source(value, sentence, ledger, before, after):
    """Evidence key holding this number when the sentence is about earlier sessions, the record or the goal."""
    if not LONGITUDINAL_SCOPE.search(sentence):
        return None
    goal = ledger.ctx.memory.get("goal") or ""
    if (re.search(r"\b(?:goal|aim|target|working toward)\b", sentence, re.I)
            and value in {float(n) for n in re.findall(r"\d+(?:\.\d+)?", goal)}):
        return "memory:goal"
    kind = longitudinal_kind(before, after)
    if kind is None:
        return None
    names = LONGITUDINAL_FIELDS[kind]
    for key, facts in ledger.facts.items():
        # Current-session records have their own checks; this only covers history, progress and profiles.
        if not (key.startswith(("progress:", "history:", "profile:"))
                or key.startswith("tool:") and key.rsplit(":", 1)[-1] in LONGITUDINAL_TOOLS):
            continue
        if any(number(amount) and round(amount, 1) == value and path.rsplit(".", 1)[-1] in names
               for path, amount in facts.items()):
            return key
    return None


def verify_inline_numbers(text, field, ledger, frame_ids=()):
    """Resolve clear current-session counts/rates and selected-shot measurements by meaning and unit."""
    ctx = ledger.ctx
    session_key = f"session:{ctx.tools.session_id}"
    session = ledger.records.get(session_key)
    issues, evidence = [], set()
    for paragraph in text.split("\n\n"):
        in_current_scope = not OUTCOME_SCOPE.search(paragraph) and not re.search(
            r"\b(?:before|after)\s+(?:i|you|we)\b|\b(?:he|she|they)\s+(?:took|attempted|made|missed)\b",
            paragraph, re.I,
        )
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", paragraph):
            for match in NUMERAL.finditer(sentence):
                token = match[0]
                before, after = sentence[:match.start()].casefold(), sentence[match.end():].casefold()
                value = float(token) if re.fullmatch(r"\d+(?:\.\d+)?", token) else None
                expected, key, label = None, None, "scope, meaning, or unit is ambiguous"
                if (session and in_current_scope and not ctx.requested_pair
                        and re.search(r"\b(?:you|your|recorded|session|accuracy)\b", sentence, re.I)):
                    known = session["made"] + session["missed"]
                    explicit_known = bool(KNOWN_OUTCOMES.search(sentence))
                    attempt_count = known if explicit_known else session["attempts"]
                    if (re.match(rf"^\s*{PERCENT}\s*(?:shooting |free[- ]throw )?(?:accuracy|success rate|made|missed)\b", after)
                            or re.match(rf"^\s*{PERCENT}", after)
                            and re.search(r"\b(?:shooting accuracy|free[- ]throw success rate|accuracy|shooting percentage)\s+"
                                          r"(?:among (?:known|labelled|labeled|confirmed) outcomes?\s+)?"
                                          r"(?:was |of |is )?$", before)):
                        if known and (explicit_known or not session["unknown"]):
                            missed = bool(re.match(rf"^\s*{PERCENT}\s*missed\b", after))
                            expected = round(100 * session["missed"] / known, 1) if missed else session["accuracy_pct"]
                            key, label = session_key, "current-session outcome rate"
                    elif re.match(r"^\s+(?:recorded )?(?:makes?|misses?)\b", after) or (
                            re.search(r"\b(?:made|missed)\s+$", before)
                            and re.match(rf"^(?:\s*(?:of them|(?:out )?of|{SHOTS})\b|/|\s*[.!?]?$)", after)):
                        missed = bool(re.match(r"^\s+(?:recorded )?misses?\b", after)
                                      or re.search(r"\bmissed\s+$", before))
                        expected = session["missed" if missed else "made"]
                        key, label = session_key, "current-session miss count" if missed else "current-session make count"
                    elif (re.search(r"\b(?:took|attempted|recorded|out of|(?:made|missed)\s+\d+\s+of)\s+$", before)
                          and re.match(rf"^\s+{COUNTED_OUTCOMES}\b", after)
                          or re.search(r"\b(?:made|missed)\s+\d+(?:\s+(?:out )?of\s+|/)$", before)
                          and re.match(r"^\s*(?:in (?:this|the current) session)?[.,!?)]?\s*$", after)):
                        key, label = session_key, "current-session attempt count"
                        expected = attempt_count
                        if session["unknown"] and not explicit_known and re.search(r"(?:\bof\s+|/)$", before):
                            expected = None
                    if key is None and (average := scoped_average(before, after, ledger)):
                        key, expected, label = average
                # Match a named metric and unit, never a coincidentally equal player value.
                if (key is None and ctx.anchor and not ctx.requested_pair and in_current_scope
                        and (ctx.anchor == ctx.tools.selected or len(ctx.tools.shots) == 1)):
                    single_shot = (not ctx.session or re.search(r"\b(?:this|the selected) shot\b", sentence, re.I))
                    group_claim = re.search(r"\b(?:average|mean|median|across|on (?:your )?(?:makes|misses)|"
                                            r"all (?:your )?(?:shots|attempts)|other attempt)\b", sentence, re.I)
                    if single_shot and not group_claim:
                        for metric, name in MEASURED_AMOUNT.items():
                            if not re.search(rf"\b(?:{name})\s+(?:(?:was|is|measured|of)\s+)?"
                                             r"(?:(?:about|around|roughly|approximately)\s+)?$", before):
                                continue
                            if re.match(rf"^\s*{measurement_unit(metric)}", after):
                                key = f"shot:{ctx.anchor.shot_id}:{metric}"
                                expected = ledger.facts.get(key, {}).get("value")
                                label = f"selected-shot {MEASUREMENTS[metric]['name'].lower()}"
                            break
                        if expected is None and re.match(r"^\s*(?:degrees?\b|°)", after):
                            joint = re.search(r"\b(elbow|knee)\b[^,.;!?]*$", before)
                            phase = re.match(r"^\s*(?:at|by|in)\s+(?:the\s+)?(knee dip|release|follow.through)\b", before)
                            if joint and phase:
                                label = phase[1].replace(" ", "_").replace("-", "_")
                                for ref_id in frame_ids:
                                    ref = ctx.frames[ref_id]
                                    mark = ref.annotation or {}
                                    if (ref_id in ledger.images_sent and ref.shot_id == ctx.anchor.shot_id
                                            and ref.phase == label and mark.get("focus") == joint[1]
                                            and "angle_arc" in mark.get("marks", ())):
                                        key, expected = ref_id, mark["angle_deg"]
                                        break
                approximate = bool(re.search(r"\b(?:about|around|roughly|approximately)\s*$", before))
                rounded = (approximate and expected is not None and value is not None
                           and value == round(expected, len(token.partition(".")[2])))
                if expected is None and value is not None and (source := longitudinal_source(value, sentence, ledger, before, after)):
                    if source in ledger.records:  # A count, rate or mean from history, progress or the goal.
                        evidence.add(source)
                elif value is None or expected is None or value != expected and not rounded:
                    issues.append(NarrativeValidationError(
                        f"{field}: numerical claim {token} cannot be verified ({label}).",
                        allowed_values={label: expected} if expected is not None else None,
                        evidence_ids=[key] if key else [],
                    ))
                else:
                    evidence.add(key)
    if re.search(r"\{\{|\}\}", text):
        issues.append(NarrativeValidationError(f"{field}: remove an unresolved fact placeholder.", kind="contract"))
    return issues, evidence


class AuthorEvidence:
    """Evidence ledger shared by tool delivery and local validation."""

    def __init__(self, ctx, history=()):
        self.ctx = ctx
        self.history = history
        self.records = {}
        self.facts = {}
        self.frame_ids = set()
        self.images_sent = set()
        self.knowledge = {}
        self.resource_ids = set()
        self.practice = {}

    def add(self, records):
        new = {key: value for key, value in records.items() if key not in self.records}
        self.records.update(new)
        self.facts.update({key: numeric_fields(value) for key, value in new.items()})
        return new

    def packet(self):
        ctx = self.ctx
        records = {key: item.model_dump() | {"topic": ctx.observation_topics[key]}
                   for key, item in ctx.observations.items()}
        records.update({shot["id"]: shot for shot in ctx.shot_summaries.values()})
        if not ctx.requested_pair:
            if not ctx.session_pair:
                records["history:outcome_counts"] = ctx.history_summary["counts"]
            if ctx.profile is not None:
                records["profile:current"] = ctx.profile_summary()
            current_session_relevant = not ctx.session_pair or ctx.tools.session_id in ctx.session_pair
            if ctx.session and ctx.session.get("status") == "available" and current_session_relevant:
                records[f"session:{ctx.tools.session_id}"] = ctx.session
            if ctx.review_requested and ctx.progress.get("status") == "available":
                ctx.retrieve_progress()
            records.update(ctx.progress_records)
            if not ctx.session_pair:
                for item in ctx.supported_strengths():
                    records.setdefault(item.evidence_ids[0], item.model_dump())
        frames = {key: ref.public() for key, ref in ctx.frames.items()
                  if not ctx.requested_pair or ctx.in_requested_pair(ctx.tools.resolve(ref.shot_id))}
        self.frame_ids.update(frames)
        records.update(frames)
        new = self.add(records)
        # Observation facts use the same field names as their measured/statistical payload.
        for key in new.keys() & ctx.observations.keys():
            self.facts[key] = numeric_fields(ctx.observations[key].technical or {})
        new_knowledge = {key: supporting_context(key) for key in ctx.knowledge_ids if key not in self.knowledge}
        self.knowledge.update(new_knowledge)
        previous_options = self.practice
        self.practice = ctx.practice_options()
        new_resources = [resource.summary(topic) for key, (resource, topic) in ctx.resources.items()
                         if key not in self.resource_ids]
        self.resource_ids.update(ctx.resources)
        packet = {
            "evidence": {key: self.compact_record(key, record) for key, record in new.items()
                         if not (key.startswith("shot:") and key in ctx.observations)},
            "knowledge": {key: {field: item[field] for field in (
                "topic", "principle", "use_when", "avoid_when", "evidence_basis", "purpose", "application",
            ) if field in item and (field != "purpose" or "application" in item)}
                          for key, item in new_knowledge.items()},
            "eligible_practice": {
                key: {field: item[field] for field in ("title", "eligible_topics", "required_equipment")}
                for key, item in self.practice.items() if previous_options.get(key) != item
            },
        }
        if preferred := [key for key in ctx.primary_measurements() if key in new]:
            packet["selected_attempt_observations"] = {
                key: {field: ctx.observations[key].technical[field] for field in ("field", "value", "unit", "phase")}
                for key in preferred
            }
        if new_resources or ctx.resource_request and not self.resource_ids:
            packet["instructional_resources"] = new_resources
            if ctx.resource_request:
                packet["requested_resource_kind"] = ctx.resource_request
        return packet

    @staticmethod
    def compact_record(key, record):
        if key == "profile:current":
            return {name: record[name] for name in ("status", "counts", "conditions", "likely_patterns", "observation_ids")
                    if name in record} | {
                "features": {name: {field: row[field] for field in ("result", "n_made", "n_missed") if field in row}
                             for name, row in record.get("features", {}).items()}
            }
        if key.startswith("pattern:"):
            fields = ("field", "unit", "n_made", "n_missed", "mean_made", "mean_missed", "direction", "effect_size")
            return {"topic": record["topic"],
                    "technical": {name: record["technical"][name] for name in fields if name in record["technical"]}}
        if key.startswith("shot:") and "measurements" in record:
            return {name: record[name] for name in ("shot_id", "session_id", "shot_number", "outcome",
                    "outcome_source", "conditions", "provenance", "ball_flight", "events")} | {
                "measurements": {name: {field: value[field] for field in ("status", "value", "unit", "sample_frames")}
                                 for name, value in record["measurements"].items()}
            }
        if key.startswith("session:") and "technical" in record:
            return {"text": record["text"]}
        return record


def validate_practice(proposal, ledger):
    ctx = ledger.ctx
    option = ledger.practice.get(proposal.drill_id)
    if not option or proposal.topic not in option["eligible_topics"]:
        raise NarrativeValidationError("practice: select an eligible drill and topic for the player's equipment, time and feedback.",
                                       allowed_values={key: item["eligible_topics"] for key, item in ledger.practice.items()})
    if NO_EXERCISE.search(ctx.question):
        raise NarrativeValidationError("practice: the player declined an exercise.", allowed_values=[None])
    rehearsal = "hoop" not in option["required_equipment"]
    dose = proposal.dose
    if dose:
        seconds_per_rep = 5 if rehearsal else 15
        budget = ctx.practice_context.get("available_time_seconds", 600)
        if not dose.sets * dose.repetitions * seconds_per_rep <= dose.duration_seconds <= budget:
            raise NarrativeValidationError("practice.dose: fit the repetitions and resets within the stated time.",
                                           allowed_values={"maximum_seconds": budget, "seconds_per_repetition": seconds_per_rep})
        previous = ctx.focus.get("prescribed_dose") if ctx.focus and ctx.focus.get("drill_id") == proposal.drill_id else None
        easier = ctx.drill_constraints(proposal.topic).get("easier")
        if easier and ((previous and dose.sets * dose.repetitions > previous["sets"] * previous["repetitions"])
                       or (not previous and (dose.sets > 1 or dose.repetitions > 5))):
            raise NarrativeValidationError("practice.dose: honor the request for lower workload.")
    for match in DOSE.finditer(with_shot_units(quantified_words(proposal.instructions))) if dose else ():
        value, unit = int(match[1]), match[2].lower()
        if unit.startswith("set"):
            expected = dose.sets
        elif unit.startswith(SHOT_UNITS + ("rep",)):
            expected = dose.repetitions
        else:
            value *= 60 if unit.startswith("minute") else 1
            expected = dose.duration_seconds
        # Naming one of several sets ("shoot one set as usual, then...") is part of the same dose.
        if value != expected and not (unit.startswith("set") and 1 <= value <= expected):
            raise NarrativeValidationError("practice.instructions: any literal quantity must agree with the structured dose.")
    if rehearsal and any(
        re.search(r"\bshoot\b|\btake\b.{0,20}\bshots\b|\brelease the ball\b", sentence, re.I)
        and not re.search(r"\b(?:no|not|without|do not|don't)\b", sentence, re.I)
        for sentence in re.split(r"[.!?]", proposal.instructions)
    ):
        raise NarrativeValidationError("practice.instructions: this drill is a no-release rehearsal.")
    return option


def validate_answer(answer, ledger, discarded=None):
    """Sanitize optional components, then collect independent problems in the spoken reply."""
    discarded = [] if discarded is None else discarded
    ctx = ledger.ctx
    def discard(field, reason):
        discarded.append({"field": field, "reason": reason})

    issues = []
    if answer.instructional_resource_id and answer.instructional_resource_id not in ledger.resource_ids:
        discard("instructional_resource_id", "Resource was not offered by the reviewed catalog")
        answer.instructional_resource_id = None
    kept = []
    for choice in answer.more_resources:
        if (choice.id not in ledger.resource_ids or choice.id == answer.instructional_resource_id
                or choice.id in {item.id for item in kept}):
            discard("more_resources", "Resource was not offered, or repeats another recommendation")
        else:
            kept.append(choice)
    if kept and not answer.instructional_resource_id:
        first = kept.pop(0)
        answer.instructional_resource_id, answer.resource_note = first.id, answer.resource_note or first.note
    answer.more_resources = kept
    if not answer.instructional_resource_id and not ctx.resource_optout:
        answer.instructional_resource_id = next((resource.id for resource in named_resources(answer.message)
                                                if resource.id in ledger.resource_ids), None)
    selected_resources = {answer.instructional_resource_id, *(choice.id for choice in answer.more_resources)}
    paragraphs = []
    removed = False
    for paragraph in answer.message.split("\n\n"):
        kept = []
        for sentence in re.split(r"(?<!\bJr\.)(?<!\bSr\.)(?<=[.!?])\s+", paragraph, flags=re.I):
            named = named_resources(sentence)
            local_video = re.search(
                r"\b(?:your|this|the selected) (?:shot |shooting )?(?:video|clip)\b|"
                r"\b(?:record|film|upload)\b[^.!?]*\b(?:video|clip)\b", sentence, re.I,
            )
            card_reference = answer.instructional_resource_id and not EXTERNAL_LINK.search(sentence) and re.search(
                r"\b(?:watch|read|use|see)\s+(?:this|the|that) (?:instructional )?(?:video|article|tutorial)"
                r"(?:\s+(?:for|to|while|below)\b|[.!?]|$)", sentence, re.I,
            )
            if ((named or MEDIA_RECOMMENDATION.search(sentence) and not (local_video or card_reference))
                    and not (named and all(resource.id in selected_resources for resource in named))):
                discard("message", "Unverified external recommendation removed")
                removed = True
                continue
            if answer.instructional_resource_id and re.search(
                r"\b(?:couldn['’]t|can['’]t|unable to|no)\b[^.!?]*\bverified\b[^.!?]*\b(?:resource|video|article)\b", sentence, re.I,
            ):
                removed = True
                continue
            kept.append(sentence)
        if kept:
            paragraphs.append(" ".join(kept))
    if removed:
        answer.message = "\n\n".join(paragraphs).strip()
    link_fields = [(answer, "message")]
    if answer.practice:
        link_fields.extend((answer.practice, field) for field in ("instructions", "evaluation"))
    for component, field in link_fields:
        value = getattr(component, field)
        if value and EXTERNAL_LINK.search(value):
            setattr(component, field, EXTERNAL_LINK.sub(lambda match: match[1] or "", value).strip())
            discard(field, "Use the reviewed resource field for external links")
    if not answer.message:
        answer.message = "See the instructional resource below." if answer.instructional_resource_id else (
            "We can work from the available coaching guidance."
        )
    if answer.practice and not answer.practice.instructions:
        discard("practice", "The proposal contained a link but no instructions")
        answer.practice = None
    for field, pool in (("evidence_ids", ledger.records), ("frame_ids", ledger.frame_ids),
                        ("knowledge_ids", ledger.knowledge)):
        original = getattr(answer, field)
        filtered = list(dict.fromkeys(key for key in original if key in pool))
        if field == "frame_ids":
            filtered = ctx.unique_frame_ids(filtered)
        if filtered != original:
            discard(field, "Unknown or duplicate references removed")
        if field == "frame_ids":
            if not filtered and ctx.visual_requested:
                if not ctx.frames:
                    ctx.select_frames()
                    ledger.packet()
                filtered = ctx.unique_frame_ids(ctx.frames)[:4]
            if original and not filtered and re.search(
                r"\b(?:watch|see|look at)\s+(?:this|these|the attached)\s+frames?\b", answer.message, re.I,
            ):
                issues.append(NarrativeValidationError("frame_ids: the message refers to a frame that is unavailable.",
                                                      evidence_ids=sorted(ledger.frame_ids)))
        setattr(answer, field, filtered)

    def verified_movement(tag):
        return set(answer.frame_ids) <= ledger.images_sent and ctx.corroborate_visual(answer.frame_ids, tag) == tag

    if answer.visual and answer.visual != "unclear" and not verified_movement(answer.visual):
        discard("visual", "Movement tag lacks verified same-shot phase images")
        answer.visual = None
    if movement := VISUAL_DIRECTION.search(answer.message) or VISUAL_COMPARISON_DIRECTION.search(answer.message):
        part = "knee" if movement[1].casefold() == "knee" else "arm"
        direction = "straightens" if movement[2].casefold().startswith("straighten") else "bends"
        if not verified_movement(f"{part}_{direction}"):
            issues.append(NarrativeValidationError("visual: the stated movement needs corroborating phase images.",
                                                  evidence_ids=sorted(ledger.images_sent)))
    if (finish := VISUAL_FINISH_CLAIM.search(answer.message)) and (
        not verified_movement("arm_straightens") or re.search(r"\bforward\b", finish[0], re.I)
    ) and not re.search(r"\b(?:no clear|not|can't|cannot|unclear)\b", finish[0], re.I):
        issues.append(NarrativeValidationError("visual: the stated follow-through movement is not established by the verified phases.",
                                              evidence_ids=sorted(ledger.images_sent)))
    if ctx.anchor and len(ctx.tools.shots) == 1 and re.search(
        r"\b(?:a good habit to keep|a typical (?:arm|knee|release|shooting) [^.!?]*\bpattern|"
        r"your (?:shot|form|release|routine|mechanics) (?:is|are) (?:usually |consistently )?consistent)\b",
        answer.message, re.I,
    ):
        issues.append(NarrativeValidationError(
            "message: describe this attempt only. It does not establish a shooting habit or repeatability."
        ))

    if answer.resource_note is not None:
        note_issues, remaining = validate_text(answer.resource_note, "resource_note", ctx)
        note_issues += verify_inline_numbers(remaining, "resource_note", ledger)[0]
        if note_issues or not answer.instructional_resource_id or FACT_TOKEN.search(answer.resource_note):
            discard("resource_note", "Resource note was unsupported or had no resource")
            answer.resource_note = None
    for choice in answer.more_resources:
        if choice.note is not None:
            note_issues, remaining = validate_text(choice.note, "more_resources.note", ctx)
            note_issues += verify_inline_numbers(remaining, "more_resources.note", ledger)[0]
            if note_issues or FACT_TOKEN.search(choice.note):
                discard("more_resources", "Resource note was unsupported")
                choice.note = None

    option = None
    if answer.practice:
        try:
            option = validate_practice(answer.practice, ledger)
            for field in ("instructions", "evaluation"):
                text = getattr(answer.practice, field)
                if not text:
                    continue
                checks, remaining = validate_text(text, f"practice.{field}", ctx)
                checks.extend(verify_inline_numbers(remaining, f"practice.{field}", ledger)[0])
                if checks:
                    raise AnswerValidationError(checks)
        except (NarrativeValidationError, AnswerValidationError) as exc:
            discard("practice", str(exc))
            answer.practice = None
            option = None

    adaptation = answer.adaptation
    if adaptation:
        reason = None
        if not ctx.focus:
            reason = "There is no previous active objective"
        elif adaptation == "continue" and ctx.feedback and ctx.feedback["kind"] == "did_not_help":
            reason = "The player reported the objective did not help"
        elif (adaptation in ("modify", "advance")) != bool(answer.practice):
            reason = "Modify and advance require a valid proposal. Continue and discontinue use the existing objective"
        elif adaptation == "advance" and (
            not ctx.next_practice_dose or answer.practice.topic != ctx.focus["knowledge_id"]
            or answer.practice.drill_id != ctx.focus.get("drill_id") or not answer.practice.dose
            or answer.practice.dose.model_dump() != ctx.next_practice_dose
        ):
            reason = "Advance requires a reported helpful completed plan and the permitted next dose for the same drill"
        if reason:
            discard("adaptation", reason)
            answer.adaptation = None
            if adaptation == "advance" and answer.practice:
                discard("practice", "The proposed progression was not supported by the current objective")
                answer.practice = None
                option = None

    # Keep only references used in text, and compact their indices without touching ordinary prose.
    texts = {"message": answer.message}
    if answer.practice:
        texts.update({f"practice.{field}": value for field in ("instructions", "evaluation")
                      if (value := getattr(answer.practice, field))})
    values, references, indices = [], [], {}
    checks, remaining = validate_text(answer.message, "message", ctx)
    inline_issues, inline_sources = verify_inline_numbers(remaining, "message", ledger, answer.frame_ids)
    issues.extend(checks + inline_issues)
    answer.evidence_ids = list(dict.fromkeys([*answer.evidence_ids, *sorted(inline_sources)]))
    cited = set(answer.evidence_ids) | set(answer.frame_ids)

    for field, text in texts.items():
        def resolve_reference(match):
            index = int(match[1])
            if index >= len(answer.facts):
                issue = NarrativeValidationError(f"{field}: fact placeholder {index} has no reference.", kind="contract")
            else:
                ref = answer.facts[index]
                catalog = ledger.facts.get(ref.evidence_id, {})
                if ref.evidence_id in cited and ref.field in catalog:
                    if index not in indices:
                        indices[index] = len(values)
                        references.append(ref)
                        values.append(catalog[ref.field])
                    return "{{fact:" + str(indices[index]) + "}}"
                issue = NarrativeValidationError(f"{field}: fact placeholder {index} needs a verified field from cited evidence.",
                                                 allowed_values={key: sorted(ledger.facts[key]) for key in sorted(cited)
                                                                 if ledger.facts.get(key)},
                                                 evidence_ids=sorted(cited))
            if field == "message":
                issues.append(issue)
            else:
                discard("practice", str(issue))
            return match[0]
        resolved = FACT_TOKEN.sub(resolve_reference, text)
        if field == "message":
            answer.message = resolved
        elif answer.practice:
            setattr(answer.practice, field.split(".")[1], resolved)
    if answer.practice and any(item["field"] == "practice" for item in discarded):
        answer.practice = option = None
        if answer.adaptation in ("modify", "advance"):
            discard("adaptation", "The replacement proposal could not be verified")
            answer.adaptation = None
    if len(references) != len(answer.facts):
        discard("facts", "Unused numeric reference entries removed")
    answer.facts = references

    if issues:
        raise AnswerValidationError(issues)
    return values, option


def render_answer(answer, ledger, values, option):
    ctx = ledger.ctx
    def resolve(text):
        return FACT_TOKEN.sub(lambda match: f"{values[int(match[1])]:g}", text) if text else None

    topic = answer.practice.topic if answer.practice else next(iter(answer.knowledge_ids), None)
    observations = [key for key in answer.evidence_ids if key in ctx.observations]
    if topic is None:
        topic = next((ctx.observation_topics[key] for key in observations if key.startswith("pattern:")), None)
    intent = ctx.intent or ("practice" if answer.practice else "general")
    decision = Decision(intent="practice" if option else intent, observation_ids=observations,
                        knowledge_id=topic, adaptation=answer.adaptation)
    result = CoachingResponse(response_type=intent, message=resolve(answer.message), session_summary=ctx.session,
        show_details=ctx.memory.get("preferences", {}).get("explanation_style") == "detailed")
    result.video_references = [ctx.frames[key].public() | {
        "outcome": ctx.tools.resolve(ctx.frames[key].shot_id).outcome,
        "outcome_source": ctx.tools.resolve(ctx.frames[key].shot_id).outcome_source,
    } for key in answer.frame_ids]
    source_ids = list(dict.fromkeys(answer.knowledge_ids + ([answer.practice.topic] if answer.practice else [])))
    result.knowledge_references = [{"id": key, "source": KNOWLEDGE[key]["source"],
                                    "url": ledger.knowledge[key]["url"], "kind": "supporting_source"}
                                   for key in source_ids]
    if intent in ("progress", "reassess") or answer.adaptation:
        result.previous_focus = ctx.previous_plan()
    if ctx.review_requested:
        result.progress = next((ctx.progress_records[key] for key in answer.evidence_ids
                                if key in ctx.progress_records), ctx.progress)
    if option:
        proposal = answer.practice
        result.focus = KNOWLEDGE[topic]["topic"]
        assumptions = [f"Requires access to a {item}." for item in option["required_equipment"]
                       if item not in ctx.practice_context.get("equipment", {})]
        result.practice = Practice(title=option["title"], drill_id=proposal.drill_id, dose=proposal.dose,
            instructions=resolve(proposal.instructions), evaluation=resolve(proposal.evaluation) or option["success_criteria"],
            assumptions=assumptions, source_info=option["source_info"])
        result.guidance_basis = "personal_pattern" if supporting_pattern(decision, ctx) else "general"
    if answer.instructional_resource_id:
        # A video is a learning resource; any personal practice lives in its own card.
        result.instructional_resource = ctx.resource_card(answer.instructional_resource_id, answer.evidence_ids,
                                                          answer.frame_ids, include_exercise=False,
                                                          note=answer.resource_note, generic=False)
        result.additional_resources = [
            ctx.resource_card(choice.id, answer.evidence_ids, answer.frame_ids, include_exercise=False,
                              note=choice.note, generic=False)
            for choice in answer.more_resources]
    if answer.adaptation == "advance" and result.practice:
        result.cue = result.practice.focus = ctx.focus["cue"]
    result.authored_evidence = {
        "observations": {key: ctx.observations[key].model_dump() for key in observations},
        "citations": answer.evidence_ids, "numeric_facts": [
            {**fact.model_dump(), "value": value} for index, (fact, value) in enumerate(zip(answer.facts, values))
            if any("{{fact:" + str(index) + "}}" in text for text in (
                answer.message, answer.practice.instructions if answer.practice else "",
                (answer.practice.evaluation or "") if answer.practice else ""))],
    }
    return decision, result


def practice_defaults(decision, ctx, cue=None):
    selected = ctx.drill_recommendation(decision.knowledge_id)
    if not selected:
        return None
    support = supporting_pattern(decision, ctx)
    reason = (f"The supported {selected['targeted_issue'].lower()} association makes this one movement to test, not a proven cause of misses."
              if support else "General practice for the selected focus; the evidence does not establish a personal weakness.")
    focus = cue or (f"Try {MOVEMENT[support[1].technical['field']][0 if support[1].technical['direction'] == 'higher_on_makes' else 1]}."
                    if support else selected["coaching_cues"][0])
    rehearsal = "hoop" not in selected["required_equipment"]
    if rehearsal:
        focus = focus.replace("as the ball leaves your hand", "while rehearsing without releasing a ball")
    details = {
        "title": selected["title"], "drill_id": selected["id"], "dose": selected["suggested_dose"],
        "reason": reason, "setup": selected["setup"], "focus": focus,
        "instructions": " ".join(selected["instructions"]),
        "evaluation": ("I'll review the selected movement across attempts and report makes and misses separately."
                       if not rehearsal else "Report whether the cue felt comfortable and repeatable. Rehearsal does not establish shooting accuracy."),
        "success_criteria": selected["success_criteria"], "easier_variation": selected["easier_variation"],
        "progression": selected["progression"], "reconsider": selected["reconsider"],
        "assumptions": selected["assumptions"], "source_info": {**selected["source_info"], "principle": selected["principle_source"]},
    }
    if ctx.memory.get("preferences", {}).get("explanation_style") == "simple":
        details["reason"] = ("A small experiment based on your recorded pattern, not proof of a fault."
                             if support else "General practice; this is not an identified personal weakness.")
        details["instructions"] = ("Rehearse the focus cue without releasing a ball, then reset."
                                   if rehearsal else "Use the focus cue for each comfortable shot, then reset.")
    return details


def personalize_fallback_practice(decision, ctx, result):
    if not result.practice:
        return result
    details = practice_defaults(decision, ctx, result.cue)
    if details is None:
        result.practice = None
        result.cue = None
        result.next_step = "No suitable exercise fits the stated constraints and practice reports. Reassess those before choosing another drill."
        return result
    result.practice = Practice(**details)
    result.cue = details["focus"]
    return result


def supporting_pattern(decision, ctx):
    for evidence_id in decision.observation_ids:
        if evidence_id.startswith("pattern:") and ctx.observation_topics[evidence_id] == decision.knowledge_id:
            return evidence_id, ctx.observations[evidence_id]
    return None


def grounded_practice(decision, ctx, result, output):
    """Tie the default experiment to a measured pattern, or clearly label a general drill."""
    support = supporting_pattern(decision, ctx)
    if not support:
        if not result.practice:
            return
        result.guidance_basis = "general"
        if result.response_type != "general":
            result.guidance_note = "General practice option. The available evidence is too limited to identify a personal adjustment."
        if decision.knowledge_id != "recording":
            result.practice.evaluation = (
                "Record another set from the same spot and angle. I’ll review the movement across attempts "
                "and track makes separately when outcomes are available."
            )
        return

    evidence_id, observation = support
    field = observation.technical["field"]
    higher = observation.technical["direction"] == "higher_on_makes"
    cue = MOVEMENT[field][0 if higher else 1]
    measurement = MEASUREMENTS[field]["name"].lower()
    if result.practice:
        result.guidance_basis = "personal_pattern"
        result.practice.title = f"{KNOWLEDGE[decision.knowledge_id]['topic']} practice set"
        result.explanation = (
            f"The difference was in your {measurement}. Trying the version that showed up on your makes "
            "gives us one movement to test while keeping the rest of your shot familiar."
        )
        result.cue = f"Try {cue}."
        result.practice.instructions = (
            "Take a short set from one spot. Rehearse the cue once before each shot, "
            "then shoot at your usual pace."
            if field != "shooting_motion_ms" else
            "Take a short set from one spot. Rehearse the new rhythm once before each shot, then let the ball go smoothly."
        )
        result.practice.evaluation = (
            f"Film the next set from the same angle. I’ll compare your {measurement} across attempts "
            "and report makes and misses separately."
        )
    frames = [frame for frame in result.video_references
              if frame["id"] in ctx.pattern_frames.get(evidence_id, ())]
    if frames:
        phases = " and ".join(PHASE_LABELS[phase] for phase in dict.fromkeys(frame["phase"] for frame in frames))
        representative = {frame["outcome"]: frame["shot_number"] for frame in frames}
        if len({frame["video_id"] for frame in frames}) == 1:
            examples = f"shot {representative['made']} (make) and shot {representative['missed']} (miss)"
        else:
            examples = "the made and missed attempts shown here"
        visual = f"Look at {phases} in {examples}. "
        if field in ("min_knee_angle", "release_elbow_angle", "max_elbow_angle"):
            joint = "knee" if field == "min_knee_angle" else "shooting elbow"
            visual += f"The {joint} appears {'straighter' if higher else 'more bent'} in the made example."
        else:
            physical_feature = {
                "knee_angle_range": "the change in knee bend", "elbow_angle_range": "the change in elbow bend",
                "elbow_extension_after_release": "how much the elbow straightens after release",
                "shooting_motion_ms": "the time between the start and release",
            }[field]
            visual += f"Notice {physical_feature}. It was {'greater' if higher else 'smaller'} in the made example."
        output[evidence_id].visual_focus = visual
    elif result.practice:
        result.guidance_note = "I couldn’t verify matching frames for this pattern."
