"""Assemble the evidence and visual references available to one response."""

import csv
import hashlib
import json
import re
from functools import cached_property

from backend.app.agent.evidence import FORM_FIELDS, LIMITATIONS, MEASUREMENTS, ROOT, VIDEO_ID, comparable, number, shot_evidence
from backend.app.agent.knowledge import (
    KNOWLEDGE, METRIC_GUIDANCE, eligible_drills, parent_topic, search_knowledge, select_drill, supporting_context,
)
from backend.app.agent.memory import active_focus
from backend.app.agent.player_input import DIFFICULTY, HELPED, merge_practice_constraints, practice_constraints, stated_profile
from backend.app.agent.profile import personal_profile
from backend.app.agent.progress import assess_progress, compare_sessions
from backend.app.agent.response import InstructionalResource, Observation
from backend.app.agent.resources import (
    CONTEXTUAL_RESOURCE_REQUEST, RESOURCE_OPTOUT, ResourceKind, find_resources, named_resources, requested_resource_kind,
    REVIEWED_ON,
)
from backend.app.agent.retrieval import CoachingTools
from backend.app.agent.session_analysis import representative_pair
from backend.app.agent.annotations import Focus
from backend.app.agent.video import angle_file, video_source

PHASES = {
    "knees": ("knee_dip", "knee_extension"), "stance": ("preparation",),
    "preparation": ("preparation", "release"), "arm": ("preparation", "release"),
    "finish": ("release", "follow_through"), "release": ("release", "follow_through"),
    "landing": ("landing",), "timing": ("preparation", "release", "follow_through"),
}
VISUAL_FOCUS = {"arm": "elbow", "knees": "knee", "finish": "elbow", "stance": "alignment"}
NAMED_PHASES = {
    "preparation": r"preparation|set position",
    "knee_dip": r"loading|knee dip|deepest (?:knee )?bend",
    "knee_extension": r"knee extension|leg extension|leg drive",
    "release": r"release",
    "follow_through": r"follow[ -]?through",
    "landing": r"landing",
}
VISUAL_REQUEST = re.compile(r"\b(show (?:me|where|how|that)|which frame|in (?:my|the) (?:video|clip)|"
                            r"see my|watch|side[ -]by[ -]side|annotat\w*|frames? of)\b", re.I)
CROSS_SESSION = re.compile(r"\b(?:across|different|previous|prior|last|earlier|between)\s+"
    r"(?:(?:my|two|practice|different)\s+)*sessions?\b", re.I)
CONSISTENCY = re.compile(r"\b(?:consisten\w*|repeatab\w*)\b", re.I)
SAVED_PLAN = re.compile(r"\bmy (?:last |current |previous |saved )?(?:practice )?(?:plan|drill|cue|exercise|routine)\b", re.I)
PROGRESS_REQUEST = re.compile(
    r"\b(?:progress|improving|(?:have|did) i (?:actually |really )?improved?|am i (?:getting )?better|"
    r"since (?:i|last)|after practice|did it help|(?:more|less) consistent|"
    r"did (?:the|that|your|my) (?:last )?(?:\w+ ){0,2}(?:adjustment|cue|drill|exercise)\b[^.!?]{0,48}\bhelp|"
    r"compare (?:my |the |last )*sessions?|(?:latest|last|this) session (?:compare|versus|vs)|"
    r"compare\w* (?:with|to) (?:my )?(?:earlier|previous|last|first) (?:ones|sessions?))\b", re.I,
)
NEXT_FOCUS = re.compile(r"\b(?:what should i (?:focus on|work on|practi[cs]e) next|next practice focus)\b", re.I)
ADVANCE_REQUEST = re.compile(r"\b(?:harder|more challenging|advance (?:the|this|my)|"
                             r"progress (?:the|this|my) drill|next level)\b", re.I)
OUTCOME_PAIR = re.compile(r"\b(?:make[sd]?|made|success(?:ful)?)\b.*\b(?:miss\w*|unsuccessful)\b|"
                          r"\b(?:miss\w*|unsuccessful)\b.*\b(?:make[sd]?|made|success(?:ful)?)\b", re.I)

VISUAL_PHASES = {"arm": ("release", "follow_through"), "knee": ("preparation", "release")}
FREE_THROW_CONCERN = re.compile(r"\b(?:keep missing|struggle with|miss (?:too )?many) .{0,25}free[ -]throws?\b", re.I)
EXERCISE_REQUEST = re.compile(
    r"\b(?:what should i practice|practice today|(?:give|suggest|recommend|need|want|any|which|what)\b"
    r"[^.!?]{0,32}\b(?:drills?|exercises?))\b", re.I,
)
SESSION_ASSESSMENT = re.compile(
    r"\b(?:overall|how did i (?:do|shoot)|how was my shooting|is my form effective|"
    r"(?:assess|evaluate|review)\b[^.!?]{0,32}\bsession|what does\b[^.!?]*\b(?:mean|tell us))\b", re.I,
)
EXPLANATION_REQUEST = re.compile(
    r"\b(?:why (?:should|does|is|would)|why[^.!?]*matter|what does[^.!?]*mean|"
    r"how (?:many|much|long)|degrees|milliseconds|technical)\b", re.I,
)


PLAIN_OBSERVATIONS = {
    "elbow_extension_after_release": "Your shooting arm straightens farther in the short window after estimated release.",
    "knee_angle_range": "Your knee angle changes between the start of the shot and estimated release.",
}


def explicit_topics(question):
    """Technique mentions, not generic words such as shooting, practice or form."""
    rules = (
        ("timing", r"quicker release|faster release|slower release|release faster|release more quickly|timing|rhythm|coordination"),
        ("finish", r"follow[ -]?through|finish|extension after release"),
        ("knees", r"knees?|knee bend|leg drive|dip"),
        ("arm", r"shooting arm|\barm\b|elbow|alignment"),
        ("stance", r"stance|feet|footwork|balance"),
        ("preparation", r"grip|pickup|ball preparation|guide hand"),
        ("release", r"wrist|fingers|spin|\brelease\b"),
        ("landing", r"landing|\bland\b|drift"),
        ("distance", r"distance|range|farther|further|trajectory|\barc\b"),
    )
    matches = [(match.start(), topic) for topic, pattern in rules
               if (match := re.search(pattern, question, re.I))]
    topics = [topic for _, topic in sorted(matches)]
    # Faster release describes timing, not an additional wrist/release request.
    if "timing" in topics and "release" in topics and not re.search(r"wrist|fingers|spin", question, re.I):
        topics.remove("release")
    if "arm" in topics and "release" in topics and re.search(r"release elbow|elbow angle.*release", question, re.I):
        topics.remove("release")
    return topics


def explicit_topic(question):
    return next(iter(explicit_topics(question)), None)


