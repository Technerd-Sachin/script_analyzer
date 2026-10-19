---
type: subtitle_rules
max_chars_per_line: 42
max_lines: 2
min_duration_s: 0.833
max_duration_s: 7.0
reading_speed_cps: 17
sources:
  - https://backlothelp.netflix.com/hc/en-us/articles/115003196707
  - https://backlothelp.netflix.com/hc/en-us/articles/4481912003987-Tamil-Timed-Text-Style-Guide
  - https://backlothelp.netflix.com/hc/en-us/articles/4482320288787-Telugu-Timed-Text-Style-Guide
  - https://backlothelp.netflix.com/hc/en-us/articles/215758617
---
Defaults for the subtitle check. Checked on 2026-10-19 (the backlothelp URLs now redirect to partnerhelp.netflixstudios.com).

- 42 characters per line and at most 2 lines: stated in the Netflix Hindi, Tamil and Telugu timed text style guides.
- Event duration from 5/6 s (0.833 s) to 7 s: stated in the Netflix general timed text requirements, not in the three Indic guides.
- 17 characters per second is a general adult reading-speed benchmark chosen for this project. It is not a Netflix Indic figure: the Hindi, Tamil and Telugu guides allow up to 22 cps for adult programmes and 18 cps for children's programmes. Configurable.

Line duration is estimated from the word-based runtime model, so results are estimates.
