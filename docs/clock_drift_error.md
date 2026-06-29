# Clock Drift Error Notes

## Problem

Behavior trial starts from the validated Unreal/VR behavior file match the
hardware trigger sequence at the beginning of the recording, but the timing
difference grows across trials.

Observed example:

```text
Best deltas:
[0.015, 0.626, 1.419, 2.203, 3.043, 3.560, 4.033, 4.767, 5.252, 5.707]

Signed deltas:
[-0.015, -0.626, -1.419, -2.203, -3.043, -3.560, -4.033, -4.767, -5.252, -5.707]
```

The signed deltas are increasingly negative:

```text
behavior_start - trigger_start < 0
```

This means the behavior timestamps become earlier relative to the recorded
hardware trigger timestamps as the session progresses.

## Diagnostic Evidence

Spacing between consecutive behavior starts is consistently shorter than the
spacing between consecutive trigger starts:

```text
behav_spacing=115.256, trigger_spacing=115.867, spacing_error=-0.611
behav_spacing=99.056,  trigger_spacing=99.848,  spacing_error=-0.792
behav_spacing=97.544,  trigger_spacing=98.329,  spacing_error=-0.785
behav_spacing=107.889, trigger_spacing=108.728, spacing_error=-0.840
```

So this is probably not one bad Arduino trigger. It looks like a systematic
timebase mismatch.

## Likely Cause

The Unreal task may trigger the Arduino and save a timestamp close together,
but those timestamps may not come from the same effective clock as the recorded
hardware trigger stream.

Possible timebases involved:

- Unreal game/session time saved in the behavior file.
- Trigger pulse arrival time recorded by the acquisition/LSL/Biopac system.
- A separate recording PC or acquisition clock.

Important point: this drift is probably too large to be normal quartz clock
drift. The observed drift is roughly 0.5% to 0.8%, or about 5-8 ms per second.
That is much larger than expected for ordinary PC quartz clocks, so the more
likely explanation is a software/timebase mismatch, such as Unreal game time
versus recorder time.

## Working Interpretation

The behavior timeline appears compressed relative to the hardware trigger
timeline.

In plain English:

> The two clocks start nearly aligned, but the Unreal behavior clock is walking
> slightly slower/shorter than the recorder trigger clock. Small differences
> accumulate until later trial starts are several seconds away.

## Processing-Side Solution

Correct this in processing by mapping behavior time onto recorder/trigger time.

Use matched pairs:

```text
(behavior_trial_start, trigger_trial_start)
```

Fit a linear conversion:

```python
recorder_time = slope * behavior_time + intercept
```

Then apply the conversion to both starts and ends of behavior intervals:

```python
corrected_start = slope * behav_start + intercept
corrected_end = slope * behav_end + intercept
```

Because the error accumulates over time, a single offset is not enough. The
correction needs both:

- an offset, handled by `intercept`
- a stretch/compression factor, handled by `slope`

Expected result: `slope` should be slightly greater than `1.0`, because behavior
time appears compressed compared with trigger time.

## Matching Notes

The matching logic should avoid reusing trigger intervals:

- Build candidate trigger intervals.
- Match each behavior trial start to the nearest unused trigger start.
- After a successful match, remove that trigger from the remaining candidates.

If behavior starts correspond only to even trigger points, candidate triggers
should eventually be filtered to `TP0`, `TP2`, `TP4`, etc.

## Tomorrow's Next Step

Add a small correction step after initial matching:

1. Collect matched behavior starts and trigger starts.
2. Fit `slope` and `intercept`.
3. Convert all behavior interval starts and ends into trigger/recorder time.
4. Use corrected behavior intervals for slicing physiology data.

