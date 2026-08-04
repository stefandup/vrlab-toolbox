from mooi_toolbox.processing.lsl import LslEventSpecification, LslIntervalSpecifications

BASELINE_START_SPEC = LslEventSpecification(stream="VR_markers", column="Markers", event=10)
BASELINE_START_FALLBACK_SPEC = LslEventSpecification(
    stream="VR_trial_events", column="VR_trial", event="RaiseSafetyPlatform", offset_seconds=-300
)
BASELINE_END_SPEC = LslEventSpecification(
    stream="VR_trial_events", column="VR_trial", event="RaiseSafetyPlatform"
)

STRESS_START_SPEC = LslEventSpecification(
    stream="VR_trial_events", column="VR_trial", event="RaiseMainPlatform"
)
STRESS_END_SPEC = LslEventSpecification(
    stream="VR_trial_events", column="VR_trial", event="MainPlatformAtMin"
)

RECOVERY_START_SPEC = LslEventSpecification(
    stream="VR_trial_events", column="VR_trial", event="MainPlatformAtMin"
)
RECOVERY_END_SPEC = LslEventSpecification(
    stream="VR_trial_events", column="VR_trial", event="RunFOHQuestions"
)

BASELINE_INTERVAL = LslIntervalSpecifications(
    start=BASELINE_START_SPEC, end=BASELINE_END_SPEC, start_fallback=BASELINE_START_FALLBACK_SPEC
)
STRESS_INTERVAL = LslIntervalSpecifications(start=STRESS_START_SPEC, end=STRESS_END_SPEC)
RECOVERY_INTERVAL = LslIntervalSpecifications(start=RECOVERY_START_SPEC, end=RECOVERY_END_SPEC)

FOH_TRIAL_INTERVALS: dict[str, LslIntervalSpecifications] = {
    "baseline": BASELINE_INTERVAL,
    "stress": STRESS_INTERVAL,
    "recovery": RECOVERY_INTERVAL,
}
