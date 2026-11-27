"""Curated coaching decisions with source principles and ShotCoach practice sets."""

import re

from backend.app.agent.knowledge_library import LIBRARY

USA = ("USA Basketball — 7 Tips To Improve Your Shooting Mechanics",
       "https://www.usab.com/news/2014/01/7-tips-to-improve-your-shooting-mechanics")
NBA_FORM = ("Jr. NBA — Form Shooting-2 Hands", "https://jr.nba.com/video/form-shooting-2-hands/")
NBA_ROUTINE = ("Jr. NBA — Fundamentals of the Free Throw", "https://jr.nba.com/video/fundamentals-of-the-free-throw/")
SPORT = ("Slegers, Lee and Wong — Basketball release variability and distance",
         "https://pmc.ncbi.nlm.nih.gov/articles/PMC8256521/")
NHS = ("NHS — Shoulder pain", "https://www.nhs.uk/symptoms/shoulder-pain/")
RECORDING = ("ShotCoach — Recording and measurement guide", None)


def entry(topic, keywords, principle, cue, purpose, use, avoid, exercise, progression,
          evaluation, source, metric=None):
    return dict(topic=topic, keywords=keywords.split(), principle=principle, cue=cue,
                purpose=purpose, use_when=use, avoid_when=avoid, exercise=exercise,
                progression=progression, evaluation=evaluation, source=source[0],
                url=source[1], metric=metric)


