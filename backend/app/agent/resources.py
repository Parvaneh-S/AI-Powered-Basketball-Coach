"""Reviewed publisher links. The catalog is local and requires no runtime requests."""

import re
from dataclasses import dataclass
from typing import Literal

from backend.app.agent.knowledge import normalized_query

ResourceKind = Literal["", "any", "video", "article"]
REVIEWED_ON = "2026-11-26"


@dataclass(frozen=True)
class Resource:
    id: str
    kind: Literal["video", "article"]
    title: str
    organization: str
    url: str
    topics: tuple[str, ...]
    watch_for: str
    creator: str | None = None
    section: str | None = None
    introductory: bool = False
    skill_levels: tuple[str, ...] = ("beginner", "intermediate", "advanced")
    # Only set when verified on the publisher's page; never derived or guessed.
    thumbnail_url: str | None = None
    embed_url: str | None = None

    def summary(self, topic):
        return {"id": self.id, "kind": self.kind, "title": self.title, "organization": self.organization,
                "topic": topic, "focus": self.watch_for, "skill_levels": self.skill_levels}


def jr_video(slug, title, topics, watch_for, levels, creator=None):
    return Resource(f"jrnba_{slug.replace('-', '_')}", "video", title, "Jr. NBA",
                    f"https://jr.nba.com/video/{slug}/", topics, watch_for,
                    creator=creator, introductory="beginner" in levels, skill_levels=levels)


def usa_video(path, title, topics, watch_for, levels, creator=None):
    return Resource(f"usab_{path.rsplit('/', 1)[-1].replace('-', '_')}", "video", title, "USA Basketball",
                    f"https://www.usab.com/videos/{path}", topics, watch_for,
                    creator=creator, introductory="beginner" in levels, skill_levels=levels)


FOUNDATION = ("beginner", "intermediate")
DEVELOPING = ("intermediate", "advanced")


