"""Read-only tools bound to a single player snapshot for each coaching request."""

from collections import Counter
from functools import cached_property

from backend.app.agent.evidence import FORM_FIELDS, comparable, load_shots, shot_evidence
from backend.app.agent.profile import personal_profile
from backend.app.agent.session_analysis import summarize_session
from backend.app.agent.video import shot_frames
from backend.app.database.recordings import recording_details
from backend.app.database.sessions import owns_session


class CoachingTools:
    def __init__(self, player, selected=None, *, shots=None, session_id=None):
        self.player = player
        records = load_shots(player) if shots is None else shots
        self.shots = [shot for shot in records if shot.player == player]
        self.selected = self.resolve(selected)
        self.recording_shots = [shot for shot in self.shots if selected and shot.video_id == selected]
        self.recording = None
        if selected and not self.selected and not self.recording_shots:
            self.recording = recording_details(player, selected)
        inferred = self.recording_shots[0].session_id if len(self.recording_shots) > 1 else None
        if self.recording:
            inferred = self.recording["session_id"]
        self.session_id = session_id if session_id is not None else inferred
        self.session_shots = [shot for shot in self.shots if shot.session_id == self.session_id]
        self.session_unavailable = self.session_id is not None and not (
            self.session_shots or owns_session(player, self.session_id)
        )
        selected_session = (self.selected.session_id if self.selected else
                            self.recording_shots[0].session_id if self.recording_shots else inferred)
        if self.session_id is not None and selected_session is not None and selected_session != self.session_id:
            self.session_unavailable = True
        self.selection_unavailable = bool(selected and not (self.selected or self.recording_shots or self.recording))
        if self.session_unavailable:
            self.session_shots = []

    @cached_property
    def session_profile(self):
        focus = self.selected
        if focus not in self.session_shots:
            focus = self.recording_shots[0] if self.recording_shots else None
        return personal_profile(self.session_shots, focus)

    def session_summary(self):
        if self.session_id is None or self.session_unavailable:
            return {"status": "unavailable"}
        profile = self.session_profile
        return {"status": "available", "session_id": self.session_id, **summarize_session(self.session_shots),
                "profile_status": profile["status"], "likely_patterns": profile.get("likely_patterns", [])}

    def session_attempts(self, outcome="", offset=0):
        if self.session_id is None or self.session_unavailable or outcome not in ("", "made", "missed", "unknown"):
            return {"status": "unavailable"}
        shots = [shot for shot in self.session_shots if not outcome or shot.outcome == outcome]
        start = max(0, offset)
        return {"total": len(shots), "offset": start, "attempts": [
            {key: value for key, value in shot_evidence(shot).items()
             if key not in ("measurements", "limitations")}
            for shot in shots[start:start + 20]
        ]}

    def resolve(self, identifier):
        if not identifier:
            return None
        matches = [shot for shot in self.shots if identifier in (shot.shot_id, shot.video_id)]
        return matches[0] if len(matches) == 1 else None

    def shot_analysis(self, shot_id: str = "") -> dict:
        """Read measurements and outcome for a shot ID or the current selection."""
        shot = self.resolve(shot_id) if shot_id else self.selected
        return shot_evidence(shot) if shot else {"status": "unavailable"}

    def player_history(self, outcome: str = "", *, include_recent=True) -> dict:
        """Read recent owned shot IDs and counts, optionally filtering by recorded outcome."""
        counts = Counter(shot.outcome if shot.outcome in ("made", "missed") else "unknown"
                         for shot in self.shots)
        shots = [shot for shot in self.shots if not outcome or shot.outcome == outcome]
        return {"counts": {key: counts[key] for key in ("made", "missed", "unknown")},
                "manual_labels": sum(shot.outcome_source == "manual" for shot in self.shots),
                "recent": [{key: value for key, value in shot_evidence(shot).items()
                            if key not in ("measurements", "limitations")} for shot in (shots[-12:] if include_recent else ())]}

    def compare_shots(self, first_id: str, second_id: str) -> dict:
        """Compare two explicitly identified owned shots in the supplied order."""
        first, second = self.resolve(first_id), self.resolve(second_id)
        if not first or not second or first == second:
            return {"status": "unavailable"}
        before, after = shot_evidence(first), shot_evidence(second)
        differences = {}
        for field in FORM_FIELDS:
            left, right = before["measurements"][field], after["measurements"][field]
            if left["status"] == right["status"] == "valid":
                differences[field] = {"first": left["value"], "second": right["value"],
                                      "second_minus_first": round(right["value"] - left["value"], 2),
                                      "unit": left["unit"]}
        return {"status": "available", "id": f"pair:{first.shot_id}:{second.shot_id}",
                "first": before, "second": after, "matched_recorded_conditions": comparable(first, second),
                "differences": differences,
                "limitations": ["Similar recorded shot type and arm do not verify camera, distance or fatigue.",
                                "A two-shot comparison does not establish a pattern or cause."]}

    def make_miss_pair(self, anchor_id: str = "") -> dict:
        """Find an opposite-outcome shot matching the anchor's known conditions."""
        anchor = self.resolve(anchor_id) if anchor_id else self.selected
        scope = self.session_shots if self.session_id is not None else self.shots
        if not anchor or anchor not in scope or anchor.outcome not in ("made", "missed"):
            return {"status": "unavailable"}
        opposite = "missed" if anchor.outcome == "made" else "made"
        matches = [shot for shot in reversed(scope)
                   if comparable(anchor, shot) and shot.outcome == opposite]
        matches.sort(key=lambda shot: (shot.session_id != anchor.session_id, shot.outcome_source != "manual"))
        return self.compare_shots(anchor.shot_id, matches[0].shot_id) if matches else {"status": "unavailable"}

    @cached_property
    def profile(self):
        return personal_profile(self.shots, self.selected)

    def form_profile(self) -> dict:
        """Retrieve statistical associations, contributing shot IDs and caveats."""
        return self.profile

    def video_frames(self, shot_id: str = "", phases=None, *, focus="", from_phase="") -> list:
        """Decode verified phase frames for an owned shot."""
        shot = self.resolve(shot_id) if shot_id else self.selected
        if shot and shot.analysis.get("synthetic") is True:
            return []  # Synthetic measurements have no visual evidence to decode.
        if not shot:
            return []
        if focus:
            return shot_frames(shot, phases, focus=focus, from_phase=from_phase)
        return shot_frames(shot, phases)