KNOWLEDGE = {
    "scoring": entry("Basketball scoring", "points scoring score count worth basket",
        "In the NBA a made free throw is worth one point. A made field goal is worth two from on or inside the three-point line, and three from outside.",
        None, None, "When the question is about scoring rules.", "When asked about an individual shooting result.",
        None, None, None, ("NBA Official — Scoring and timing", "https://official.nba.com/rule-no-5-scoring-and-timing/")),
    "free_throw": entry("What a free throw is", "free throw rules foul line",
        "A free throw is an undefended attempt from the free-throw line. A successful attempt is worth one point.",
        None, None, "When the question asks what a free throw is.", "When the player asks for a free-throw practice drill.",
        None, None, None, ("NBA Official — Definitions", "https://official.nba.com/rule-no-4-definitions/")),
    "mechanics": entry("Shooting mechanics", "mechanics fundamentals",
        "A balanced setup, coordinated lift and comfortable finish give you useful checkpoints for a repeatable shot.",
        "Pick one checkpoint and keep the rest of your usual shot.",
        "Find a useful starting point without rebuilding the whole shot.", "When learning the movement or establishing a baseline.",
        "When a comfortable, effective movement already serves the player’s goal.",
        "Shooting checkpoints", "Take a short set from close range and pay attention to your setup on every rep.",
        "Check whether your setup feels stable and repeats across attempts.", USA),
    "stance": entry("Stance and balance", "stance feet footwork balance stable square",
        "A comfortable base helps you start each shot balanced.",
        "Set both feet before you lift the ball and feel your weight centered.",
        "Start each rep from a stable position.", "When the setup feels rushed or unstable.",
        "When a comfortable, repeatable stance is already working.",
        "Set and shoot", "Take a short set from one spot. Reset your feet before each rep.",
        "Check whether your setup feels repeatable. Record makes separately.", USA),
    "preparation": entry("Ball preparation", "preparation setup pickup pocket position grip hands guide ball",
        "A repeatable ball position gives your shooting hand a consistent start.",
        "Start with the ball comfortably in front of you and let your shooting hand sit under it.",
        "Make the lift easier to repeat.", "When the player is learning the pickup or grip.",
        "When changing the pickup would add another focus to the current practice.",
        "Slow lift", "From close range, rehearse the lift, then take a short set at normal speed.",
        "Check whether the ball starts in a similar place across reps.", USA),
    "knees": entry("Knee bend", "knees knee bend legs dip crouch",
        "A comfortable knee bend can help you find a repeatable setup.",
        "Let your knees soften slightly before you lift the ball.",
        "Keep the setup comfortable and repeatable.", "When testing a more repeatable preparation.",
        "When deeper bending causes discomfort or the player already has a reliable setup.",
        "Same-spot knee bend", "Take a short set at the same spot and repeat the same comfortable bend.",
        "Compare how similar the bend looks across the set and record makes separately.", USA,
        "min_knee_angle"),
    "arm": entry("Shooting arm", "arm elbow alignment shooting side",
        "The shooting hand and arm guide the ball on delivery.",
        "Lift the ball with your shooting hand underneath and let the arm extend toward the basket.",
        "Give the ball a repeatable lift.", "When exploring shooting-arm delivery.",
        "When chasing a specific joint angle or changing an effective shot for appearance.",
        "Close one-hand form shots", "Take a short set close to the rim, then add your guide hand.",
        "Compare the shooting arm at similar points in each clip.", NBA_FORM, "release_elbow_angle"),
    "timing": entry("Leg and arm timing", "timing coordination rhythm smooth motion sync",
        "The lower body and shooting arm can work together as one smooth movement.",
        "As you rise, let the ball rise with you in one smooth motion.",
        "Find a rhythm that is easy to repeat.", "When the shot feels rushed or has an unwanted pause.",
        "When an individualized rhythm is effective and comfortable.",
        "Smooth-rise set", "Start close and take a short set from the same spot with one rhythm cue.",
        "Check how repeatable the setup-to-release timing looks.", USA, "shooting_motion_ms"),
    "release": entry("Ball release", "release wrist fingers spin hand",
        "A relaxed shooting wrist is a useful release cue.",
        "Finish the lift by letting the ball roll off your fingers toward the rim.",
        "Practice a repeatable finish with the shooting hand.", "For close-range release practice.",
        "When the player has wrist pain or when estimating trajectory from an elbow angle.",
        "Close-range release set", "Take a short set close to the hoop with the same starting position.",
        "Check your wrist finish across reps and record makes separately.", USA),
    "finish": entry("Follow-through", "follow through followthrough finish extension straighten shooting hand",
        "A repeatable finish gives you something easy to check after each shot.",
        "Let your shooting arm finish up with your wrist relaxed.",
        "Make the end of the shooting motion easy to repeat.", "When testing an early finish cue.",
        "When the video ends at release or when interpreting early extension as hold duration.",
        "Same-spot finish set", "Take a short set from one spot and think only about the finish.",
        "Review early follow-through across the next clips and log makes separately.", USA,
        "elbow_extension_after_release"),
    "landing": entry("Landing and stability", "landing land jump drift stability feet",
        "A balanced landing can help you finish under control.",
        "On a stationary jump shot, try landing softly and balanced near your takeoff spot.",
        "Use a controllable finish in a stationary drill.", "When comparing stationary jump shots.",
        "When momentum is part of the drill or feet are out of frame.",
        "Balanced landing set", "Start close and record your feet from setup through landing.",
        "Review whether you finish balanced from rep to rep.", USA),
    "distance": entry("Trajectory and distance", "trajectory arc distance short long power force three range",
        "Longer shots can call for more contribution from the legs and a faster ball release. Compare shots from the same spot first.",
        "Move closer until you can send the ball up comfortably with a smooth release.",
        "Find a comfortable range for a controlled practice set.", "When a player is exploring range.",
        "When claiming launch angle, speed or power from a joint angle or one missed shot.",
        "Same-distance set", "Choose one spot for the set. Change distance in the next set only.",
        "Log makes, misses and any visible short or long tendency separately at each spot.", SPORT),
    "bank": entry("Bank shots", "backboard",
        "A bank shot uses the backboard to redirect the ball into the basket.",
        "Start close at an angle and pick a visible spot on the board.",
        "Learn how your target on the board changes with your shooting position.",
        "When practising a shot intended to use the backboard.",
        "When the player is working on a direct-to-rim shot.",
        "Same-spot bank shots", "Try a few comfortable shots from one close spot using the same target on the board.",
        "Compare where the ball hits the board and where it goes after that.",
        ("Jr. NBA — Bank Shot", "https://jr.nba.com/bank-shot/")),
    "routine": entry("Shooting consistency", "routine consistency consistent free throw practice repeat drill beginner",
        "One repeatable routine gives you a clear starting point for practice.",
        "Set your feet, pick a spot on the rim, then use the same comfortable rhythm each time.",
        "Give each attempt a similar setup.", "For a beginner or a baseline practice set.",
        "When adding a new sequence would conflict with a reliable existing routine.",
        "Repeat your free-throw routine", "Take a short set from one spot. Use the same routine for each shot.",
        "Record makes and misses separately from how repeatable your setup-to-release rhythm felt.", NBA_ROUTINE,
        "shooting_motion_ms"),
    "individual": entry("Individual technique", "unusual unconventional effective percentage form accuracy different",
        "Different players can make effective shots with different comfortable mechanics.",
        "Keep the parts that feel comfortable and work. Test one small change only if it serves your goal.",
        "Preserve an effective routine while learning what is repeatable.", "When appearance is the main concern.",
        "When a painful movement needs qualified assessment.",
        "Keep-your-routine set", "Take a set with your usual shot from your usual distance.",
        "Compare outcome counts and repeatability across comparable sets.", SPORT),
    "recording": entry("Recording quality", "recording camera tracking coverage missing video angle side view quality",
        "A steady side view with the whole body visible makes pose review easier.",
        "Place the camera on a steady support and keep your feet, shooting hand and hoop in frame.",
        "Reduce occlusion and make clips easier to compare.", "When clips are hard to interpret or compare.",
        "When treating camera visibility as proof that a measurement is correct.",
        "Matching clips", "Record the next set from the same position in good light.",
        "Check that setup, release and finish are visible across the set.", RECORDING),
    "safety": entry("Pain while shooting", "pain hurt hurts sore discomfort injured injury shoulder",
        "Pain that worsens or persists warrants assessment by a qualified healthcare professional.",
        "Pause the shooting movement that makes the pain worse.",
        "Avoid aggravating the painful movement.", "When the player reports pain or injury.",
        "Technique experiments intended to diagnose or treat pain.",
        None, None, None, NHS),
}

