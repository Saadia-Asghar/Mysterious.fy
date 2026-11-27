# Event correlation

Groups related events by time window and topology. An upstream switch fault becomes one incident; unrelated failures stay apart.

Status: implemented on dev (see code in this folder and tests/test_intelligence.py). Not yet evaluated on real runs (M14).

## `upstream_anchor_quorum_v2`

Kept alongside v1 so both can be evaluated (`correlate_with(method, ...)`).

1. An event joins the group of an alerting ancestor whose event is within the window, before or after it. The nearest one wins, so slow cascades still attach to their switch.
2. Events no alerting ancestor explains are clustered per shared immediate parent. A cluster becomes one incident only if at least `quorum` (0.5, fixed before evaluation) of that parent's known children failed and two or more devices are involved. Otherwise each event stays separate.

Known limit: a device that fails on its own while its upstream is already down cannot be told apart from part of that outage using alerts alone.