def inferred_intent(question):
    query = question.casefold().replace("’", "'")

    # Remove a common basketball idiom before looking for player-reported pain.
    health = query.replace("hurt my chances", "").replace("hurts my chances", "")
    health = re.sub(r"\b(?:injury prevention|prevent(?:ing)? (?:an? )?injur(?:y|ies))\b", "", health)
    if re.search(r"\b(pain(?:ful)?|hurts?|ach(?:e|es|ing)|sore(?:ness)?|discomfort|injur\w*|swollen|numb(?:ness)?|dislocat\w*|sprain\w*|tendonitis|tendinitis|pins and needles)\b", health):
        return "pain"
    if re.search(r"did(?:n't| not) (?:help|work)|got worse|made .{0,30}worse|disagree|don't agree|doesn.t feel right|still struggling", query):
        return "reassess"
    if re.search(r"\b(power|too (?:hard|soft|much force)|force|launch angle)\b", query):
        return "power"
    if re.search(r"what am i doing well|what should i keep doing|anything good about|strengths|what.*doing right|"
                 r"anything[^.!?]*\bkeep (?:rather than|instead of) chang", query):
        return "strengths"
    if ADVANCE_REQUEST.search(query) or NEXT_FOCUS.search(query):
        return "practice"
    if PROGRESS_REQUEST.search(query) or HELPED.fullmatch(query):
        return "progress"
    if re.search(r"\b(compare|comparison|versus|vs\.?|makes and misses|make and miss)\b", query):
        return "compare"
    if CONSISTENCY.search(query) and re.search(r"\b(?:my|across|between|from shot to shot)\b", query):
        return "compare"
    if VISUAL_REQUEST.search(query):
        return "visual"
    if re.search(r"\b(why|cause)\b.*\b(miss\w*)\b", query):
        return "explain_miss"
    if re.search(r"\b(what should i practice|drills?|practice today|give me .{0,12}exercise)\b", query):
        return "practice"
    if re.search(r"\b(my (?:shot|shooting|form|release|elbow|knee)|what am i doing wrong|how can i improve)\b", query):
        return "shot"
    if FREE_THROW_CONCERN.search(query) or (
        re.search(r"\b(?:i struggle|i have trouble|i can't)\b", query)
        and re.search(r"\b(?:shoot\w*|shots?)\b", query)
    ):
        return "shot"
    if explicit_topic(question) and re.search(r"\b(improve|practice|work on|my|i want)\b", query):
        return "shot"
    profile = stated_profile(question)
    if profile.get("goal") or profile.get("experience"):
        return "shot"
    return None