for key, item in KNOWLEDGE.items():
    item["evidence_basis"] = {
        "scoring": "official_rules", "free_throw": "official_rules", "safety": "clinical_guidance",
        "recording": "measurement_guidance", "distance": "observational_study", "individual": "observational_study",
    }.get(key, "coaching_guidance")
if KNOWLEDGE.keys() & LIBRARY.keys():
    raise ValueError("A detailed knowledge ID conflicts with an existing coaching topic")
KNOWLEDGE.update(LIBRARY)

TOPIC_PHRASES = {
    "mechanics": ("shooting mechanics", "shooting fundamentals", "how to shoot a basketball", "shooting form", "form shooting"),
    "stance": ("feet set", "step into", "foot placement", "off balance", "base of support", "one two step"),
    "preparation": ("guide hand", "off hand", "shooting pocket", "set point", "ball pickup", "thumb flick"),
    "knees": ("knee bend", "leg drive", "load my legs", "knee dip", "straighten my legs"),
    "arm": ("elbow flare", "elbow positioning", "shooting arm", "arm path", "elbow under", "elbow extension"),
    "timing": ("one motion", "two motions", "leg and arm timing", "quick release", "rushed shot", "pause at the top",
               "as i rise", "whole body", "legs and arms", "lower body and upper body"),
    "release": ("wrist snap", "finger roll", "backspin", "ball leaves", "release point", "wrist flick"),
    "finish": ("follow through", "hold my finish", "arm extension", "finish high", "straighten my arm",
               "straightens after release", "extension after release"),
    "landing": ("land forward", "jump forward", "stationary jump", "land off balance"),
    "distance": ("shot falls short", "keep coming up short", "get more range", "launch angle", "ball flight",
                 "generate power", "shoot farther", "flat shot", "too flat", "shooting range"),
    "bank": ("bank shot", "bank shots", "use the glass", "off the glass"),
    "routine": ("shooting routine", "free throw routine", "foul line routine", "same spot", "shot to shot", "practice plan", "repeatable routine"),
    "individual": ("unconventional form", "unusual form", "looks different", "effective form", "form works",
                   "makes most shots", "high percentage"),
    "recording": ("camera angle", "side view", "pose tracking", "record my shot"),
}

