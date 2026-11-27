import json
from urllib.parse import urlsplit

import httpx
import pytest

from backend.app.agent.coaching_agent import coach, response_text
from backend.app.agent.context import EvidenceContext
from backend.app.agent.gemini_provider import GeminiProvider
from backend.app.agent.knowledge import KNOWLEDGE, search_knowledge
from backend.app.agent.memory import empty_memory
from backend.app.agent.openai_provider import OpenAIProvider
from backend.app.agent.resources import RESOURCES
from evaluation.fixtures import MockOpenAI, playground_scenario


def offline(question, *, memory=None, history=()):
    return coach("Fixture", question, shots=[], history=history, persist=False,
                 memory_state=("", memory or empty_memory()))


@pytest.mark.parametrize(("question", "topic"), [
    ("How can I improve my shooting mechanics?", "mechanics"),
    ("My off-hand thumb flicks the ball", "preparation"),
    ("My shot feels rushed and there's a pause at the top", "timing"),
    ("How should I finish high?", "finish"),
    ("How do I get more range?", "distance"),
    ("I land off balance after a jump", "landing"),
    ("I have an unconventional form but make most shots", "individual"),
])
def test_topic_matching_uses_coaching_phrases(question, topic):
    assert search_knowledge(question)[0] == topic


def test_mechanics_without_player_evidence_stays_general_and_resource_is_optional():
    result = offline("How can I improve my shooting mechanics?")
    assert result.guidance_basis == "general"
    assert result.focus == "Shooting mechanics"
    assert result.instructional_resource is None and not result.video_references
    assert "checkpoint" in result.cue.lower()


def test_catalog_keeps_exact_publisher_links_and_omits_unverified_video_time():
    assert len({item.id for item in RESOURCES}) == len(RESOURCES)
    for entry in RESOURCES:
        url = urlsplit(entry.url)
        assert url.scheme == "https" and url.netloc in {"jr.nba.com", "www.usab.com", "pmc.ncbi.nlm.nih.gov"}
        assert url.path.strip("/") and set(entry.topics) <= KNOWLEDGE.keys()
    result = offline("Can you link the video Form Shooting-2 Hands?")
    card = result.instructional_resource
    assert (card.title, card.organization, card.creator) == ("Form Shooting-2 Hands", "Jr. NBA", "Dale Ellis")
    assert card.url == "https://jr.nba.com/video/form-shooting-2-hands/"
    assert card.section is None
    assert card.watch_for and card.exercise and "general reference" in card.relevance
    tutorial = offline("Show me a tutorial on my shooting mechanics.")
    assert tutorial.instructional_resource.id == "usab_beef" and not tutorial.video_references
    article = offline("Please recommend an article about increasing shooting range.").instructional_resource
    assert article.kind == "article" and article.section == "Shooting"


def test_no_verified_video_leaves_relevant_knowledge_and_no_homepage_recommendation():
    result = offline("Find a video on bank shots.")
    assert result.instructional_resource is None
    assert "verified video" in result.guidance_note
    assert "backboard" in result.message
    context = EvidenceContext("Fixture", "What is a bank shot?", None, (), [], empty_memory(), shots=[])
    lookup = context.retrieve_knowledge("bank shots", "video")
    assert list(lookup["principles"]) == ["bank"]
    assert lookup["resource_status"] == "no_match" and not lookup["resources"]
    context = EvidenceContext("Fixture", "Explain my follow-through. No external links.",
                              None, (), [], empty_memory(), shots=[])
    assert context.retrieve_knowledge("finish", "video")["resource_status"] == "no_match"


def test_follow_up_uses_prior_topic_and_skips_the_link_already_shared():
    question = "Recommend a video for my follow-through."
    first = offline(question)
    history = [{"role": "user", "content": question}, {"role": "assistant", "content": response_text(first)}]
    second = offline("Another video, please?", history=history)
    assert first.instructional_resource.id == "jrnba_two_hand_form"
    assert second.instructional_resource.id == "usab_beef"


