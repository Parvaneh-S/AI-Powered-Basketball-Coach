"""Build synthetic shot evidence and explicitly marked OpenAI test doubles."""

import json
from dataclasses import replace

from backend.app.agent.evidence import RecordedShot
from backend.app.agent.memory import empty_memory


def synthetic_shot(index=1, player="Fixture", outcome="made", knee=110, quality="pass",
                   angle=120, source="manual", arm="right", session_id=1):
    analysis = {
        "shot_type": "free_throw",
        "shot_events": {"start_frame": 20, "release_frame": 50, "end_frame": 56,
                        "segmentation_status": "experimental_review_required"},
        "biomechanics": {
            "shooting_arm": arm, "measurement_quality": quality, "min_knee_angle": knee,
            "release_elbow_angle": angle, "shooting_motion_ms": 1000, "max_elbow_angle": 165,
            "knee_angle_range": 30, "elbow_angle_range": 66, "elbow_extension_after_release": 45,
            "knee_coverage_pct": 100 if quality == "pass" else 60, "elbow_coverage_pct": 100,
        },
        "ball_tracking": {"tracking_coverage_pct": 75, "tracked_frames": 24},
    }
    return RecordedShot(player, session_id, f"fixture_shot_{index}", f"fixture_video_{index}",
                        outcome, source, analysis, index)


def fixture_focus(shots):
    from backend.app.agent.knowledge import KNOWLEDGE

    item = KNOWLEDGE["knees"]
    return {
        "id": "focus_from_prior_turn", "title": item["topic"], "cue": item["cue"], "exercise": item["exercise"],
        "knowledge_id": "knees", "field": item["metric"], "decision": "start",
        "conditions": shots[0].conditions, "evidence_ids": ["shot:fixture_shot_1:min_knee_angle"],
        "baseline_shot_ids": [shot.shot_id for shot in shots],
        "last_row_id": max(shot.row_id for shot in shots),
    }


PLAYGROUND_SCENARIOS = {
    "consistent_high": ("Consistent form, high accuracy", "Low synthetic measurement spread; 16 makes and 4 misses. Consistency does not establish ideal mechanics."),
    "consistent_low": ("Consistent form, low accuracy", "The same low-spread measurements with 4 makes and 16 misses. Do not invent a technical cause for misses."),
    "inconsistent_high": ("Variable form, high accuracy", "Wide measurement spread with 16 makes and 4 misses. Variability is not automatically a weakness."),
    "inconsistent_low": ("Variable form, low accuracy", "Wide measurement spread with 4 makes and 16 misses. Outcome groups have matched feature distributions."),
    "multiple_priorities": ("Multiple supported priorities", "Constructed knee, arm and timing associations test evidence ranking. They are synthetic associations, not causal coaching rules."),
    "insufficient": ("Insufficient personal evidence", "Only two labelled attempts. A personal make/miss pattern cannot be established."),
    "unreliable": ("Unreliable measurements", "Twenty known outcomes but low joint coverage and invalid release measurements. No personal form diagnosis is justified."),
    "unsuccessful": ("Previous practice did not help", "Multiple constructed patterns plus an unsuccessful knee recommendation and exercise. Test reassessment and repetition avoidance."),
}


