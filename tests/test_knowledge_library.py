import json
from collections import Counter
from urllib.parse import urlsplit

import pytest

from backend.app.agent.knowledge import KNOWLEDGE, normalized_query, search_knowledge
from backend.app.agent.knowledge_library import LIBRARY
from backend.app.agent.resources import RESOURCES, find_resources


@pytest.mark.parametrize(("question", "expected"), [
    ("Should I use an open stance?", "open_stance"),
    ("I wobble before release", "stable_base"),
    ("Can I use staggered feet?", "staggered_feet"),
    ("How should I change hip flexion on threes?", "hip_loading"),
    ("What does shoulder flexion look like?", "shoulder_elevation"),
    ("Do I need a deeper knee bend?", "knee_dip_depth"),
    ("My guide hand pushes the ball", "guide_hand_job"),
    ("Should my forearm be vertical?", "forearm_support"),
    ("What do we know about elbow-wrist coordination?", "elbow_wrist_sequence"),
    ("Does a quick wrist snap cause better accuracy?", "wrist_speed_evidence"),
    ("Where are my fingertips at release? I mean the last finger.", "finger_contact"),
    ("What is the difference between launch vs entry angle?", "launch_vs_entry"),
    ("Can I calculate force from this video?", "power_vs_speed"),
    ("What matters for spin axis alignment?", "spin_axis"),
    ("The ball spins sideways", "side_spin_hypothesis"),
    ("What can I test for front rim misses?", "short_miss"),
    ("What can I check for back rim misses?", "long_miss"),
    ("Why is my ball missing right?", "lateral_miss"),
    ("When should I release at apex?", "release_jump_timing"),
    ("What is useful for mid-range mechanics?", "midrange_mechanics"),
    ("How do I build a range ladder?", "range_ladder"),
    ("How do I reset after a missed free throw?", "routine_reset"),
    ("How can I practice pressure free throws?", "routine_pressure"),
    ("Any advice about a dribble gather?", "pullup_gather"),
    ("How do I shoot off a screen?", "screen_shooting"),
    ("What is the difference between accuracy versus consistency?", "accuracy_vs_repeatability"),
    ("What can I do about shooting worse when tired?", "late_set_fatigue"),
    ("Could I use a neuromuscular warmup?", "neuromuscular_warmup"),
    ("What is an intermediate shooting progression?", "intermediate_progression"),
    ("Should I use a next day test?", "retention_test"),
    ("Should I fix my weird shot?", "unconventional_maintain"),
    ("The previous cue did not help.", "failed_cue_reassessment"),
])
def test_representative_detail_ranks_first(question, expected):
    assert search_knowledge(question)[:1] == [expected]


def test_precise_source_records_and_duplicate_catalog_checks():
    assert 100 <= len(KNOWLEDGE) <= 150
    assert 30 <= len(RESOURCES) <= 50
    assert len({normalized_query(item["topic"]) for item in KNOWLEDGE.values()}) == len(KNOWLEDGE)
    assert len({normalized_query(item["principle"]) for item in KNOWLEDGE.values()}) == len(KNOWLEDGE)
    assert len({item.id for item in RESOURCES}) == len(RESOURCES)
    assert len({normalized_query(item.title) for item in RESOURCES}) == len(RESOURCES)
    assert len({(urlsplit(item.url).hostname, urlsplit(item.url).path.rstrip("/").lower())
                for item in RESOURCES}) == len(RESOURCES)
    assert Counter(item.kind for item in RESOURCES)["video"] > len(RESOURCES) / 2
    for item in RESOURCES:
        url = urlsplit(item.url)
        assert url.scheme == "https" and url.hostname in {"jr.nba.com", "www.usab.com", "pmc.ncbi.nlm.nih.gov"}
        assert url.path.strip("/") and not url.query and not url.fragment
        assert set(item.topics) <= KNOWLEDGE.keys()
        assert item.organization and item.watch_for and item.skill_levels
        assert set(item.skill_levels) <= {"beginner", "intermediate", "advanced"}
    for item in LIBRARY.values():
        assert item["parent"] in KNOWLEDGE
        for field in ("phrases", "principle", "purpose", "use_when", "avoid_when", "application", "source", "evidence_basis"):
            assert item[field]
        assert urlsplit(item["url"]).scheme == "https" and urlsplit(item["url"]).path.strip("/")


