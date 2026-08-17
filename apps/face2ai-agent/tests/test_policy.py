from __future__ import annotations

from datetime import datetime, timedelta, timezone

from face2ai_agent.config import AgentConfig
from face2ai_agent.policy import GreetingPolicy, build_instructions
from face2ai_agent.presence import PresenceMemory, StoreChange, Transition

T0 = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def known(name: str, ident: str, at: datetime = T0) -> Transition:
    return Transition(at=at, from_state="NO_FACE", to_state="KNOWN", identity_id=ident, display_name=name, faces=1)


def test_known_person_greeted_once_per_cooldown_and_new_person_immediately():
    policy = GreetingPolicy(AgentConfig(language="de"), cooldown_seconds=15)
    first = policy.on_transition(known("Ada", "a"), T0)
    assert first is not None and first.kind == "greet_known" and "Ada" in first.instructions
    assert first.fallback_text == "Hallo Ada."
    assert policy.on_transition(known("Ada", "a"), T0 + timedelta(seconds=5)) is None
    assert policy.on_transition(known("Bo", "b"), T0 + timedelta(seconds=6)) is not None
    again = policy.on_transition(known("Ada", "a"), T0 + timedelta(seconds=16))
    assert again is not None and again.display_name == "Ada"


def test_unknown_and_multiple_are_rate_limited_and_configurable():
    policy = GreetingPolicy(AgentConfig(language="en", unknown_greeting_cooldown_seconds=60))

    def unknown_at(at):
        return Transition(at=at, from_state="NO_FACE", to_state="UNKNOWN", identity_id=None, display_name=None, faces=1)

    prompt = policy.on_transition(unknown_at(T0), T0)
    assert prompt is not None and prompt.kind == "greet_unknown"
    assert "Do not guess a name" in prompt.instructions
    assert "Learn person" in prompt.fallback_text
    assert policy.on_transition(unknown_at(T0 + timedelta(seconds=30)), T0 + timedelta(seconds=30)) is None
    assert policy.on_transition(unknown_at(T0 + timedelta(seconds=61)), T0 + timedelta(seconds=61)) is not None

    def multiple_at(at):
        return Transition(at=at, from_state="UNKNOWN", to_state="MULTIPLE_FACES", identity_id=None, display_name=None, faces=2)

    assert policy.on_transition(multiple_at(T0), T0).kind == "announce_multiple"
    assert policy.on_transition(multiple_at(T0 + timedelta(seconds=10)), T0 + timedelta(seconds=10)) is None
    unknown = unknown_at(T0)
    multiple = multiple_at(T0)

    silent = GreetingPolicy(AgentConfig(greet_unknown=False, announce_multiple=False, greet_known=False))
    assert silent.on_transition(unknown, T0) is None
    assert silent.on_transition(multiple, T0) is None
    assert silent.on_transition(known("Ada", "a"), T0) is None


def test_no_face_and_no_signal_are_silent():
    policy = GreetingPolicy(AgentConfig())
    for state in ("NO_FACE", "NO_SIGNAL"):
        t = Transition(at=T0, from_state="KNOWN", to_state=state, identity_id=None, display_name=None, faces=0)
        assert policy.on_transition(t, T0) is None


def test_enrollment_is_welcomed_and_suppresses_immediate_regreet():
    policy = GreetingPolicy(AgentConfig(language="de"), cooldown_seconds=15)
    prompt = policy.on_store_change(StoreChange(at=T0, kind="enrolled", identity_id="a", display_name="Ada", identity_count=1), T0)
    assert prompt is not None and prompt.kind == "welcome_enrolled" and prompt.fallback_text.startswith("Willkommen, Ada")
    assert policy.on_transition(known("Ada", "a", T0 + timedelta(seconds=5)), T0 + timedelta(seconds=5)) is None  # just welcomed
    assert policy.on_transition(known("Ada", "a", T0 + timedelta(seconds=16)), T0 + timedelta(seconds=16)) is not None
    assert policy.on_store_change(StoreChange(at=T0, kind="deleted", identity_id="a", display_name="Ada", identity_count=0), T0) is None


def test_stale_transitions_and_store_changes_are_not_spoken():
    policy = GreetingPolicy(AgentConfig(language="de"))
    old = known("Ada", "a", T0)
    assert policy.on_transition(old, T0 + timedelta(seconds=25)) is None  # replayed / delayed by > 20 s
    assert policy.on_transition(known("Ada", "a", T0), T0 + timedelta(seconds=5)) is not None
    stale_store = StoreChange(at=T0, kind="enrolled", identity_id="b", display_name="Bo", identity_count=2)
    assert policy.on_store_change(stale_store, T0 + timedelta(seconds=60)) is None


def test_instructions_contain_rules_language_and_live_situation():
    memory = PresenceMemory()
    memory.apply_hello({"presence": {"state": "KNOWN", "display_name": "Ada", "identity_id": "a"}})
    text = build_instructions(AgentConfig(language="de", agent_name="Mira"), memory, T0)
    assert "You are Mira" in text
    assert "Always answer in German" in text
    assert "never a login" in text
    assert "Never invent a name" in text
    assert "Ada is in front of the camera" in text
    persona = build_instructions(AgentConfig(persona="Du bist ein Pirat."), memory, T0)
    assert persona.startswith("Du bist ein Pirat.")