def test_context_lookup_uses_goals_and_filters_unsuccessful_exercises():
    memory = {**empty_memory(), "experience": "beginner", "goal": "Improve my free throw routine"}
    result = offline("Can you recommend an instructional video?", memory=memory)
    assert result.instructional_resource.id == "jrnba_free_throw"
    assert not result.video_references
    case = playground_scenario("unsuccessful")
    attempted = coach(case["player"], "Find an instructional video about my knee bend.", shots=case["shots"],
                      memory_state=("", case["memory"]), persist=False)
    assert attempted.instructional_resource.id == "jrnba_two_hand_form"
    assert attempted.instructional_resource.exercise is None
    reassess = coach(case["player"], "The knee cue you suggested did not help.", shots=case["shots"],
                     memory_state=("", case["memory"]), persist=False)
    assert reassess.instructional_resource is None and reassess.practice is None


def test_unconventional_effective_form_does_not_get_a_technique_comparison_for_appearance():
    case = playground_scenario("consistent_high")
    result = coach(case["player"], "My form is unconventional but effective. Should I change it?",
                   shots=case["shots"], memory_state=("", case["memory"]), persist=False)
    assert result.instructional_resource is None
    assert result.practice is None
    assert result.focus == "Individual technique"
    assert "different comfortable mechanics" in result.message


def test_tool_lookup_returns_compact_records_and_unoffered_resource_is_omitted():
    call = [{"type": "function_call", "name": "retrieve_knowledge", "call_id": "knowledge",
             "arguments": '{"topic":"hold my finish","resource_kind":"video"}'}]
    model = MockOpenAI([call, {"message": "Review the finish cue here https://example.invalid/unknown",
                               "instructional_resource_id": "invented"}])
    result = coach("Fixture", "How do I finish my shot?", shots=[], client=model, persist=False,
                   memory_state=("", empty_memory()))
    output = next(item for item in model.calls[1]["inputs"] if item.get("type") == "function_call_output")
    lookup = json.loads(output["output"])["result"]
    assert lookup["resources"][0]["id"] == "jrnba_two_hand_form"
    assert "drills" not in lookup["principles"]["finish"] and "url" not in lookup["resources"][0]
    assert result.instructional_resource is None and "example.invalid" not in result.message


@pytest.mark.parametrize("provider_name", ["openai", "gemini"])
def test_provider_combines_cited_player_frames_and_reviewed_resource(monkeypatch, provider_name):
    monkeypatch.setenv("SHOTCOACH_PROVIDER", provider_name)
    frame = "frame:free_throw_03_shot_1:follow_through:82:elbow:"
    final = {"message": "Use the early finish frame to look at where the shooting arm ends up.",
             "frame_ids": [frame], "instructional_resource_id": "jrnba_two_hand_form"}
    args = {"phases": "follow_through", "focus": "elbow"}
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        first = len(payloads) == 1
        if provider_name == "openai":
            output = [{"type": "function_call", "name": "retrieve_frames", "call_id": "frame",
                       "arguments": json.dumps(args)}] if first else [
                           {"type": "message", "content": [{"type": "output_text", "text": json.dumps(final)}]}]
            return httpx.Response(200, json={"output": output})
        part = {"functionCall": {"name": "retrieve_frames", "args": args, "id": "frame"}} if first else {
            "text": json.dumps(final),
        }
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [part]}}]})

    provider = OpenAIProvider if provider_name == "openai" else GeminiProvider
    with provider("test-only", transport=httpx.MockTransport(respond)) as client:
        result = coach("TestPlayer", "Show me my follow-through and recommend a video for the finish.",
                       selected="free_throw_03", client=client, persist=False, memory_state=("", empty_memory()))
    assert len(payloads) == 2
    assert "jrnba_two_hand_form" in json.dumps(payloads[0])
    assert ("input_image" if provider_name == "openai" else "inlineData") in json.dumps(payloads[1])
    assert result.video_references[0]["id"] == frame
    assert "angle_arc" in result.video_references[0]["annotation"]["marks"]
    assert result.instructional_resource.id == "jrnba_two_hand_form"
    assert "frame from your attempt" in result.instructional_resource.relevance