def playground_scenario(key, player="SYNTHETIC_fixture"):
    """Real coaching contracts with fictional measurements; never create media."""
    if key not in PLAYGROUND_SCENARIOS or not player.startswith("SYNTHETIC_"):
        raise ValueError("Use a known scenario and an explicitly synthetic player namespace")
    shots = []
    associated = key in ("multiple_priorities", "unsuccessful")
    high = key.endswith("high")
    made_count = 10 if associated or key == "unreliable" else 16 if high else 4
    count = 2 if key == "insufficient" else 20
    if key == "insufficient":
        made_count = 1
    for index in range(1, count + 1):
        made = index <= made_count
        # Balanced cycles give identical make/miss distributions in the four
        # consistency/outcome scenarios, independently varying accuracy and form.
        level = (-1.5, -0.5, 0.5, 1.5)[(index - 1) % 4]
        scale = 5 if key.startswith("inconsistent") else 0.4
        knee = (112 if made else 123) + level if associated else 116 + scale * level
        elbow = (143 if made else 135) + level if associated else 140 + scale * level
        duration = (800 if made else 920) + level * 10 if associated else 860 + scale * level * 10
        shot = synthetic_shot(index, player=player, outcome="made" if made else "missed", knee=knee, angle=elbow)
        start = 90 * (index - 1) + 10
        release = start + round(duration * 30 / 1000)
        events = {"start_frame": start, "release_frame": release, "end_frame": release + 6,
                  "start_time_ms": start * 1000 / 30, "release_time_ms": release * 1000 / 30,
                  "end_time_ms": (release + 6) * 1000 / 30, "segmentation_status": "synthetic_fixture"}
        biomech = {**shot.analysis["biomechanics"], "max_elbow_angle": 165,
                   "min_knee_angle": knee, "knee_angle_range": 160 - knee,
                   "elbow_angle_range": 65, "elbow_extension_after_release": 165 - elbow,
                   "shooting_motion_ms": (release - start) * 1000 / 30,
                   "valid_knee_frames": release - start + 1, "valid_elbow_frames": release - start + 7,
                   "release_angle_valid": True}
        if key == "unreliable":
            biomech.update(measurement_quality="review", knee_coverage_pct=25,
                           elbow_coverage_pct=35, release_angle_valid=False)
        shots.append(replace(shot, shot_id=f"{player}_shot_{index}", video_id=f"{player}_recording",
            analysis={**shot.analysis, "synthetic": True, "shot_number": index,
                      "shot_events": events, "biomechanics": biomech}))
    memory = empty_memory()
    if key == "unsuccessful":
        focus = {**fixture_focus(shots), "id": "synthetic_unsuccessful_focus", "session_id": 1,
                 "evidence_ids": [f"shot:{shots[0].shot_id}:min_knee_angle"],
                 "guidance_basis": "general", "verified_personal_correction": False,
                 "drill_id": "focused_shooting"}
        memory["recommendations"] = [focus]
        memory["reports"] = [{"focus_id": focus["id"], "kind": "did_not_help",
                              "text": "SYNTHETIC report: this knee cue and exercise did not help.",
                              "recorded_at": "synthetic_fixture"}]
    return {"key": key, "title": PLAYGROUND_SCENARIOS[key][0], "description": PLAYGROUND_SCENARIOS[key][1],
            "data_origin": "SYNTHETIC — not measured from a video", "player": player,
            "shots": shots, "memory": memory}


def scenario_input(fixture):
    player = "Fixture"
    memory = empty_memory()
    shots = [synthetic_shot()]
    if fixture in ("pattern", "flat", "high", "low"):
        for i in range(2, 13):
            is_made = i <= {"pattern": 6, "flat": 6, "high": 10, "low": 2}[fixture]
            knee = (110 if is_made else 142) if fixture == "pattern" else 110
            shots.append(synthetic_shot(i, outcome="made" if is_made else "missed", knee=knee))
    elif fixture == "poor":
        shots = [synthetic_shot(quality="review")]
    elif fixture == "missing":
        shots[0].analysis["biomechanics"] = {}
    elif fixture in ("focus", "progress"):
        shots.append(synthetic_shot(2, outcome="missed", knee=125))
        memory["recommendations"].append(fixture_focus(shots))
        if fixture == "progress":
            shots.extend(synthetic_shot(i, knee=115, session_id=2) for i in (3, 4))
            memory["reports"].append({"focus_id": "focus_from_prior_turn", "kind": "completed",
                                      "text": "Player fixture explicitly reports finishing", "recorded_at": "fixture"})
    elif fixture == "none":
        shots = []
    elif fixture == "unauthorized":
        shots.append(synthetic_shot(2, player="SomeoneElse"))
    elif fixture == "video":
        player = "TestPlayer"
        shots = None
    options = {"selected": shots[0].shot_id if shots else None, "comparison": (), "history": []}
    if fixture == "video":
        options["selected"] = "free_throw_03"
    if fixture == "focus":
        options["history"] = [{"role": "assistant", "content": "Try the same-spot knee bend set."}]
    if fixture == "unauthorized":
        options["comparison"] = ("fixture_shot_1", "fixture_shot_2")
    return player, shots, memory, options


class MockOpenAI:
    """Respond to a bounded series of mocked requests and retain the actual payloads."""

    def __init__(self, results):
        self.calls = []
        self.results = iter(results)

    def respond(self, **kwargs):
        self.calls.append({**kwargs, "inputs": list(kwargs["inputs"])})
        value = next(self.results)
        if isinstance(value, list):
            return value
        return [{"type": "message", "content": [{"type": "output_text",
                                                "text": json.dumps(value) if isinstance(value, dict) else value}]}]