METRIC_GUIDANCE = {
    "min_knee_angle": "knees", "knee_angle_range": "knees",
    "release_elbow_angle": "arm", "max_elbow_angle": "arm", "elbow_angle_range": "arm",
    "elbow_extension_after_release": "finish", "shooting_motion_ms": "timing",
}


# Compact exercise families, bound to the validated topic at recommendation time.
# These are app-authored practice adaptations, not externally validated protocols.
def drill(identifier, title, topics, equipment, instructions, success, easier, progression, limitations):
    return {
        "id": identifier, "title": title, "target_topics": topics.split(),
        "purpose": "Test one comfortable, repeatable movement while tracking outcomes separately.",
        "experience_levels": ["beginner", "intermediate", "experienced", "advanced"],
        "required_equipment": equipment, "setup": instructions[0], "instructions": instructions[1:],
        "dose_range": {"sets": [1, 3], "repetitions": [1, 10], "duration_seconds": [1, 600]},
        "coaching_cues": ["Use the selected topic cue; preserve the rest of the comfortable routine."],
        "success_criteria": success, "easier_variation": easier, "progression": progression,
        "limitations": limitations,
        "safety": "Stop if the exercise causes pain or discomfort. Use clear, stable space; do not force a joint angle.",
        "source_info": {"author": "ShotCoach", "status": "app_authored_adaptation", "professionally_validated": False},
    }


DRILLS = {item["id"]: item for item in (
    drill("focused_shooting", "One-focus shooting experiment",
          "arm knees timing finish release preparation stance routine individual distance mechanics", ["ball", "hoop"],
          ["Choose one comfortable shooting spot with clear space and a ball and hoop.",
           "Rehearse the selected cue once, then shoot using the usual routine.", "Reset between attempts; change only the selected focus."],
          "Check comfort and repeatability of the selected focus; record makes and misses separately.",
          "Use fewer attempts at a comfortable closer spot.",
          "Repeat comfortably before adding attempts or range; change one demand at a time.",
          ["Not a diagnosis or a guarantee of more makes.", "Do not change an effective comfortable habit solely for appearance."]),
    drill("close_delivery", "Close-range delivery rehearsal", "arm release finish preparation", ["ball", "hoop"],
          ["Choose a comfortable close spot with a ball, hoop and clear space.",
           "Rehearse the selected delivery cue with both hands in the usual setup.", "Take an unhurried attempt, then reset."],
          "Check whether the selected delivery cue feels comfortable and can be repeated; track outcomes separately.",
          "Rehearse without releasing the ball before trying a shot.",
          "Return to the usual distance only after the close-range version feels repeatable.",
          ["No ideal elbow angle is prescribed.", "Do not infer wrist or launch-angle faults from elbow measurements."]),
    drill("shadow_rehearsal", "No-release movement rehearsal",
          "arm knees timing finish release preparation stance routine individual distance mechanics", [],
          ["Use clear, stable space. No ball or hoop is required; keep an available ball in hand without releasing it.",
           "Slowly rehearse the selected movement at a comfortable pace.", "Reset after each repetition without throwing or jumping."],
          "Report whether the selected cue feels comfortable and repeatable. This does not measure shooting accuracy.",
          "Use a smaller comfortable movement and pause between repetitions.",
          "Transfer the same cue to shooting only when a ball and hoop are available and the rehearsal feels comfortable.",
          ["A rehearsal is not a shooting-outcome test.", "Range practice without a hoop can rehearse the routine but cannot assess flight or power."]),
    drill("steady_setup", "Comfortable setup rehearsal", "knees stance timing routine", [],
          ["Use clear, stable space. No hoop or ball is required.",
           "Set the feet comfortably, rehearse the selected setup or timing cue, then reset.", "Keep the movement small and comfortable without releasing a ball."],
          "Check whether the setup or rhythm can be repeated comfortably; this exercise does not test makes.",
          "Rehearse only the comfortable starting position before adding the movement.",
          "Add the usual shooting motion only when the setup feels repeatable and suitable equipment is available.",
          ["Do not prescribe deeper bending from appearance alone."]),
    drill("landing_balance", "Stationary balance rehearsal", "landing", [],
          ["Use clear, stable space with both feet visible if filming.",
           "Rehearse a comfortable stationary finish and reset the feet without adding a jump.", "Check balance and comfort after each repetition."],
          "Report whether the stationary finish feels controlled; current measurements do not establish landing quality.",
          "Practise only a comfortable standing finish.",
          "Reconsider with suitable full-body footage before adding a jumping task.",
          ["General balance practice only; the analysis does not diagnose a landing fault."]),
    drill("recording_check", "Matched-view recording check", "recording", ["camera"],
          ["Use an available camera on a stable support; keep the body and available ball and hoop visible.",
           "Record a short view check using the same camera position.", "Check visibility of setup, release and finish before collecting a new set."],
          "Confirm the required body parts are visible; visibility does not prove measurement accuracy.",
          "Start with a stationary framing check.",
          "Keep the same position for a later comparable set.",
          ["This improves recording consistency, not shooting mechanics."]),
)}