RESOURCES = (
    Resource("jrnba_two_hand_form", "video", "Form Shooting-2 Hands", "Jr. NBA",
             "https://jr.nba.com/video/form-shooting-2-hands/",
             ("arm", "finish", "preparation", "release", "timing", "knees"),
             "Watch how the guide hand supports the ball and how the legs and shooting arm extend through the finish.",
             creator="Dale Ellis"),
    Resource("usab_beef", "video", "BEEF - Acronym for Shooting Form", "USA Basketball",
             "https://www.usab.com/videos/2021/04/beef-acronym-for-shooting-form",
             ("mechanics", "stance", "finish", "arm"),
             "Pick one checkpoint to watch, such as balance before the lift or the finish after the ball leaves.",
             creator="Tara VanDerveer", introductory=True),
    Resource("jrnba_free_throw", "video", "Fundamentals of the Free Throw", "Jr. NBA",
             "https://jr.nba.com/video/fundamentals-of-the-free-throw/",
             ("routine", "timing"),
             "Watch the sequence before the shot and how a repeatable routine sets up its rhythm.",
             creator="Megan Griffith", introductory=True),
    Resource("jrnba_footwork", "video", "Set Up Your Footwork Before Your Shot", "Jr. NBA",
             "https://jr.nba.com/video/set-up-your-footwork-before-your-shot/",
             ("stance",),
             "Watch when the feet set during the one-two step and how that sets up the lift."),
    Resource("usab_shooting_tips", "article", "7 Tips To Improve Your Shooting Mechanics", "USA Basketball",
             "https://www.usab.com/news/2014/01/7-tips-to-improve-your-shooting-mechanics",
             ("timing", "knees", "mechanics"),
             "Read how the legs, trunk and shooting arm can contribute to one coordinated delivery.",
             creator="Jeff Haefner", section="Give Smooth Delivery"),
    Resource("jrnba_jump_shot", "article", "How to Shoot a Jump Shot", "Jr. NBA",
             "https://jr.nba.com/how-to-shoot-a-jump-shot/",
             ("landing", "release", "finish"),
             "Look at the example of finishing the shot and recovering balance after a stationary jump.",
             section="Steps 4–5"),
    Resource("usab_basic_jump_shot", "article", "The Basic Jump shot", "USA Basketball",
             "https://www.usab.com/news/2023/05/the-basic-jump-shot",
             ("distance", "timing"),
             "In the range discussion, look for the point at which moving back makes you force the shot.",
             section="Shooting", introductory=True),
    Resource("release_variability_study", "article",
             "The Relationship of Intra-Individual Release Variability with Distance and Shooting Performance in Basketball",
             "Journal of Sports Science and Medicine", "https://pmc.ncbi.nlm.nih.gov/articles/PMC8256521/",
             ("distance", "individual"),
             "Notice that the study separates changes in release conditions with distance from repeatability at a given distance.",
             creator="Nathan Slegers, Davin Lee and Grant Wong", section="Abstract and Key points",
             skill_levels=DEVELOPING),
    jr_video("1-step-form-shooting", "1-Step Form Shooting", ("one_two_footwork", "close_first"),
             "Watch how the step establishes the base before the lift.", FOUNDATION, "Dale Ellis"),
    jr_video("jump-stop-shooting-drill", "Jump Stop Shooting Drill", ("jump_stop_base", "stable_base"),
             "Focus on the two-foot stop and the balance of the base before shooting.", FOUNDATION, "Jon Babul"),
    jr_video("partner-step-in-shooting-drill", "Partner Step-In Shooting Drill", ("step_in", "one_two_footwork"),
             "Watch the order of the pass, foot contacts, and lift.", FOUNDATION, "Allan Houston"),
    jr_video("catch-turn-shoot-drill", "Catch, Turn and Shoot Drill", ("turn_balance",),
             "Watch how the shooter gets balanced after turning with the catch.", DEVELOPING, "Jeremiah Boswell"),
    jr_video("be-ready-to-shoot-off-the-catch", "Be Ready to Shoot Off the Catch", ("catch_ready", "rushed_catch"),
             "Look at what the shooter can prepare before the ball reaches them.", FOUNDATION, "Rick Carlisle"),
    jr_video("learn-to-shoot-off-the-dribble", "Learn to Shoot Off the Dribble", ("pullup_gather",),
             "Follow the last dribble, the gather and the step into the shot.", DEVELOPING, "Rick Carlisle"),
    jr_video("fundamentals-of-shooting", "Fundamentals of Shooting", ("close_first", "stable_base"),
             "Pick one part of the demonstration to watch, such as the setup or the lift.", FOUNDATION, "Allan Houston"),
    jr_video("perfect-shot-no-basket", "Perfect Shot (No Basket)", ("no_basket_delivery",),
             "Focus on the finish and the ball's visible path. Adapt to a no-release rehearsal if space is limited.",
             FOUNDATION, "Dale Ellis"),
    jr_video("make-it-take-it", "Make It, Take It", ("routine_pressure", "representative_practice"),
             "Watch how the scoring format adds pressure to familiar attempts.", DEVELOPING),
    jr_video("7-spot-shooting", "7 Spot Shooting", ("spot_map", "midrange_spots", "variable_practice"),
             "Notice how the drill organizes attempts by court location.", DEVELOPING),
    jr_video("around-the-world", "Around the World", ("spot_map", "intermediate_progression"),
             "Watch the order of the shooting locations so you can reproduce the same circuit.", FOUNDATION, "Dale Ellis"),
    jr_video("using-a-screen-shooting-drill", "Using a Screen Shooting Drill", ("screen_shooting",),
             "Watch how the route around the screen sets up the receiving footwork.", DEVELOPING, "Jeremiah Boswell"),
    jr_video("practice-the-shooting-proper-form", "Practice the Shooting Proper Form", ("blocked_practice",),
             "Choose one part of the stroke to watch across repetitions.", FOUNDATION, "Rick Carlisle"),
    jr_video("block-to-block-shooting-drill", "Block to Block Shooting Drill", ("midrange_spots", "intermediate_progression"),
             "Watch how the shooter relocates and resets as teammates rotate through the drill.", DEVELOPING, "Kiesha Brown"),
    jr_video("fundamentals-of-the-shot-fake", "Fundamentals of the Shot Fake", ("shot_fake_balance",),
             "Watch how the fake creates room while the shooter remains prepared to move.", FOUNDATION, "C.J. McCollum"),
    jr_video("the-shot-fake-breakdown-drill", "The Shot Fake Breakdown Drill", ("shot_fake_balance",),
             "Watch the preparation and reset before adding another action.", FOUNDATION, "C.J. McCollum"),
    jr_video("the-shot-fake-1-dribble-pull-up-drill", "The Shot Fake 1-Dribble Pull-Up Drill", ("fake_to_pullup",),
             "Follow the transition from fake to dribble and the final shooting gather.", DEVELOPING, "C.J. McCollum"),
    usa_video("2017/02/one-hand-form-shooting", "One Hand Form Shooting", ("one_hand_isolation", "forearm_support"),
              "Watch how the shooting hand supports and delivers the ball without the guide hand.", FOUNDATION),
    usa_video("2017/11/two-hand-shooting-from-a-self-pass", "Two-Hand Shooting From A Self-Pass", ("self_pass_transfer",),
              "Watch the sequence from the self-pass to the catch and shooting setup.", FOUNDATION),
    usa_video("2017/02/two-hand-form-shooting-shooting-with-a-jump", "Two-Hand Form Shooting - Shooting With A Jump",
              ("release_jump_timing", "line_drive_knee_arm"),
              "Watch how the upward movement and the arm delivery come together.", FOUNDATION),
    usa_video("2021/05/usa-basketball-shooting-drills", "USA Basketball Shooting Drills",
              ("close_first", "line_drive_knee_arm"),
              "Choose one part of the demonstrated delivery to observe across repetitions.", FOUNDATION, "John Calipari"),
    usa_video("2015/11/shooting-3-part-floater", "Shooting: 3 Part Floater", ("floater_touch",),
              "Watch how the floater is practiced in parts before applying it as a complete shot.", DEVELOPING),
    usa_video("2015/10/rapid-fire-shooting-drill", "Rapid Fire Shooting Drill", ("rushed_catch", "advanced_routine"),
              "Look for how the group organizes the next catch as the pace increases.", ("advanced",)),
    usa_video("2015/10/50-make-1-miss-shooting-drill", "50 Make 1 Miss Shooting Drill", ("routine_pressure",),
              "Watch how the scoring constraint changes the reset after a miss. Use a much smaller set if appropriate.",
              ("advanced",)),
    Resource("usab_three_point_practice", "article", "3 Ways to Make More 3-Point Shots", "USA Basketball",
             "https://www.usab.com/news/2014/01/3-ways-to-make-more-3-point-shots",
             ("range_ladder", "three_point_stationary_transfer"),
             "Read how the practice moves away from the basket in stages and note when the shot starts to feel forced.",
             section="Warm-Up Speed", skill_levels=DEVELOPING),
    Resource("usab_ray_allen_routine", "article", "Ray Allen's Pregame Shooting Routine", "USA Basketball",
             "https://www.usab.com/news/2014/01/ray-allens-pregame-shooting-routine",
             ("advanced_routine", "spot_map"),
             "Follow the progression across distances and spots. Use the sequence as an example for your own workload.",
             skill_levels=("advanced",)),
)