def test_expanded_resources_respect_topic_type_level_and_repeats():
    topics = ("routine_pressure",)
    beginning = find_resources("video about pressure free throws", topics, "video", experience="beginner")
    advanced = find_resources("video about pressure free throws", topics, "video", experience="advanced")
    assert beginning[0][0].id == "jrnba_make_it_take_it"
    assert [resource.id for resource, _ in advanced] == ["jrnba_make_it_take_it", "usab_50_make_1_miss_shooting_drill"]
    seen = [{"role": "assistant", "content": advanced[0][0].url}]
    assert find_resources("another video", topics, "video", history=seen)[0][0].id == advanced[1][0].id
    assert not find_resources("video about spin rpm", ("spin_axis",), "video")
    assert search_knowledge("quantum chromatography seminar", default_to_routine=False) == []
    assert search_knowledge("forearm_support", default_to_routine=False) == ["forearm_support"]


def test_catalog_context_integrates_measurements_goals_experience_and_failed_practice():
    from backend.app.agent.context import EvidenceContext
    from backend.app.agent.memory import empty_memory
    from evaluation.fixtures import playground_scenario, synthetic_shot

    shot = synthetic_shot()
    measured = EvidenceContext("Fixture", "How can I improve my shot?", shot.shot_id, (), [], empty_memory(), shots=[shot])
    measured.collect(False)
    assert "knee_dip_depth" in measured.knowledge_ids
    beginner = EvidenceContext("Fixture", "What should I practice?", None, (), [],
                               {**empty_memory(), "experience": "beginner"}, shots=[])
    beginner.collect(False)
    assert "close_first" in beginner.knowledge_ids
    goal = EvidenceContext("Fixture", "What should I practice?", None, (), [],
                           {**empty_memory(), "goal": "Build a range ladder"}, shots=[])
    assert "range_ladder" in goal.knowledge_ids
    case = playground_scenario("unsuccessful")
    after = EvidenceContext(case["player"], "The previous cue did not help.", None, (), [], case["memory"], shots=case["shots"])
    after.collect(False)
    assert "failed_cue_reassessment" in after.knowledge_ids
    specific = EvidenceContext("Fixture", "Find a video about spin rpm", None, (), [], empty_memory(), shots=[])
    specific.collect(False)
    assert "spin_axis" in specific.knowledge_ids and not specific.resources
    prevention = EvidenceContext("Fixture", "What warmup helps with injury prevention?", None, (), [], empty_memory(), shots=[])
    assert prevention.intent != "pain" and prevention.knowledge_ids[0] == "neuromuscular_warmup"


def test_mocked_request_keeps_expanded_catalog_out_of_prompt():
    from backend.app.agent.coaching_agent import coach
    from backend.app.agent.memory import empty_memory
    from evaluation.fixtures import MockOpenAI

    call = [{"type": "function_call", "name": "retrieve_knowledge", "call_id": "detail",
             "arguments": '{"topic":"spin axis"}'}]
    model = MockOpenAI([call, {"message": "Consider the direction of rotation and how steadily you can reproduce it.",
                               "knowledge_ids": ["spin_axis"]}])
    result = coach("Fixture", "What is the spin axis of a basketball shot?", client=model, shots=[],
                   persist=False, memory_state=("", empty_memory()))
    initial = model.calls[0]["inputs"][0]["content"][0]["text"]
    knowledge = json.loads(initial)["knowledge"]
    tool = next(item for item in model.calls[1]["inputs"] if item.get("type") == "function_call_output")
    result_packet = json.loads(tool["output"])["result"]
    assert 1 <= len(knowledge) <= 6 and "spin_axis" in knowledge
    assert len(initial.encode("utf-8")) < 15_000
    assert len(json.dumps(knowledge).encode("utf-8")) < 4_000
    assert len(result_packet["principles"]) <= 2
    assert result_packet["principles"]["spin_axis"]["application"]
    assert result.knowledge_references[0]["id"] == "spin_axis"
