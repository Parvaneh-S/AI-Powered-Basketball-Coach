
import os
import sys
import time
from backend.app.rag.knowledge_retriever import (
    search_coaching_knowledge,
)

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ServerError

from backend.app.agent.tools import (
    get_shot_analysis,
    get_player_shot_history,
    compare_player_shots,
)


# Load environment variables from the project's .env file.
load_dotenv()

MODEL = os.getenv("SHOTCOACH_MODEL", "gemini-3.8-flash")

MAX_ATTEMPTS = 2


SYSTEM_INSTRUCTION = """
You are ShotCoach, an AI basketball coaching agent.

Your job is to help players understand their shooting
mechanics using measured data and player history.

Rules:

1. Call relevant tools before making claims about a player's
   measurements, history, or shot outcomes.

2. Never invent measurements, outcomes, or player history.

3. Measurement quality 'pass' means sufficient measurement
   coverage, not confirmed biomechanical accuracy.

4. Explicitly mention any 'review' measurement status.

5. Shot segmentation and shot-outcome detection are
   experimental and may contain errors.

6. Never interpret 'unknown' as 'made' or 'missed'.

7. Numerical differences do not automatically indicate
   improvement or deterioration.

8. Database insertion order does not necessarily reflect
   the actual chronological order of recorded shots.

9. If there are too few reliable shots, explain that
   personalized form-to-outcome conclusions are unavailable.

10. Keep feedback clear, concise, constructive,
    and appropriate for a basketball player.

11. When the player asks for coaching recommendations or
explanations of shooting mechanics, call coaching_knowledge
to retrieve relevant basketball coaching references.

Use the retrieved coaching knowledge together with
the player's actual biomechanical measurements.

Clearly distinguish measured player data from general
coaching guidance.

Include source names and URLs when presenting
knowledge-based recommendations.

Do not invent coaching sources or claim that retrieved
knowledge proves a specific joint angle is optimal.

If retrieval returns irrelevant information, do not use
it as evidence.

12. shooting_motion_ms measures the time between detected
    shot start and ball release, not total shot duration.

13. Large differences in knee or elbow measurements
    may result from pose-estimation or segmentation errors.
    Do not present them as confirmed changes in technique.

14. Clearly distinguish observed measurements,
    possible interpretations, and practical suggestions.

15. Do not claim that a shot was made or missed unless
    the available outcome data supports that conclusion.

16. Do not prescribe specific ideal joint-angle ranges
    unless supported by retrieved coaching knowledge.

17. Until RAG is implemented, provide general technique
    suggestions without unsupported numerical targets.

18. If a tool returns an error, do not invent its result.
    Use available evidence or explain the limitation.

    19. When reporting shooting_motion_ms, use the exact value
    returned by the tools. Do not calculate it from frame
    numbers or timestamps.

20. Treat biomechanics.shooting_motion_ms as the
    authoritative shooting-motion duration for each shot.

21. When tools provide a precomputed comparison,
    use its numeric values directly. Do not recalculate
    existing differences.

22. If two tools return conflicting measurements,
    explicitly report the inconsistency rather than
    choosing or inventing a value.
"""


def ask_coach(player_name: str, question: str) -> str:
    """
    Ask the Gemini coaching agent a question.

    Gemini can automatically call our existing tools:
    - Shot analysis
    - Player history
    - Shot comparison
    """

    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Add it to your .env file."
        )

    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY")
    )

    # --------------------------------------------------
    # Tool 1: Individual shot analysis
    # --------------------------------------------------


    def shot_analysis(video_id: str) -> dict:
        """
        Retrieve detailed analysis for one recorded shot.

        Accepts either:
        - Video ID, such as free_throw_03
        - Shot ID, such as free_throw_03_shot_1

        Args:
            video_id: A video ID or shot ID belonging to
                the current player.
        """

        history = get_player_shot_history(player_name)
        shots = history.get("shots", [])

        matching_shot = next(
            (
                shot for shot in shots
                if video_id in (
                    shot["video_id"],
                    shot["shot_id"],
                )
            ),
            None,
        )

        if matching_shot is None:
            return {
                "error": (
                    "Shot not found for the current player"
                )
            }

        resolved_video_id = matching_shot["video_id"]

        print(
            f"[Tool called: shot_analysis("
            f"{resolved_video_id})]"
        )

        return get_shot_analysis(resolved_video_id)


    # --------------------------------------------------
    # Tool 2: Player history
    # --------------------------------------------------

    def player_history() -> dict:
        """
        Retrieve the current player's recorded shot history.
        """

        print("[Tool called: player_history]")

        return get_player_shot_history(player_name)

    # --------------------------------------------------
    # Tool 3: Shot comparison
    # --------------------------------------------------

    def shot_comparison() -> dict:
        """
        Compare the two most recently stored shots
        belonging to the current player.
        """

        print("[Tool called: shot_comparison]")

        return compare_player_shots(player_name)


    # --------------------------------------------------
    # Tool 4: Semantic coaching knowledge retrieval
    # --------------------------------------------------

    def coaching_knowledge(query: str) -> dict:
        """
        Search source-referenced basketball coaching
        knowledge using local semantic embeddings.

        Args:
            query: A basketball shooting mechanics topic
                or coaching question.
        """

        print(
            f"[Tool called: coaching_knowledge({query})]"
        )

        return search_coaching_knowledge(
            query=query,
            top_k=2,
        )

    # --------------------------------------------------
    # Initialize Gemini chat session
    # --------------------------------------------------

    try:
        chat = client.chats.create(
            model=MODEL,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                tools=[
                    shot_analysis,
                    player_history,
                    shot_comparison,
                    coaching_knowledge,
                ],
                automatic_function_calling=(
                    types.AutomaticFunctionCallingConfig(
                        maximum_remote_calls=6
                    )
                ),
                temperature=0.2,
            ),
        )

        # ----------------------------------------------
        # Send question with limited retry handling
        # ----------------------------------------------

        for attempt in range(MAX_ATTEMPTS):

            try:
                response = chat.send_message(question)

                return response.text or (
                    "Gemini returned no text response."
                )

            except ServerError as error:

                # Only handle temporary 503 errors.
                if error.code != 503:
                    raise

                if attempt == MAX_ATTEMPTS - 1:
                    return (
                        "Gemini is temporarily unavailable "
                        "due to high demand. "
                        "Please try your coaching question "
                        "again later."
                    )

                delay = 2 ** (attempt + 1)

                print(
                    f"[Gemini 503: service unavailable. "
                    f"Retrying after {delay} seconds...]"
                )

                time.sleep(delay)

    finally:
        client.close()


# ------------------------------------------------------
# Command-line interface
# ------------------------------------------------------

if __name__ == "__main__":

    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: python -m "
            "backend.app.agent.coaching_agent "
            "<player_name> <question>"
        )

    player_name = sys.argv[1]
    question = " ".join(sys.argv[2:])

    print("\n=== AI BASKETBALL COACH ===")
    print(f"Model: {MODEL}")
    print(f"Player: {player_name}\n")

    answer = ask_coach(
        player_name=player_name,
        question=question,
    )

    print("\n=== COACHING FEEDBACK ===\n")
    print(answer)