def eligible_drills(topic, constraints, memory):
    """Filter unsafe or infeasible resources without ranking coaching choices."""
    if topic not in KNOWLEDGE or not KNOWLEDGE[topic]["exercise"]:
        return []
    equipment = constraints.get("equipment", {})
    outcomes = {report["focus_id"]: report["kind"] for report in memory["reports"]
                if report["kind"] in ("helped", "did_not_help")}
    failed_focuses = {focus_id for focus_id, outcome in outcomes.items() if outcome == "did_not_help"}
    failed_drills = {item.get("drill_id") for item in memory["recommendations"] if item["id"] in failed_focuses}
    if any(item["id"] in failed_focuses and not item.get("drill_id") and item.get("knowledge_id") == topic
           for item in memory["recommendations"]):
        # Legacy records lack an exercise identity: reassess rather than assume
        # the old unsuccessful cue is safe to repeat under a new title.
        return []
    if constraints.get("available_time_seconds") == 0 or equipment.get("clear_space") is False or constraints.get("seated_only"):
        return []
    return [item for item in DRILLS.values() if topic in item["target_topics"]
            and item["id"] not in failed_drills
            and not any(equipment.get(required) is False for required in item["required_equipment"])
            and not (constraints.get("no_jumping") and "hoop" in item["required_equipment"])
            and constraints.get("available_time_seconds", 600) >= (15 if "hoop" in item["required_equipment"] else 5)]