def phase_three_drafts(number, player):
    """Captured live author/repair pair, with shot IDs built from the saved player ID."""
    def fact(evidence_id, field):
        return {"evidence_id": evidence_id, "field": field}

    def shot_facts(*fields):
        return [fact(f"shot:{player}_shot_1:{field}", field) for field in fields]

    def draft(message, evidence, facts, knowledge, practice=None, adaptation=None):
        return {"message": message, "evidence_ids": evidence, "facts": facts, "frame_ids": [],
                "visual": None, "knowledge_ids": knowledge, "practice": practice, "adaptation": adaptation}

    def practice(topic, instructions, evaluation=None, sets=1, reps=10, seconds=300, drill="focused_shooting"):
        return {"drill_id": drill, "topic": topic, "instructions": instructions, "evaluation": evaluation,
                "dose": {"sets": sets, "repetitions": reps, "duration_seconds": seconds} if seconds else None}

    strengths = ["session:1:outcome_counts", "session:1:max_elbow_angle", "session:1:elbow_angle_range"]
    if number == 1:
        facts = shot_facts("min_knee_angle", "knee_angle_range", "release_elbow_angle", "max_elbow_angle",
                           "elbow_angle_range", "elbow_extension_after_release", "shooting_motion_ms")
        return [
            draft("In this practice session, you took 20 shots and made 4 of them, resulting in a 20% shooting accuracy. The recorded shots were all free throws with your right arm. Your shooting mechanics, such as knee bend, elbow angles, and shooting motion time, were consistent across attempts but did not show a clear difference between made and missed shots. This suggests that your form was stable but did not directly correlate with making shots in this session. Since your shooting routine and form are consistent, focusing on comfort and repeatability in your routine could be beneficial. Would you like to try a focused shooting drill to test and improve one aspect of your shot routine?",
                  strengths, facts, ["routine"], practice("routine",
                    "Choose one comfortable shooting spot with a ball and hoop. Rehearse your usual shooting routine once, then shoot focusing on maintaining that routine. Reset between attempts and keep the rest of your routine comfortable and consistent.",
                    "Check if the selected routine feels comfortable and repeatable, and record makes and misses separately."), "continue"),
            draft("In this practice session, you took 20 shots and made 4 of them, resulting in a 20% shooting accuracy. Your shooting mechanics, including knee bend, elbow angles, and shooting motion time, were consistent across attempts but did not show a clear difference between made and missed shots. This means your form was stable but did not directly relate to making shots in this session. If you want, I can suggest drills to help you focus on specific aspects of your shooting routine to improve comfort and repeatability.",
                  strengths, facts, []),
        ]
    if number == 5:
        facts = [fact(key, field) for key, field in zip(strengths, ("accuracy_pct", "max_elbow_angle", "elbow_angle_range"))]
        return [
            draft("Your shooting form, while it may look awkward to you, is effective since you made most of your free throws in the session, with an 80% success rate (16 makes out of 20 attempts). The detailed measurements of your shooting mechanics, such as knee angles and elbow angles, show no clear differences between your made and missed shots, indicating that your current form is consistent and effective for you. Different players can have different comfortable and effective shooting mechanics, so if your form feels comfortable and works well, there is no strong evidence to suggest you need to change it solely based on appearance. If you want to explore adjustments, consider testing one small, comfortable change at a time and track your outcomes separately to see if it helps. For now, preserving your effective routine is advisable.",
                  strengths, facts, ["individual"], adaptation="continue"),
            draft("Your shooting form, although it may look awkward to you, has been effective based on your free throw success rate of 80% (16 makes out of 20 attempts). The measurements of your shooting mechanics, including knee and elbow angles, show no clear differences between made and missed shots, suggesting your current form is consistent for you. Different players can have effective shots with different comfortable mechanics, so if your form feels comfortable and works, there is no strong evidence to change it solely for appearance reasons. If you wish to explore adjustments, consider testing one small, comfortable change at a time and track your outcomes separately to evaluate its effect.",
                  strengths, facts, ["individual"]),
        ]
    if number == 6:
        evidence = ["session:1", "profile:current"]
        facts = [fact("session:1", "accuracy_pct")]
        return [
            draft("Your shooting form appears consistent in the measured mechanics such as knee bending, elbow angles, and shooting motion timing, with no clear difference between made and missed shots in these aspects. This suggests that your form consistency alone is not the main factor limiting your shooting accuracy, as your recorded shots show about 20% made and 80% missed despite similar form metrics. It implies that other factors beyond the visible form consistency, such as release timing, ball launch angle, power, or mental focus, might be affecting your shooting success. Maintaining your comfortable and repeatable mechanics is good, but to improve accuracy, you might consider experimenting with one specific aspect of your shot or routine at a time and track outcomes separately to find what helps. If you want, I can suggest a focused shooting drill to test one comfortable movement or routine element while recording makes and misses separately.",
                  evidence, facts, ["individual"], practice("individual",
                    "Choose one comfortable shooting spot with a ball and hoop. Rehearse one small, comfortable movement or routine cue once, then shoot using your usual routine. Reset between attempts and change only the selected focus. Record makes and misses separately to see what helps."), "continue"),
            draft("Your shooting form shows consistent mechanics in key areas like knee bending and elbow angles, with no clear difference between made and missed shots in these measurements. This means that while your form looks consistent, it alone does not explain why you made few shots. Other factors not captured by these measurements, such as release timing, ball trajectory, or mental focus, might be influencing your shooting accuracy. Maintaining your comfortable and repeatable mechanics is important, and if you want to explore improvements, consider testing one small change at a time while tracking your makes and misses separately to see what helps.",
                  evidence, facts, ["individual"]),
        ]
    if number == 4:
        evidence = ["pattern:min_knee_angle:07db80a6a3f842a3", "pattern:knee_angle_range:e0805da6fe845ff8"]
        plan = practice("knees",
            "Choose a comfortable shooting spot with a ball and hoop. Focus on letting your knees bend comfortably before and during your shot. Rehearse this knee bend once, then shoot using your usual routine. Reset between attempts and keep all other parts of your shot the same. Record your makes and misses separately to see if this adjustment helps.",
            "Check if the knee bend feels comfortable and repeatable, and if your shooting accuracy improves.", sets=2)
        return [
            draft('To improve your shot by focusing on one key aspect, the evidence from your recorded shots suggests that bending your knees more deeply and using a larger knee bend range during your shot is associated with making more shots. Specifically, your made shots had a smaller minimum knee angle (more bend) and a greater knee angle change through the shot compared to missed shots. This means letting your knees soften and bend more before and during your shot could help you find a more repeatable and effective setup. Additionally, your shooting elbow tends to be straighter at release on made shots, so maintaining a consistent arm extension at release is also beneficial. However, since knee bend is a foundational part of your shot preparation and linked to better outcomes, I recommend focusing on a comfortable, repeatable knee bend as your primary adjustment. You can try a "Same-spot knee bend" drill to rehearse this movement comfortably and track your makes and misses separately to see if it helps.',
                  evidence + ["pattern:release_elbow_angle:e82b9750caa689d2"],
                  shot_facts("min_knee_angle", "knee_angle_range", "release_elbow_angle"), ["knees", "arm"], plan, "modify"),
            draft('Looking at your shot data, one clear association is that shots where your knees bend more deeply and change angle more during the shot tend to be made more often. This suggests that focusing on a comfortable, repeatable knee bend before and during your shot could help improve consistency. You might try practicing a "Same-spot knee bend" drill, where you rehearse letting your knees soften slightly before lifting the ball, then shoot using your usual routine. This drill helps you find a repeatable setup without forcing changes to other parts of your shot. Remember, this advice is based on patterns in your shots and does not guarantee improvement, but it offers a focused area to explore.',
                  evidence, shot_facts("min_knee_angle", "knee_angle_range"), ["knees"], plan),
        ]
    if number == 8:
        evidence = ["pattern:knee_angle_range:2cdd12c7b0b21c5f"]
        facts = [fact(evidence[0], "knee_angle_range")]
        plan = practice("Knee bend",
            "Use clear, stable space. No ball or hoop is required; keep an available ball in hand without releasing it. Slowly rehearse the knee bend movement at a comfortable pace. Reset after each repetition without throwing or jumping. Check whether the cue feels comfortable and repeatable. This does not measure shooting accuracy.",
            reps=5, seconds=25, drill="shadow_rehearsal")
        return [
            draft("Since the previous advice to try a slightly larger knee bend-to-rise movement did not help, it may be useful to focus on a different aspect or try a different approach. Your recorded shots show that a larger knee angle change is associated with makes, but this doesn't guarantee it will improve your shooting if it feels uncomfortable or hard to repeat. \n\nLet's try a no-release movement rehearsal drill next. This drill lets you slowly practice the knee bend movement without shooting, helping you find a comfortable and repeatable setup. Use clear, stable space, and rehearse the movement slowly at a comfortable pace, resetting after each repetition without jumping or throwing the ball. This will help you assess if the knee bend cue feels comfortable and repeatable before adding the shooting motion again.\n\nPrescribed practice target: 1 set of 5 repetitions; allow about 25 seconds including resets. Stop if uncomfortable and report how it feels. This drill does not test shooting accuracy but helps build a reliable movement pattern.",
                  evidence, facts, ["knees"], plan, "modify"),
            draft("Your recorded shots show that a larger knee angle change across the shot is associated with made shots, suggesting this movement might be beneficial to explore further. However, since the previous advice did not help, let's try a no-release movement rehearsal drill to practice the knee bend movement slowly and comfortably without shooting. This will help you find a repeatable and comfortable setup before adding the shooting motion again. Use clear, stable space, rehearse the movement at a comfortable pace, and reset after each repetition without throwing or jumping. Stop if uncomfortable and report how it feels. This drill does not test shooting accuracy but helps build a reliable movement pattern.",
                  evidence, facts, ["knees"], {**plan, "dose": None}, "modify"),
        ]
    raise ValueError("No Phase 3 live draft pair for this scenario")
