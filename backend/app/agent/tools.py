
import json
from pathlib import Path

from backend.app.database.shot_history import (
    get_player_history,
)
from backend.app.analysis.shot_comparison import (
    compare_shots,
)
from backend.app.database.outcome_labels import (
    apply_outcome_label,
)
from backend.app.ml.form_profile import (
    build_form_profile,
)


ROOT = Path(__file__).resolve().parents[3]


def get_shot_analysis(video_id: str) -> dict:
    """
    Return the unified analysis for a video.
    """
    # Accept only a simple video identifier.
    if (
        not video_id
        or Path(video_id).name != video_id
        or video_id in (".", "..")
        or "/" in video_id
        or "\\" in video_id
    ):
        return {"error": "Invalid video ID"}

    path = (
        ROOT
        / "outputs"
        / video_id
        / "shot_analysis.json"
    )

    if not path.is_file():
        return {
            "error": f"No analysis found for {video_id}"
        }

    with path.open(encoding="utf-8") as file:
        analysis = json.load(file)

    # Include any manual outcome label from the database.
    return apply_outcome_label(analysis)


def get_player_shot_history(player_name: str) -> dict:
    """
    Retrieve stored shots for a player.
    """
    history = get_player_history(player_name)

    return {
        "player": player_name,
        "total_shots": len(history),
        "shots": history,
    }


def compare_player_shots(player_name: str) -> dict:
    """
    Compare the two most recently stored shots.
    """
    comparison = compare_shots(player_name)

    if comparison is None:
        return {
            "player": player_name,
            "status": "insufficient_data",
            "message": (
                "Two stored shots are required "
                "for comparison."
            ),
        }

    return {
        "status": "success",
        "comparison": comparison,
        "warning": (
            "Differences do not necessarily indicate "
            "improvement. Review measurement quality "
            "and experimental segmentation results."
        ),
    }


def get_personal_form_profile(player_name: str) -> dict:
    """
    Compare the player's form on made and missed shots
    across all of their sessions.
    """
    return build_form_profile(player_name)


if __name__ == "__main__":
    print("=== SHOT ANALYSIS ===")
    analysis = get_shot_analysis("free_throw_03")

    print(json.dumps({
        "video_id": analysis.get("video_id"),
        "biomechanics": analysis.get("biomechanics"),
        "shot_outcome": analysis.get("shot_outcome"),
    }, indent=2))

    print("\n=== PLAYER HISTORY ===")
    history = get_player_shot_history("TestPlayer")

    print(json.dumps(history, indent=2))

    print("\n=== SHOT COMPARISON ===")
    comparison = compare_player_shots("TestPlayer")

    print(json.dumps(comparison, indent=2))