class EvidenceContext:
    def __init__(self, player, question, selected, comparison, history, memory, *, shots=None, session_id=None):
        self.tools = CoachingTools(player, selected, shots=shots, session_id=session_id)
        self.session = self.tools.session_summary() if self.tools.session_id is not None else None
        self.session_pattern_id = None
        self.pattern_frames = {}
        self.question = question
        self.history = history
        self.resources = {}
        self.resource_optout = bool(RESOURCE_OPTOUT.search(question))
        self.resource_request = requested_resource_kind(question) or (
            "any" if not self.resource_optout and named_resources(question) else ""
        )
        self.intent = inferred_intent(question)
        self.visual_requested = bool(VISUAL_REQUEST.search(question))
        if self.resource_request and self.intent == "visual" and not re.search(
            r"\b(?:show|see) (?:me )?(?:(?:where|how) )?(?:my|this attempt)\b|"
            r"\b(?:which frame|annotated frames?|in my (?:video|clip))\b",
            question, re.I,
        ):
            self.intent = None
            self.visual_requested = False
        self.visual_across_sessions = bool(CROSS_SESSION.search(question))
        if self.tools.session_id is not None and self.intent is None and re.search(
            r"\b(session|attempts|accuracy|shooting percentage|how did i (?:do|shoot)|how many (?:shots|did i make|did i miss))\b",
            question, re.I,
        ):
            self.intent = "shot"
        if comparison and self.intent != "pain":
            self.intent = "compare"
        self.visual_consistency = bool(CONSISTENCY.search(question)) and self.intent in ("compare", "visual")
        self.visual_outcome_pair = bool(OUTCOME_PAIR.search(question)) and self.intent in ("compare", "visual")
        self.session_assessment = (
            self.intent == "shot" and bool(self.session and self.session.get("status") == "available")
            and bool(SESSION_ASSESSMENT.search(question)) and not EXERCISE_REQUEST.search(question)
        )
        self.explanation_only = bool(
            self.session_assessment or (
                not EXERCISE_REQUEST.search(question)
                and (self.intent == "explain_miss" or self.intent == "shot" and EXPLANATION_REQUEST.search(question))
            )
        )
        self.memory = memory
        self.practice_context = memory.get("preferences", {}).get("practice", {})
        for turn in history:
            if turn["role"] == "user":
                self.practice_context = merge_practice_constraints(self.practice_context, practice_constraints(turn["content"]))
        self.practice_context = merge_practice_constraints(self.practice_context, memory.get("preferences", {}).get("practice", {}))
        current_constraints = practice_constraints(question)
        self.practice_context = merge_practice_constraints(self.practice_context, current_constraints)
        self.focus = active_focus(memory)
        self.last_recommendation = memory["recommendations"][-1] if memory["recommendations"] else None
        feedback_focus = self.focus or (self.last_recommendation
                                        if self.intent in ("shot", "practice", "progress", "reassess") else None)
        self.feedback = next((report for report in reversed(memory["reports"])
                              if feedback_focus and report["focus_id"] == feedback_focus["id"]
                              and report["kind"] != "completed"), None)
        self.failed_topic = (feedback_focus["knowledge_id"] if self.feedback
                             and self.feedback["kind"] == "did_not_help" else None)
        difficulty_turn = self.focus and DIFFICULTY.fullmatch(question)
        if difficulty_turn:
            self.intent = "practice"
        self.difficult_topic = (self.focus["knowledge_id"] if self.focus and self.feedback
                                and self.feedback["kind"] == "difficulty"
                                and current_constraints.get("easier") is not False else None)
        self.easier_topic = self.difficult_topic
        if self.focus and self.focus.get("easier_after_feedback") and current_constraints.get("easier") is not False:
            self.easier_topic = self.focus["knowledge_id"]
        self.progress_records = {}
        self.session_pair = tuple(dict.fromkeys(int(value) for match in re.findall(
            r"\bsessions?\s*#?(\d+)\b(?:\s+(?:and|vs\.?|versus|&)\s*#?(\d+)\b)?", question, re.I,
        ) for value in match if value)) if self.intent == "progress" else ()
        self.comparison_camera = ("changed" if re.search(
            r"\bdifferent (?:camera(?: angle| view)?|viewpoint)|\bcamera (?:angle |view )?changed\b", question, re.I,
        ) else "unknown")
        self.different_distance = bool(re.search(r"\b(?:different (?:distance|distances|spots)|"
                                                  r"moved (?:farther|closer|back))\b", question, re.I))
        self.frames = {}
        self.images = {}
        self.observations = {}
        self.shot_summaries = {}
        self.observation_topics = {}
        self.history_summary = self.tools.player_history(include_recent=False)
        self.profile = None
        self.pair = None
        self.requested_pair = tuple(comparison)
        self.denied_pair = False
        self.explicit_selection_unavailable = self.tools.selection_unavailable or self.tools.session_unavailable
        self.anchor = self.referenced_shot(history, self.tools.selected)
        numbered = self.tools.recording_shots or self.tools.session_shots
        attempts = []
        numbers = re.findall(r"\b(?:attempt|shot)s?\s*#?(\d+)\b(?:\s+(?:and|vs\.?|versus|&)\s*#?(\d+)\b)?",
                             question, re.I)
        for number in (part for match in numbers for part in match if part):
            matches = [shot for shot in numbered if shot.shot_number == int(number)]
            if len(matches) == 1 and matches[0] not in attempts:
                attempts.append(matches[0])
        if attempts and (self.visual_requested or self.intent == "compare") and not comparison:
            self.anchor = attempts[0]
            if len(attempts) == 2:
                self.requested_pair = tuple(shot.shot_id for shot in attempts)
                self.intent = "compare"
        if self.tools.session_id is not None and not comparison:
            if self.anchor not in self.tools.session_shots:
                self.anchor = None
            candidates = self.tools.recording_shots or self.tools.session_shots
            if not self.anchor and candidates:
                self.anchor = candidates[0]
        elif not self.anchor and self.tools.shots and self.intent in ("shot", "practice", "progress", "reassess", "strengths", "visual"):
            self.anchor = self.tools.shots[-1]
        self.knowledge_ids = search_knowledge(question)
        if self.intent in ("shot", "practice") and self.knowledge_ids == ["routine"] and memory["goal"] and (
            not FREE_THROW_CONCERN.search(question)
        ):
            goal_topics = [topic for topic in search_knowledge(memory["goal"])
                           if topic not in ("scoring", "free_throw")]
            if goal_topics:
                self.knowledge_ids = goal_topics
        self.requested_practice_topics = explicit_topics(question) if self.intent in ("shot", "practice") else []
        if self.intent == "practice" and self.difficult_topic and not self.requested_practice_topics:
            self.requested_practice_topics = [self.difficult_topic]
        self.requested_practice_topic = self.requested_practice_topics[0] if self.requested_practice_topics else None
        self.general_topic = self.requested_practice_topic or (
            "individual" if re.search(r"unconventional|unusual|form.*effective|different.*form", question, re.I) else None
        ) or (
            self.knowledge_ids[0] if self.knowledge_ids[0] == "mechanics" else None
        ) or (
            explicit_topic(memory["goal"]) if not FREE_THROW_CONCERN.search(question) else None
        ) or "routine"
        flight_topic = self.flight_topic() if self.intent in ("explain_miss", "shot", "practice") else None
        if flight_topic:
            # The question gave no topic, but the selected miss's ball path does: lead with it.
            if self.knowledge_ids == ["routine"] and not explicit_topics(question):
                self.knowledge_ids = []
            self.knowledge_ids.insert(0, flight_topic)
            self.add_knowledge(KNOWLEDGE[flight_topic].get("parent"))
        self.add_knowledge(self.general_topic)
        if "routine" not in self.knowledge_ids:
            self.knowledge_ids.append("routine")
        # An evidence-free saved suggestion should not steer unrelated questions toward its topic.
        if self.steering_focus and self.steering_focus["knowledge_id"] in KNOWLEDGE:
            self.add_knowledge(self.steering_focus["knowledge_id"])
        if self.intent in ("power", "pain"):
            self.add_knowledge({"power": "distance", "pain": "safety"}[self.intent])

    @staticmethod
    def evidence_free(recommendation, memory):
        """A general suggestion with no player evidence and no player report about it."""
        return bool(recommendation) and not recommendation.get("evidence_ids") and (
            recommendation.get("guidance_basis") != "personal_pattern") and not any(
            report.get("focus_id") == recommendation.get("id") for report in memory.get("reports", []))

    @property
    def steering_focus(self):
        """The saved focus, unless it is an evidence-free suggestion and this is an investigation."""
        if self.plan_requested:
            return self.focus
        return None if self.evidence_free(self.focus, self.memory) else self.focus

    @property
    def plan_requested(self):
        """The player is asking about the saved plan itself: progress, feedback, advancing or what next."""
        return (self.intent in ("progress", "reassess") or self.review_requested
                or bool(ADVANCE_REQUEST.search(self.question) or NEXT_FOCUS.search(self.question)
                        or SAVED_PLAN.search(self.question)))

    def flight_topic(self):
        """Map the selected missed shot's saved ball path to the matching miss-investigation topic."""
        if not self.anchor or self.anchor.outcome != "missed":
            return None
        geometry = shot_evidence(self.anchor)["ball_flight"].get("path_relative_to_rim") or {}
        side, view = geometry.get("crossing_side_along_travel"), geometry.get("camera_view_estimate")
        if view == "front_or_rear_likely":
            return "lateral_miss"
        if view == "side_on_likely" and side:
            return "short_miss" if side == "before_rim_centre" else "long_miss"
        return None

    def add_knowledge(self, key):
        if not key:
            return
        if key not in self.knowledge_ids:
            self.knowledge_ids.append(key)

    @property
    def review_requested(self):
        return self.intent in ("progress", "reassess") or bool(NEXT_FOCUS.search(self.question))

    @cached_property
    def objective_progress(self):
        reviewed = self.focus or (self.last_recommendation if self.intent == "reassess" or (
            self.intent == "progress" and re.search(
                r"\b(?:last|previous) (?:cue|adjustment|drill|exercise)\b|\bdid it help\b|"
                r"\b(?:cue|adjustment|drill|exercise)\b[^.!?]{0,48}\bhelp\b", self.question, re.I,
            )) else None)
        return assess_progress(self.tools.shots, reviewed, self.memory["reports"], self.tools.session_id,
                               camera=self.comparison_camera, different_distance=self.different_distance)

    @cached_property
    def progress(self):
        metric = KNOWLEDGE.get(explicit_topic(self.question), {}).get("metric")
        if (not self.session_pair and self.objective_progress["status"] != "no_focus"
                and (not metric or self.objective_progress.get("field") == metric)):
            return self.objective_progress
        return self.session_progress() if self.review_requested else {"status": "no_focus"}

    def session_progress(self, field="", before_id=None, after_id=None):
        topic = explicit_topic(self.question)
        field = field or KNOWLEDGE.get(topic, {}).get("metric") or "release_elbow_angle"
        before_id = before_id or (self.session_pair[0] if len(self.session_pair) >= 2 else None)
        after_id = after_id or (self.session_pair[-1] if self.session_pair else self.tools.session_id)
        return compare_sessions(self.tools.shots, self.anchor, field, before_id=before_id, after_id=after_id,
                                camera=self.comparison_camera, different_distance=self.different_distance)

    @cached_property
    def next_practice_dose(self):
        focus = self.focus
        if (not focus or not ADVANCE_REQUEST.search(self.question) or not self.feedback
                or self.feedback["kind"] != "helped" or not self.objective_progress.get("completed")
                or (self.objective_progress.get("assessment") or {}).get("overall") in ("mixed", "unfavorable")
                or self.practice_context.get("easier")):
            return None
        options = eligible_drills(focus["knowledge_id"], self.drill_constraints(focus["knowledge_id"]), self.memory)
        drill = next((item for item in options if item["id"] == focus.get("drill_id")), None)
        dose = focus.get("prescribed_dose")
        if not drill or not dose or dose["repetitions"] >= drill["dose_range"]["repetitions"][-1]:
            return None
        reps = dose["repetitions"] + 1
        seconds = max(dose["duration_seconds"], dose["sets"] * dose["repetitions"] * (
            15 if "hoop" in drill["required_equipment"] else 5
        ))
        duration = (seconds * reps + dose["repetitions"] - 1) // dose["repetitions"]
        if duration > min(600, self.practice_context.get("available_time_seconds", 600)):
            return None
        return {"sets": dose["sets"], "repetitions": reps, "duration_seconds": duration}

    def ranked_patterns(self):
        """Rank already-qualified associations; never manufacture a new association.

        All candidates passed the existing measurement/profile reliability gates.
        Effect size and group support rank before goal or previous-focus preferences.
        Repeated usable attempts supply recurrence evidence, not causation.
        """
        if self.general_topic == "individual":
            return []
        candidates = []
        for key, observation in self.observations.items():
            if not key.startswith("pattern:"):
                continue
            topic = self.observation_topics[key]
            if self.requested_practice_topics and topic not in self.requested_practice_topics:
                continue
            if topic == self.failed_topic:
                continue
            data = observation.technical or {}
            effect = data.get("effect_size")
            support = min(data.get("n_made", 0), data.get("n_missed", 0))
            contributing_ids = data.get("made_shot_ids", []) + data.get("missed_shot_ids", [])
            sessions = {shot.session_id for shot_id in contributing_ids
                        if (shot := self.tools.resolve(shot_id))}
            # No order-dependent tie breaking and no previous recommendation bonus
            # without current qualified evidence for that topic.
            rank = (-abs(effect) if number(effect) else 0, -support, -len(sessions),
                    topic != self.general_topic,
                    not (self.focus and topic == self.focus["knowledge_id"]), key)
            candidates.append((rank, key))
        return [key for _, key in sorted(candidates)]

    def priority(self):
        patterns = self.ranked_patterns()
        if patterns:
            key = patterns[0]
            return self.observation_topics[key], [key], (
                "Qualified personal association ranked by effect size and usable make/miss support; "
                "explicit technique scope and unsuccessful-practice reports respected."
            )
        if self.general_topic == self.failed_topic:
            return None, [], "The relevant previous cue was unsuccessful; clarify before repeating it."
        return self.general_topic, [], (
            "No eligible personal association for this request; use the explicit technique or stated goal, "
            "otherwise a general routine. This is not a personalized correction."
        )

    def primary_measurements(self):
        """Rank valid observations for the selected attempt without assigning a fault."""
        if not self.anchor or self.requested_pair or self.session_pair:
            return []
        requested = explicit_topics(self.question)
        prefix = f"shot:{self.anchor.shot_id}:"
        keys = [prefix + field for field in FORM_FIELDS if prefix + field in self.observations]
        if requested:
            keys = [key for key in keys if self.observation_topics[key] in requested]
        return sorted(keys, key=lambda key: (
            -(self.observations[key].technical["reliability"].get("joint_coverage_pct") or 0),
            -(self.observations[key].technical.get("sample_frames") or 0),
        ))[:2]

    def drill_recommendation(self, topic=None):
        if self.explanation_only or re.search(r"\bno drills?|\b(?:don't|do not) (?:give|recommend|suggest).{0,15}\bdrill", self.question, re.I):
            return None
        explicit = EXERCISE_REQUEST.search(self.question)
        if not explicit and self.intent not in ("shot", "practice"):
            return None
        topic = topic if topic is not None else self.priority()[0]
        if topic == "individual" and not explicit:
            return None
        selected = select_drill(topic, self.drill_constraints(topic), self.memory)
        if self.next_practice_dose and topic == self.focus["knowledge_id"]:
            current = next(item for item in eligible_drills(topic, self.drill_constraints(topic), self.memory)
                           if item["id"] == self.focus["drill_id"])
            return {**selected, **current, "coaching_cues": [self.focus["cue"]],
                    "suggested_dose": self.next_practice_dose}
        if selected and self.easier_topic == topic and selected["id"] == self.focus.get("drill_id"):
            previous = self.focus.get("prescribed_dose")
            if previous:
                dose = selected["suggested_dose"]
                sets = min(dose["sets"], previous["sets"])
                reps = min(dose["repetitions"], previous["repetitions"])
                if self.difficult_topic == topic and sets * reps >= previous["sets"] * previous["repetitions"]:
                    if sets > 1:
                        sets -= 1
                    elif reps > 1:
                        reps -= 1
                seconds_per_rep = dose["duration_seconds"] // (dose["sets"] * dose["repetitions"])
                selected["suggested_dose"] = {"sets": sets, "repetitions": reps,
                                              "duration_seconds": sets * reps * seconds_per_rep}
        return selected

    def drill_constraints(self, topic):
        if self.easier_topic and self.easier_topic == topic:
            return {**self.practice_context, "easier": True}
        return self.practice_context

    def supported_strengths(self):
        """Conservative strengths from existing summaries, with no ideal-angle claims."""
        result = []
        if self.session and self.session.get("status") == "available":
            for field, data in self.session["measurements"].items():
                if data["sample"] > 1 and data["min"] == data["max"]:
                    key = f"session:{self.tools.session_id}:{field}"
                    result.append(Observation(
                        text=f"Your measured {MEASUREMENTS[field]['name'].lower()} was consistent across {data['sample']} usable attempts.",
                        evidence_ids=[key], technical={"field": field, **data},
                    ))
            made = self.session["made"]
            known = made + self.session["missed"]
            scope = "this session"
        else:
            counts = self.history_summary["counts"]
            made, known, scope = counts["made"], counts["made"] + counts["missed"], "your history"
        if made:
            result.append(Observation(
                text=f"There are {made} recorded makes out of {known} known outcomes in {scope}. That records successful outcomes, not proof of ideal mechanics.",
                evidence_ids=[f"session:{self.tools.session_id}:outcome_counts" if self.session else "history:outcome_counts"],
            ))
        return result[:3]

    def referenced_shot(self, history, selected):
        # Match owned identifiers as complete tokens only. Prior discussion can
        # supply a reference when the current question does not identify a shot.
        for message in [self.question] + ([] if selected else [turn["content"] for turn in reversed(history)]):
            tokens = set(re.findall(r"[A-Za-z0-9_-]+", message))
            match = next((shot for shot in self.tools.shots
                          if shot.shot_id in tokens or shot.video_id in tokens), None)
            if match:
                return match
        return selected

    def collect(self, multimodal=True, *, prepare_examples=True):
        if self.intent == "pain" or self.explicit_selection_unavailable:
            return
        requested = self.requested_pair
        if not requested and self.intent == "compare":
            requested = tuple(dict.fromkeys(
                shot.shot_id for token in re.findall(r"[A-Za-z0-9_-]+", self.question)
                if (shot := self.tools.resolve(token))
            ))
        if len(requested) == 2:
            self.requested_pair = requested
            self.retrieve_comparison(*requested)
        elif not self.visual_outcome_pair and self.tools.session_id is None and self.intent in ("explain_miss", "compare") and self.anchor and (
            self.intent == "explain_miss" or re.search(r"make.*miss|miss.*make", self.question, re.I)
        ):
            self.retrieve_make_miss(self.anchor.shot_id)
        if self.anchor and (self.intent or self.requested_pair) and not self.session_pair:
            self.retrieve_shot(self.anchor.shot_id)
            if self.intent == "explain_miss" and self.session and self.session["status"] == "available":
                self.add_session_flight_observation()
            if self.intent in ("shot", "explain_miss", "practice", "progress", "reassess") or (
                self.intent == "compare" and self.tools.session_id is not None and not self.requested_pair
            ):
                self.retrieve_profile()
            if prepare_examples and not (self.visual_requested or self.visual_outcome_pair or self.visual_consistency
                                         or self.visual_across_sessions) and not self.requested_pair and self.intent in (
                "shot", "explain_miss", "practice", "compare",
            ):
                self.prepare_representative_comparison()
        if self.intent == "strengths":
            for observation in self.supported_strengths():
                key = observation.evidence_ids[0]
                self.observations[key] = observation
                self.observation_topics[key] = "individual"
        if self.resource_request and not self.denied_pair:
            self.offer_resources(self.question, self.resource_request)
        if self.intent in ("shot", "practice", "reassess") and not self.requested_pair and not self.denied_pair:
            detail = next((key for key in self.knowledge_context() if parent_topic(key) != key), None)
            if detail:
                self.add_knowledge(detail)

    def select_frames(self):
        if not (self.visual_requested or self.intent in ("visual", "compare") or self.requested_pair):
            return
        if self.review_requested and self.progress["status"] == "available":
            self.select_progress_frames()
            return
        topics = explicit_topics(self.question)
        measured = self.primary_measurements() if not topics and self.visual_requested else []
        topic = next((item for item in topics if item in VISUAL_FOCUS),
                     self.observation_topics[measured[0]] if measured else (topics or self.knowledge_ids)[0])
        focus = VISUAL_FOCUS.get(topic, "")
        phases = PHASES.get(topic, ("release",))
        named = tuple(phase for phase, pattern in NAMED_PHASES.items()
                      if re.search(rf"\b(?:{pattern})\b", self.question, re.I))
        first, second = self.anchor, None
        if self.pair and not self.visual_outcome_pair:
            first, second = (self.tools.resolve(self.pair[key]["shot_id"]) for key in ("first", "second"))
        elif self.visual_outcome_pair or self.visual_consistency or self.visual_across_sessions:
            first, second = self.visual_examples(focus)
            if second and not self.pair:
                self.register_pair(self.tools.compare_shots(first.shot_id, second.shot_id))
        if first and (second or not (self.requested_pair or self.visual_outcome_pair
                                     or self.visual_consistency or self.visual_across_sessions)):
            if not second and self.intent == "compare" and len(named) < 2:
                return
            if named and (second or len(named) >= 2):
                phases = named
                if not focus and any(phase.startswith("knee_") for phase in phases):
                    focus = "knee"
            if not second and len(phases) == 1 and topic == "routine":
                phases = ("preparation", "release", "follow_through")
            self.retrieve_frames(first.shot_id, ",".join(phases), focus=focus,
                                 second_shot_id=second.shot_id if second else "",
                                 from_phase=phases[0] if len(phases) == 2 and not second else "")

    def select_progress_frames(self):
        field = self.progress.get("field")
        if (self.progress.get("assessment") or {}).get("camera") == "changed":
            return
        topic = METRIC_GUIDANCE.get(field)
        phase = {"knees": "knee_dip", "finish": "follow_through", "timing": "release"}.get(topic, "release")
        before = self.progress["before_shot_ids"][:3]
        after = self.progress["after_shot_ids"][:3]
        # The first decodable pair for the same phase is an illustration of the two samples.
        for first, second in zip(before, after):
            if self.retrieve_frames(first, phase, VISUAL_FOCUS.get(topic, ""), second)["frames"]:
                return

    def visual_examples(self, focus):
        """Choose comparison examples for the local fallback."""
        if self.requested_pair and self.pair:
            candidates = [self.tools.resolve(self.pair[key]["shot_id"]) for key in ("first", "second")]
        else:
            candidates = self.tools.shots if self.visual_across_sessions else (
                self.tools.recording_shots or self.tools.session_shots or self.tools.shots
            )
        if self.visual_outcome_pair:
            candidates = [shot for shot in candidates if shot.outcome_source == "manual"]
        sources = {video_id: video_source(video_id) for video_id in {shot.video_id for shot in candidates}}
        candidates = [shot for shot in candidates if (source := sources[shot.video_id])
                      and (not focus or source[0] != "annotated video")]
        firsts = ([self.anchor] if self.anchor in candidates else []) + list(reversed(candidates))
        for first in firsts:
            for second in reversed(candidates):
                if first == second or (self.visual_across_sessions and first.session_id == second.session_id):
                    continue
                if self.visual_outcome_pair and {first.outcome, second.outcome} != {"made", "missed"}:
                    continue
                if first.conditions == second.conditions:
                    return first, second
        return None, None

    def retrieve_shot(self, shot_id: str = "") -> dict:
        """Read one owned shot by recording or shot ID, or read the current selection."""
        shot = self.tools.resolve(shot_id) if shot_id else self.anchor
        if not shot or (self.requested_pair and not self.in_requested_pair(shot)) or (
                        self.tools.session_id is not None and not self.requested_pair
                        and shot not in self.tools.session_shots):
            return {"status": "unavailable"}
        evidence = self.tools.shot_analysis(shot.shot_id)
        prefix = evidence["id"]
        self.add_outcome(evidence)
        measurements = evidence["measurements"]
        for field, data in measurements.items():
            if data["status"] != "valid":
                continue
            value = data["value"]
            if field in PLAIN_OBSERVATIONS and value > 0:
                text = PLAIN_OBSERVATIONS[field]
            else:
                text = f"{MEASUREMENTS[field]['name'].capitalize()} was {value:g} {data['unit']} in this shot."
            key = f"{prefix}:{field}"
            self.observations[key] = Observation(text=text, evidence_ids=[key], technical={
                **data, **MEASUREMENTS[field], "shot_id": shot.shot_id,
                "provenance": evidence["provenance"], "session_id": shot.session_id,
            })
            self.observation_topics[key] = METRIC_GUIDANCE.get(field, "recording")
        valid_form = [field for field in FORM_FIELDS if measurements[field]["status"] == "valid"]
        quality = shot.analysis.get("biomechanics", {}).get("measurement_quality")
        if not valid_form or quality == "review":
            key = f"{prefix}:limited"
            text = ("Some pose measurements are too limited to use. We can still review the parts that were tracked."
                    if valid_form else "The pose results for this clip are too limited to judge your shooting movement.")
            self.observations[key] = Observation(text=text, evidence_ids=[key])
            self.observation_topics[key] = "recording"
            self.add_knowledge("recording")
        evidence["observation_ids"] = [key for key in self.observations if key.startswith(prefix + ":")]
        self.shot_summaries[shot.shot_id] = evidence
        return evidence

    def add_session_flight_observation(self):
        misses = [shot for shot in self.tools.session_shots if shot.outcome == "missed"]
        supported = [shot.shot_id for shot in misses if shot.analysis.get("shot_outcome", {}).get(
            "observation"
        ) == "clear_lateral_miss_candidate"]
        if not supported:
            return
        key = f"session:{self.tools.session_id}:miss_flight"
        text = (f"The 2D ball tracker saw the ball pass beside the rim on {len(supported)} "
                f"of {len(misses)} attempts labelled missed. That describes the flight we could observe.")
        self.observations[key] = Observation(text=text, evidence_ids=[key], technical={
            "session_id": self.tools.session_id, "shot_ids": supported, "sample_shots": len(supported),
            "labelled_misses": len(misses), "provenance": "experimental 2D rim crossing detector",
        })
        self.observation_topics[key] = "distance"

    def add_outcome(self, evidence):
        key = evidence["id"] + ":outcome"
        outcome = evidence["outcome"]
        label = evidence["outcome_source"]
        if outcome == "unknown":
            text = "The result of this shot is unconfirmed."
        elif label == "player label":
            text = f"You recorded this shot as {outcome}."
        else:
            text = f"The ball tracker estimates this shot was {outcome}."
        geometry = evidence.get("ball_flight", {}).get("path_relative_to_rim") or {}
        if outcome == "missed" and geometry.get("interpretation"):
            text += " " + geometry["interpretation"]
        self.observations[key] = Observation(text=text, evidence_ids=[key], technical={
            "outcome": outcome, "outcome_source": label, "shot_id": evidence["shot_id"],
            "provenance": evidence["provenance"],
            **({"ball_path": geometry} if outcome == "missed" and geometry else {}),
        })
        self.observation_topics[key] = "individual"

    def retrieve_comparison(self, first_id: str, second_id: str) -> dict:
        """Compare two chosen attempts in the current scope in order, even if no association is established."""
        if self.requested_pair and self.pair:
            first, second = self.tools.resolve(first_id), self.tools.resolve(second_id)
            if not first or not second or (first.shot_id, second.shot_id) != (
                self.pair["first"]["shot_id"], self.pair["second"]["shot_id"]
            ):
                return {"status": "unavailable"}
        if self.tools.session_id is not None and not self.requested_pair:
            if any(self.tools.resolve(key) not in self.tools.session_shots for key in (first_id, second_id)):
                return {"status": "unavailable"}
        pair = self.tools.compare_shots(first_id, second_id)
        if pair["status"] == "available":
            self.register_pair(pair, select=self.tools.session_id is None or bool(self.requested_pair))
        elif self.requested_pair:
            self.denied_pair = True
        return pair

    def retrieve_make_miss(self, shot_id: str = "") -> dict:
        """Find an opposite-outcome example with matching recorded conditions in the current scope."""
        if self.requested_pair:
            return {"status": "unavailable"}
        pair = self.tools.make_miss_pair(shot_id or (self.anchor.shot_id if self.anchor else ""))
        if pair["status"] == "available":
            self.register_pair(pair, select=self.tools.session_id is None)
        return pair

    def register_pair(self, pair, *, select=True):
        if select:
            self.pair = pair
        for evidence in (pair["first"], pair["second"]):
            self.add_outcome(evidence)
        for field, numbers in pair["differences"].items():
            key = f"{pair['id']}:{field}"
            delta = numbers["second_minus_first"]
            label = MEASUREMENTS[field]["name"]
            text = (f"The measured {label.lower()} was the same in both clips." if not delta else
                    f"The second clip had a {'higher' if delta > 0 else 'lower'} measured {label.lower()}.")
            self.observations[key] = Observation(text=text, evidence_ids=[key], technical={
                **numbers, "field": field, "shot_ids": [pair["first"]["shot_id"], pair["second"]["shot_id"]],
                "matched_recorded_conditions": pair["matched_recorded_conditions"],
            })
            self.observation_topics[key] = METRIC_GUIDANCE[field]
        pair["observation_ids"] = [key for key in self.observations if key.startswith(pair["id"] + ":")]

    def retrieve_profile(self) -> dict:
        """Retrieve the current player's supported form-to-outcome associations."""
        profile_anchor = self.anchor
        if self.tools.session_id is not None:
            self.profile = self.tools.session_profile
        elif self.review_requested and profile_anchor:
            self.profile = personal_profile(
                [shot for shot in self.tools.shots if shot.session_id == profile_anchor.session_id], profile_anchor,
            )
        else:
            self.profile = self.tools.form_profile() if profile_anchor == self.tools.selected else personal_profile(
                self.tools.shots, profile_anchor
            )
        for field in self.profile.get("likely_patterns", []):
            result = self.profile["features"][field]
            fingerprint = hashlib.sha256(json.dumps(
                [self.tools.player, self.tools.session_id, self.profile["conditions"], result], sort_keys=True
            ).encode()).hexdigest()[:16]
            key = f"pattern:{field}:{fingerprint}"
            label = MEASUREMENTS[field]["name"]
            direction = "higher" if result["direction"] == "higher_on_makes" else "lower"
            if field in ("min_knee_angle", "release_elbow_angle"):
                body = ("knee at its deepest bend" if field == "min_knee_angle" else
                        "shooting elbow at estimated release")
                movement = f"your {body} looked {'straighter' if direction == 'higher' else 'more bent'}"
            else:
                movement = f"the measured {label.lower()} tended to be {direction}"
            text = (f"On your recorded makes, {movement} than on your misses "
                    f"({result['n_made']} makes and {result['n_missed']} misses with usable measurements).")
            self.observations[key] = Observation(text=text, evidence_ids=[key], technical={
                **result, "field": field, "unit": MEASUREMENTS[field]["unit"],
                "conditions": self.profile["conditions"], "provenance": self.profile["provenance"],
                "auto_label_count": self.profile["auto_label_count"],
            })
            self.observation_topics[key] = METRIC_GUIDANCE[field]
            self.add_knowledge(METRIC_GUIDANCE[field])
        return self.profile_summary()

    def profile_summary(self):
        return {
            **{key: value for key, value in self.profile.items() if key != "features"},
            "features": {field: {key: value[-12:] if key.endswith("_shot_ids") else value
                                 for key, value in data.items()}
                         for field, data in self.profile.get("features", {}).items()},
            "observation_ids": [key for key in self.observations if key.startswith("pattern:")],
        }

    def retrieve_session(self) -> dict:
        """Read the current session's attempt counts, outcome coverage and form variability."""
        return self.session or {"status": "unavailable"}

    def retrieve_attempts(self, outcome: str = "", offset: int = 0) -> dict:
        """List up to twenty session attempts, optionally filtered to made, missed or unknown."""
        return self.tools.session_attempts(outcome, offset)

    def retrieve_historical_profile(self) -> dict:
        """Review up to three earlier compatible sessions and look for recurring associations."""
        anchor = self.anchor or (self.tools.shots[-1] if self.tools.shots else None)
        if not anchor:
            return {"status": "unavailable"}
        sessions = list(dict.fromkeys(shot.session_id for shot in self.tools.shots))
        earlier = sessions[:sessions.index(anchor.session_id)]
        groups = {}
        for shot in self.tools.shots:
            if shot.session_id in earlier and comparable(shot, anchor):
                groups.setdefault(shot.session_id, []).append(shot)
        groups = dict(list(groups.items())[-3:])
        history = [shot for group in groups.values() for shot in group]
        result = personal_profile(history, anchor)
        reviewed = {}
        for session_id, group in groups.items():
            profile = personal_profile([shot for shot in group if shot.outcome_source == "manual"], anchor)
            reviewed[session_id] = {
                field: {key: profile["features"][field][key] for key in ("direction", "n_made", "n_missed")}
                for field in profile.get("likely_patterns", ())
            }
        recurrence = {}
        for field in FORM_FIELDS:
            directions = {session_id: patterns[field]["direction"] for session_id, patterns in reviewed.items()
                          if field in patterns}
            if len(directions) >= 2:
                recurrence[field] = {"sessions": directions,
                                     "status": "recurring" if len(set(directions.values())) == 1 else "mixed"}
        return {key: value for key, value in result.items() if key != "features"} | {
            "sessions_reviewed": list(groups), "session_associations": reviewed, "recurrence": recurrence,
            "recurrence_outcome_source": "player-confirmed outcomes",
            "features": {field: {key: value[-10:] if key.endswith("_shot_ids") else value
                                 for key, value in data.items()}
                         for field, data in result.get("features", {}).items()}
        }

    def retrieve_representative_comparison(self, evidence_id: str = "") -> dict:
        """Read verified made/missed examples for a specific current association ID."""
        if self.requested_pair:
            return {"status": "unavailable"}
        key = evidence_id or next(iter(self.pattern_frames), "")
        if not key.startswith("pattern:") or key not in self.observations:
            return {"status": "unavailable"}
        self.prepare_representative_comparison(key)
        frames = self.pattern_frames.get(key, ())
        if not frames:
            return {"status": "unavailable"}
        return {"status": "available", "association_id": key,
                "comparison": self.pair, "frames": [self.frames[frame].public() for frame in frames]}

    def prepare_representative_comparison(self, evidence_id=None):
        if not self.profile:
            return
        if evidence_id is None:
            candidates = self.ranked_patterns()
            if not candidates:
                return
            evidence_id = candidates[0]
            field = self.observations[evidence_id].technical["field"]
            self.session_pattern_id = evidence_id
        else:
            field = self.observations[evidence_id].technical["field"]
        selection = representative_pair(self.tools, self.profile, field)
        if selection:
            pair, images = selection
            self.register_pair(pair)
            self.pattern_frames[evidence_id] = [ref.id for ref, _ in images]
            for ref, image in images:
                self.frames[ref.id] = ref
                self.images[ref.id] = image
            self.observations[evidence_id].video_reference_ids = self.pattern_frames[evidence_id]

    def retrieve_history(self, outcome: str = "") -> dict:
        """List recent owned recordings and distinguish labelled results from unknown ones."""
        return self.tools.player_history(outcome)

    def knowledge_context(self):
        """Rank existing evidence and stated preferences without inferring a technique fault."""
        patterns = [self.observation_topics[key] for key in self.ranked_patterns()]
        measured = [self.observation_topics[key] for key, observation in self.observations.items()
                    if observation.technical and observation.technical.get("status") == "valid"]
        question = search_knowledge(self.question, limit=1, default_to_routine=False, resource_query=True)
        goal = search_knowledge(self.memory["goal"], default_to_routine=False)
        focus = self.steering_focus["knowledge_id"] if self.steering_focus else None
        failed = bool(self.feedback and self.feedback["kind"] == "did_not_help")
        measurement_details = {"knees": "knee_dip_depth", "arm": "forearm_support",
                               "finish": "hold_finish", "timing": "one_rise"}
        measured_details = [measurement_details[topic] for topic in dict.fromkeys(patterns + measured)
                            if topic in measurement_details]
        # A measured angle informs what to review, not which technique to prescribe.
        beginner = self.memory["experience"].casefold() in ("beginner", "new to basketball")
        experience_detail = "close_first" if beginner and self.intent in ("practice", "shot") else None
        reassessment = "failed_cue_reassessment" if failed else None
        return list(dict.fromkeys(key for key in [*question, reassessment, *goal, *patterns, focus,
                                                  *measured_details[:1], experience_detail, *measured,
                                                  "mechanics", "routine"]
                                  if key in KNOWLEDGE and not (failed and key == focus)))

    def offer_resources(self, query, kind):
        if self.resource_optout or self.intent == "pain" or self.denied_pair or self.explicit_selection_unavailable:
            return []
        topics = search_knowledge(query, default_to_routine=False, context_topics=self.knowledge_context(),
                                  resource_query=True)
        if not topics and (not query or CONTEXTUAL_RESOURCE_REQUEST.search(query)):
            for turn in reversed(self.history):
                if turn["role"] == "user" and (topics := search_knowledge(
                    turn["content"], default_to_routine=False, resource_query=True,
                )):
                    break
            if not topics:
                measured = self.primary_measurements()
                topics = ([self.observation_topics[measured[0]]] if measured else self.knowledge_context()[:1])
        resource_topics = topics[:2]
        if resource_topics and parent_topic(resource_topics[0]) != resource_topics[0]:
            resource_topics = resource_topics[:1]
        choices = find_resources(query, resource_topics, kind, experience=self.memory.get("experience", ""), history=self.history)
        for resource, topic in choices:
            self.resources[resource.id] = (resource, topic)
            self.add_knowledge(topic)
        return choices

    def retrieve_knowledge(self, topic: str = "", resource_kind: ResourceKind = "") -> dict:
        """Look up general principles by catalog ID or technique phrase. Use an empty topic for scoped
        coaching context. Set resource_kind to video, article or any when a verified example would help."""
        context = self.knowledge_context()
        matches = (search_knowledge(topic, limit=2, default_to_routine=False, context_topics=context)
                   if topic else context[:2])
        for key in matches:
            self.add_knowledge(key)
        result = {"status": "available" if matches else "no_match",
                  "principles": {key: {field: value for field, value in supporting_context(key).items() if field != "drills"}
                                 for key in matches}}
        if resource_kind:
            requested = self.resource_request
            compatible = not requested or requested == "any" or resource_kind in (requested, "any")
            kind = requested if requested and requested != "any" else resource_kind
            choices = self.offer_resources(topic, kind) if compatible else []
            result["resources"] = [resource.summary(key) for resource, key in choices
                                   if resource_kind in ("any", resource.kind)]
            result["resource_status"] = "available" if result["resources"] else "no_match"
        return result

    def resource_relation(self, topic, evidence_ids, frame_ids):
        observation = next((self.observations[key] for key in evidence_ids
                            if self.observation_topics.get(key) == topic
                            and self.observations[key].technical
                            and (self.observations[key].technical.get("status") == "valid" or key.startswith("pattern:"))), None)
        if observation:
            field = observation.technical.get("field") or observation.technical.get("id")
            name = observation.technical.get("name") or MEASUREMENTS.get(field, {}).get("name")
            if name:
                return f"Use this example alongside your measured {name.lower()}."
        for key in frame_ids:
            ref = self.frames.get(key)
            if (ref and ref.phase in PHASES.get(topic, ()) and ref.annotation
                    and ref.annotation["focus"] == VISUAL_FOCUS.get(topic) and ref.annotation["marks"]):
                return f"Use the demonstration while reviewing the {ref.phase.replace('_', ' ')} frame from your attempt."
        return None

    def resource_card(self, resource_id, evidence_ids=(), frame_ids=(), *, include_exercise=True, note=None,
                      generic=True):
        resource, topic = self.resources[resource_id]
        parent = parent_topic(topic)
        relevance = note or self.resource_relation(parent, evidence_ids, frame_ids)
        item = KNOWLEDGE[topic]
        exercise = None
        if include_exercise and parent != self.failed_topic and not re.search(
            r"\b(?:no|skip|without) (?:drills?|exercises?)\b|\b(?:don['’]t|do not) (?:give|suggest|recommend)"
            r"\b[^.!?]*\b(?:drills?|exercises?)\b", self.question, re.I,
        ):
            drill = select_drill(parent, self.drill_constraints(parent), self.memory)
            if drill:
                exercise = ((item.get("application") or " ".join((item["progression"], item["evaluation"])))
                            if "hoop" in drill["required_equipment"]
                            else " ".join((drill["setup"], *drill["instructions"], drill["success_criteria"])))
        return InstructionalResource(id=resource.id, title=resource.title, kind=resource.kind,
                                     organization=resource.organization, creator=resource.creator, url=resource.url,
                                     section=resource.section, verified_on=REVIEWED_ON, watch_for=resource.watch_for,
                                     skill_levels=list(resource.skill_levels),
                                     exercise=exercise,
                                     thumbnail_url=resource.thumbnail_url, embed_url=resource.embed_url,
                                     relevance=relevance or (
                                         f"Use this as a general reference for {item['topic'].lower()}." if generic else ""))

    def retrieve_memory(self, topic: str = "", focus_id: str = "") -> dict:
        """Read stated preferences and one relevant recommendation with its player reports."""
        topics = search_knowledge(topic, limit=1, default_to_routine=False)
        focus = next((item for item in reversed(self.memory["recommendations"])
                      if (not focus_id or item["id"] == focus_id)
                      and (not topic or item["knowledge_id"] in topics)), None)
        return self.memory_summary(focus)

    def memory_summary(self, focus):
        details, reports = None, []
        if focus:
            details = {key: focus.get(key) for key in ("id", "title", "cue", "decision", "exercise", "field",
                       "knowledge_id", "drill_id", "prescribed_dose", "session_id", "recorded_at", "guidance_basis")}
            details.update(
                practice_instructions=(focus.get("practice_instructions") or "")[:400] or None,
                practice_evaluation=(focus.get("practice_evaluation") or "")[:240] or None,
                evidence_ids=focus.get("evidence_ids", [])[:3], provenance="coaching recommendation",
            )
            reports = [{**item, "text": item["text"][:260], "provenance": "player report"}
                       for item in self.memory["reports"] if item["focus_id"] == focus["id"]][-3:]
        return {"goal": self.memory["goal"], "experience": self.memory["experience"],
                "preferences": self.memory.get("preferences", {}), "focus": details,
                "recommendations": [{"id": details["id"], "title": details["title"]}] if details else [],
                "reports": reports}

    def prompt_memory(self):
        relevant = self.plan_requested or self.intent in ("shot", "practice", "explain_miss")
        plan = self.last_recommendation
        if plan and not self.plan_requested and self.evidence_free(plan, self.memory):
            plan = None  # An unsupported earlier suggestion is not evidence about this shot.
        summary = self.memory_summary(plan if relevant and not (self.requested_pair or self.session_pair) else None)
        if self.plan_requested or self.intent in ("practice", "shot", "progress", "reassess", "strengths"):
            summary["previous_advice"] = self.previous_advice(summary["focus"])
        return summary

    def previous_advice(self, focus, limit=4):
        """Earlier advice and how it went, so the coach builds on it instead of repeating it."""
        latest = {}
        for report in self.memory["reports"]:
            if report.get("kind") in ("completed", "helped", "did_not_help", "difficulty"):
                latest[report["focus_id"]] = report["kind"]
        current = (focus or {}).get("id")
        advice = {}
        for item in reversed(self.memory["recommendations"]):
            if item.get("id") == current:
                continue
            key = (item.get("title"), item.get("cue"))
            if key in advice:  # The same advice given again: count it, keep the latest record.
                advice[key]["times_given"] += 1
                advice[key]["player_report"] = advice[key]["player_report"] or latest.get(item["id"])
                continue
            advice[key] = {"title": item.get("title"), "cue": (item.get("cue") or "")[:140] or None,
                           "given": (item.get("recorded_at") or "")[:10] or None, "times_given": 1,
                           "player_report": latest.get(item["id"]),
                           "based_on": "this player's recordings" if item.get("evidence_ids") else "general guidance"}
        return list(advice.values())[:limit]

    def previous_plan(self):
        if self.last_recommendation and not self.session_pair:
            return {key: self.last_recommendation.get(key) for key in (
                "id", "title", "cue", "exercise", "practice_instructions", "prescribed_dose",
            )}
        return None

    def retrieve_progress(self, field: str = "", before_session_id: int = 0, after_session_id: int = 0) -> dict:
        """Review the current objective or compare owned sessions for a named movement metric."""
        if field and field not in FORM_FIELDS:
            return {"status": "unavailable"}
        progress = (self.session_progress(field, before_session_id, after_session_id)
                    if field or before_session_id or after_session_id or self.progress["status"] == "no_focus"
                    else self.progress)
        compact = {key: value[-3:] if key.endswith("_shot_ids") else value
                   for key, value in progress.items()}
        if compact["status"] == "available":
            self.progress_records[compact["id"]] = compact
        return compact

    def retrieve_frames(self, shot_id: str = "", phases: str = "", focus: Focus = "",
                        second_shot_id: str = "", from_phase: str = "") -> dict:
        """Get saved player frames. Choose comma-separated phases such as preparation, release,
        follow_through, knee_dip, knee_extension or post_release_extension. Choose elbow, knee
        or alignment to draw focused overlays where available. Supply second_shot_id for up to
        two matching phases across attempts. For movement within one attempt, request both
        phases and set from_phase to the earlier phase to mark visible image-plane displacement."""
        unavailable = {"frames": [], "status": "matching_visual_evidence_unavailable"}
        remaining = 6 - len(self.frames)
        if remaining < 1 or self.explicit_selection_unavailable or self.intent == "pain":
            return unavailable
        requested = tuple(dict.fromkeys(item.strip() for item in phases.split(",") if item.strip()))
        shot = self.tools.resolve(shot_id) if shot_id else self.anchor
        second = self.tools.resolve(second_shot_id) if second_shot_id else None
        shots = [shot, second] if second_shot_id else [shot]
        if any(not item or (self.requested_pair and not self.in_requested_pair(item)) or (
            self.tools.session_id is not None and not self.requested_pair and not self.visual_across_sessions
            and item not in self.tools.session_shots and not self.in_progress_scope(item)
        ) for item in shots):
            return unavailable
        if second_shot_id and second == shot:
            return unavailable
        if self.visual_outcome_pair and (not second or {shot.outcome, second.outcome} != {"made", "missed"}
                                         or any(item.outcome_source != "manual" for item in shots)):
            return unavailable
        if second:
            matching = (requested or ("release",))[:min(2, remaining // 2)]
            if not matching:
                return unavailable
            first_frames, second_frames = (
                {ref.phase: (ref, jpg) for ref, jpg in self.tools.video_frames(item.shot_id, matching, focus=focus)}
                for item in shots
            )
            results = [item for phase in matching if phase in first_frames and phase in second_frames
                       for item in (first_frames[phase], second_frames[phase])]
        else:
            requested = requested or ("preparation", "release", "follow_through")
            results = self.tools.video_frames(shot.shot_id, requested, focus=focus,
                                              from_phase=from_phase if from_phase in requested else "")
            unique = {}
            for ref, image in results:
                if ref.frame not in unique or focus == "elbow" and ref.phase == "release":
                    unique[ref.frame] = ref, image
            results = list(unique.values())[:min(3, remaining)]
        for ref, image in results:
            self.frames[ref.id] = ref
            self.images[ref.id] = image
        return {"frames": [ref.public() for ref, _ in results]} if results else unavailable

    def unique_frame_ids(self, ids):
        unique = {}
        for key in ids:
            ref = self.frames[key]
            # Different joint overlays of one frame are different visuals; plain aliases are not.
            unique.setdefault((ref.shot_id, ref.video_id, ref.frame, (ref.annotation or {}).get("focus")), key)
        return list(unique.values())

    def in_progress_scope(self, shot):
        records = list(self.progress_records.values()) + ([self.progress] if self.review_requested else [])
        return any(shot.shot_id in progress.get("before_shot_ids", ()) or
                   shot.shot_id in progress.get("after_shot_ids", ()) for progress in records)

    def in_requested_pair(self, shot):
        return bool(shot and self.pair and shot.shot_id in (self.pair["first"]["shot_id"], self.pair["second"]["shot_id"]))

    def practice_options(self):
        """Eligible topic and resource combinations. The author chooses the focus and drill."""
        resources = {}
        for topic in self.knowledge_ids:
            for item in eligible_drills(topic, self.drill_constraints(topic), self.memory):
                option = resources.setdefault(item["id"], {**item, "eligible_topics": []})
                option["eligible_topics"].append(topic)
        return resources

    def author_tools(self):
        tools = [self.retrieve_shot, self.retrieve_frames, self.retrieve_knowledge, self.retrieve_memory]
        if self.requested_pair:
            return tools + [self.retrieve_comparison]
        tools += [self.retrieve_history, self.retrieve_profile, self.retrieve_progress,
                  self.retrieve_comparison, self.retrieve_make_miss, self.retrieve_historical_profile]
        if self.session:
            return tools + [self.retrieve_session, self.retrieve_attempts,
                            self.retrieve_representative_comparison]
        return tools

    def visual_pair(self, frame_ids, tag):
        joint = tag.partition("_")[0]
        allowed = set(VISUAL_PHASES.get(joint, ())) | ({"knee_dip", "knee_extension"} if joint == "knee" else set())
        focus = "elbow" if joint == "arm" else joint
        # With several attached pairs, judge the tag on the frames that show its joint.
        refs = sorted((ref for ref in (self.frames[key] for key in frame_ids) if ref.phase in allowed
                       and (ref.annotation or {}).get("focus") in (None, focus)), key=lambda ref: ref.frame)
        phases = tuple(ref.phase for ref in refs)
        if len(refs) == 2 and refs[0].shot_id == refs[1].shot_id and (
            phases == VISUAL_PHASES.get(joint) or joint == "knee" and phases == ("knee_dip", "knee_extension")
        ):
            return refs
        return []

    def corroborate_visual(self, frame_ids, tag):
        refs = self.visual_pair(frame_ids, tag)
        if not refs:
            return None
        shot = self.tools.resolve(refs[0].shot_id)
        if not shot or not VIDEO_ID.fullmatch(shot.video_id):
            return None
        joint = "elbow" if tag.startswith("arm_") else "knee"
        field = {"elbow": "release_elbow_angle", "knee": "min_knee_angle"}[joint]
        evidence = self.tools.shot_analysis(shot.shot_id)
        if evidence["measurements"][field]["status"] != "valid":
            return None
        arm = shot.conditions.get("shooting_arm")
        try:
            path = angle_file(shot, ROOT / "outputs" / shot.video_id)
            with path.open(encoding="utf-8", newline="") as stream:
                frames = {int(row["frame"]): float(row[f"{arm}_{joint}_angle"])
                          for row in csv.DictReader(stream)
                          if int(row["frame"]) in {ref.frame for ref in refs}}
            a, b = (frames[ref.frame] for ref in refs)
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not all(number(angle) and 0 <= angle <= 180 for angle in (a, b)) or round(a, 2) == round(b, 2):
            return None
        part = "arm" if joint == "elbow" else "knee"
        return f"{part}_{'straightens' if b > a else 'bends'}"