RESOURCE_OPTOUT = re.compile(r"\b(?:no|without|skip) (?:(?:a|an|any) )?(?:external )?(?:links?|resources?|tutorials?|videos?|articles?)\b|"
                             r"\b(?:do not|don['’]t) (?:send|recommend|link|suggest)\b[^.!?]{0,36}"
                             r"\b(?:videos?|articles?|links?|resources?|tutorials?)\b", re.I)
RESOURCE_REQUEST = re.compile(
    r"\b(?:recommend|suggest|find|send|share|link|want|need|know of|do you have|would like|where can i watch)\b[^.!?]{0,64}"
    r"\b(?:videos?|articles?|links?|resources?|tutorials?|instructional clips?|something to (?:watch|read))\b|"
    r"\b(?:show me|(?:can|could|may) i (?:see|watch|get)) (?:a|an|any|another)\b[^.!?]{0,48}"
    r"\b(?:videos?|articles?|resources?|tutorials?)\b|"
    r"^\s*(?:a|an|any|another) (?:(?:instructional|coaching) )?(?:videos?|articles?|resources?|tutorials?)\b", re.I,
)
CONTEXTUAL_RESOURCE_REQUEST = re.compile(
    r"\b(?:recommend|suggest|find|send|share|link|want|need|know of)\s+(?:me\s+)?"
    r"(?:(?:a|an|any|another|the)\s+)?(?:(?:instructional|coaching|basketball)\s+)*"
    r"(?:videos?|articles?|links?|resources?|tutorials?)(?:\s+please)?"
    r"(?:\s+and\s+(?:explain|tell me|say)\s+(?:what|where|how|why)\b[^.!?]*)?[?.!]*\s*$|"
    r"\b(?:another|that|this|same) (?:video|link|resource|article)\b", re.I,
)


def requested_resource_kind(question):
    if RESOURCE_OPTOUT.search(question) or not RESOURCE_REQUEST.search(question):
        return ""
    video = re.search(r"\b(?:videos?|clips?|watch)\b", question, re.I)
    article = re.search(r"\b(?:articles?|read)\b", question, re.I)
    if video and article:
        return "any"
    if video:
        return "video"
    if article:
        return "article"
    return "any"


def named_resources(query):
    normalized = f" {normalized_query(query)} "
    return [resource for resource in RESOURCES if f" {normalized_query(resource.title)} " in normalized]


def find_resources(query, topics, kind, *, experience="", history=(), limit=2):
    named = named_resources(query)
    recent_text = [turn["content"] for turn in history if turn["role"] == "assistant"]
    beginner = experience.casefold() in ("beginner", "new to basketball")
    level = "beginner" if beginner else "advanced" if experience.casefold() == "experienced" else experience.casefold()
    research = bool(re.search(r"\b(?:research|study|studies|paper|papers|trajectory|launch angle)\b", query, re.I))
    repeat_ok = bool(re.search(r"\b(?:again|same (?:link|video|article|resource))\b", query, re.I))
    ranked = []
    for resource in named or RESOURCES:
        if kind not in ("any", resource.kind):
            continue
        if not (named or repeat_ok) and any(resource.url in text for text in recent_text):
            continue
        topic = next((topic for topic in topics if topic in resource.topics), None)
        if topic is None and not named:
            continue
        topic = topic or resource.topics[0]
        score = (topics.index(topic) if topic in topics else 0,
                 research and resource.id != "release_variability_study",
                 bool(level and level not in resource.skill_levels),
                 beginner and not resource.introductory, resource.topics.index(topic))
        ranked.append((score, resource, topic))
    return [(resource, topic) for _, resource, topic in sorted(ranked, key=lambda item: item[0])[:limit]]
