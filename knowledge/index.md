---
type: index
okf_version: "0.2"
---
# Bullet Script Analyzer knowledge bundle

Plain Markdown files with YAML frontmatter, following the Open Knowledge Format (OKF) v0.2 (`GoogleCloudPlatform/open-knowledge-format`, SPEC.md, checked 2026-10-19). Code reads these files; prompts receive their rendered text. Files are short because the analysis model has a 16k token context.

## OKF conventions followed
- `type` is present in every concept file (the only required key).
- Bundle-specific keys are added per `type` (OKF allows extra keys).
- `okf_version` is declared in this root index.

## Deviations from OKF v0.2 (kept for the project's Pydantic contract)
- This index carries `type: index`. OKF says index files have no frontmatter except `okf_version`.
- `verified: false` is a boolean meaning "not yet reviewed by the user". OKF defines `verified` as a list of `{by, at}` events, and absence means unverified.
- `sources` is a list of URL strings. OKF defines entries as mappings with a required `resource` key.

## Files
- `rubric/<factor>.md` (`rubric_factor`): the 8 engagement factors with weight, 1-5 anchors and scoring guidance for 1-2 minute vertical episodes. Weights sum to 1.0.
- `rubric/calibration.md` (`calibration`): one strong and one weak sample script with gold factor scores.
- `craft/opening_strategies.md`, `craft/cliffhanger_techniques.md` (`craft_reference`): strategy ids for alternative openings and endings.
- `craft/micro_drama_conventions.md` (`craft_reference`): format and genre conventions.
- `craft/emotion_taxonomy.md` (`emotion_taxonomy`): Plutchik's 8 emotions and the Reagan et al. (2016) arc shapes.
- `tropes/taxonomy.md` (`trope_taxonomy`): about 40 Indian TV and micro-drama tropes with cue words.
- `compliance/it-rules-2021-classification.md` (`compliance_rule`): IT Rules 2021 bands, display and access controls, Schedule categories.
- `compliance/rating-matrix.md` (`rating_matrix`): house matrix v1, category by severity to band.
- `compliance/notice-tobacco-cotpa-2023.md`, `compliance/notice-narcotics-mib-2026.md` (`compliance_rule`): statutory notices and their triggers.
- `compliance/legal-risk-flags.md` (`legal_risk_flags`): flags for legal review, never determinations.
- `localization/subtitle-rules.md` (`subtitle_rules`): subtitle check limits.
- `localization/profiles/<lang>.md` (`localization_profile`): hi, ta, te, bn, mr, en.
- `lexicons/*.txt` (plain lists, not OKF): prescan terms for code-mix detection and the rating categories. `profanity.txt` lines are `severity<TAB>term`.
- `trends/<trope>.md` (`trend`): generated later by `bsa trends refresh`.

All compliance files are `verified: false` until the user reviews them. Ratings are estimates to support editors, not certification or legal advice.
