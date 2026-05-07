# Terminal vs GUI Agent: Fundamental Differences

## Constraint Enforcement

GUI interfaces enforce validity constraints that terminal commands do not.

**Example: Brightness minimum (tasks 26, 44)**

- **GUI agent**: drags the Settings brightness slider to the leftmost position. The slider physically stops at brightness=1. The agent cannot overshoot — the UI enforces the valid range.
- **Terminal agent**: runs `settings put system screen_brightness 0`. The command succeeds silently. Nothing indicates that 0 is outside the valid range. The agent has no way to discover that the UI-defined minimum is 1, not 0.

The AndroidWorld evaluator (`_SystemBrightnessToggle.is_successful`) checks `settings get system screen_brightness` and expects exactly `1` for "min". This matches what the Settings UI produces, but a terminal agent operating below the UI layer can set values the UI would never allow.

**Conclusion**: this is an evaluator mismatch, not an agent failure. The terminal agent correctly sets brightness to the lowest possible value (0), but the evaluator defines "min" as the lowest value the Settings slider allows (1).