def select_drill(topic, constraints, memory):
    """Pick a conservative default for provider-unavailable responses."""
    candidates = eligible_drills(topic, constraints, memory)
    if not candidates:
        return None
    equipment = constraints.get("equipment", {})
    easier = constraints.get("easier", False)
    experience = memory.get("experience", "").casefold()
    beginner = experience in ("beginner", "new to basketball")
    unavailable = equipment.get("ball") is False or equipment.get("hoop") is False or constraints.get("no_jumping", False)
    brief = constraints.get("available_time_seconds", 300) < 60
    preferred = ("steady_setup" if topic in ("knees", "stance", "timing", "routine") else "shadow_rehearsal") if unavailable or brief else (
        "close_delivery" if (beginner or easier) and topic in ("arm", "release", "finish", "preparation") else
        "steady_setup" if (beginner or easier) and topic in ("knees", "stance", "timing", "routine") else "focused_shooting")
    candidates.sort(key=lambda item: (item["id"] != preferred,
                                      item["id"] != "shadow_rehearsal", item["id"]))
    item = candidates[0]
    shooting = "hoop" in item["required_equipment"]
    reps = 5 if beginner or easier or not experience else 8
    sets = 1 if beginner or easier or not experience else 2
    seconds_per_rep = 15 if shooting else 5
    budget = min(constraints.get("available_time_seconds", 300), 600)
    if budget < seconds_per_rep:
        return None
    sets = min(sets, max(1, budget // (seconds_per_rep * reps)))
    reps = min(reps, max(1, budget // (sets * seconds_per_rep)))
    dose = {"sets": sets, "repetitions": reps, "duration_seconds": sets * reps * seconds_per_rep}
    assumptions = [f"Plan estimate: allow about {seconds_per_rep} seconds per repetition including resetting; this is a practice allowance, not a measured player time."]
    if not experience:
        assumptions.append("Experience is unknown; start with a small, unhurried set.")
    for required in item["required_equipment"]:
        if required not in equipment:
            assumptions.append(f"This exercise assumes access to a {required}; use a no-release variation if unavailable.")
    return {**item, "target_topic": topic, "targeted_issue": KNOWLEDGE[topic]["topic"],
            "purpose": KNOWLEDGE[topic]["purpose"], "coaching_cues": [KNOWLEDGE[topic]["cue"]],
            "suggested_dose": dose, "assumptions": assumptions,
            "selection_reason": "Validated coaching topic, stated resources/time, experience, requested difficulty and unsuccessful-exercise exclusions.",
            "reconsider": "Stop if uncomfortable. Reassess if the cue is difficult or unhelpful; do not repeat an unsuccessful exercise automatically.",
            "principle_source": {"title": KNOWLEDGE[topic]["source"],
                                 "url": KNOWLEDGE[topic]["url"],
                                 "status": "existing_background_attribution_not_exercise_validation"}}


def supporting_context(key):
    """Give the model principles and applicability while the server keeps fallback copy."""
    item = KNOWLEDGE[key]
    result = {field: item[field] for field in (
        "topic", "principle", "cue", "purpose", "use_when", "avoid_when", "exercise", "source", "url", "metric",
        "evidence_basis",
    )}
    if key in LIBRARY:
        result["application"] = item["application"]
    result["drills"] = [drill for drill in DRILLS.values() if key in drill["target_topics"]]
    return result


def normalized_query(query):
    return " ".join(re.findall(r"[a-z0-9]+", query.casefold()))


SEARCH_PHRASES = {
    key: tuple((f" {phrase} ", len(phrase.split())) for alias in item.get("phrases", TOPIC_PHRASES.get(key, ()))
               if (phrase := normalized_query(alias)))
    for key, item in KNOWLEDGE.items()
}


def parent_topic(topic):
    return KNOWLEDGE.get(topic, {}).get("parent", topic)


def search_knowledge(query, limit=4, *, default_to_routine=True, context_topics=(), resource_query=False):
    key = re.sub(r"[\s-]+", "_", query.strip().casefold())
    if not default_to_routine and key in KNOWLEDGE:
        return [key]
    query = normalized_query(query)
    if re.search(r"\b(?:(?:quick(?:er)?|fast(?:er)?|slow(?:er)?) release|release (?:more )?(?:quickly|faster)|speed up .{0,15}release)\b", query):
        return ["timing"]
    if re.search(r"\b(?:(?:farther|further)(?: away| out| back)?|longer (?:range|distance))\b", query):
        return ["distance"]
    tokens = set(query.split())
    if resource_query:
        tokens -= {"shoot", "shooting", "shot", "form", "position", "video", "angle", "count", "practice", "drill", "hand", "ball"}
    phrase_query = f" {query} "
    scored = []
    for key, item in KNOWLEDGE.items():
        if key == "safety":
            continue
        phrase = max((weight for alias, weight in SEARCH_PHRASES[key] if alias in phrase_query), default=0)
        score = 4 * phrase + len(tokens.intersection(item["keywords"]))
        if score:
            scored.append((score, key in context_topics or parent_topic(key) in context_topics, key))
    if re.search(r"\b(?:what is|what s|define) (?:a )?free throw\b", query):
        return ["free_throw"]
    ranked = [key for _, _, key in sorted(scored, key=lambda match: (-match[0], -match[1]))
              if key != "free_throw" or {"rules", "foul"} & tokens]
    if not {"points", "scoring", "worth", "score"} & tokens:
        ranked = [key for key in ranked if key != "scoring"]
    return ranked[:limit] or (["routine"] if default_to_routine else [])
