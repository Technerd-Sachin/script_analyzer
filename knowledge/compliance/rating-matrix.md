---
type: rating_matrix
bands: ["U", "U/A 7+", "U/A 13+", "U/A 16+", "A"]
categories: [violence, language, sex, nudity, substances, imitable_behaviour, discrimination, theme]
matrix:
  violence:
    mild: "U/A 7+"
    moderate: "U/A 13+"
    strong: "U/A 16+"
    explicit: "A"
  language:
    mild: "U/A 7+"
    moderate: "U/A 13+"
    strong: "U/A 16+"
    explicit: "A"
  sex:
    mild: "U/A 7+"
    moderate: "U/A 13+"
    strong: "U/A 16+"
    explicit: "A"
  nudity:
    mild: "U/A 13+"
    moderate: "U/A 16+"
    strong: "A"
    explicit: "A"
  substances:
    mild: "U/A 7+"
    moderate: "U/A 13+"
    strong: "U/A 16+"
    explicit: "A"
  imitable_behaviour:
    mild: "U/A 7+"
    moderate: "U/A 13+"
    strong: "U/A 16+"
    explicit: "A"
  discrimination:
    mild: "U/A 7+"
    moderate: "U/A 13+"
    strong: "U/A 16+"
    explicit: "A"
  theme:
    mild: "U/A 7+"
    moderate: "U/A 13+"
    strong: "U/A 16+"
    explicit: "A"
guidance:
  violence:
    mild: "non-graphic, no injury detail"
    moderate: "fights, blood, threat"
    strong: "graphic injury, sustained or brutal violence"
    explicit: "gory, sexual violence depicted"
  language:
    mild: "mild insults"
    moderate: "strong insults"
    strong: "strong expletives"
    explicit: "frequent sexual or aggressive expletives"
  sex:
    mild: "romantic affection, kissing"
    moderate: "references, innuendo"
    strong: "implicit sexual activity"
    explicit: "explicit sexual activity"
  nudity:
    mild: "brief, non-sexual, partial"
    moderate: "non-sexual nudity"
    strong: "sexual context"
    explicit: ""
  substances:
    mild: "references only"
    moderate: "alcohol or tobacco use depicted"
    strong: "illicit drug use depicted"
    explicit: "glamorised or instructional drug use"
  imitable_behaviour:
    mild: "minor risky acts"
    moderate: "dangerous acts children could copy"
    strong: "self-harm or suicide depicted"
    explicit: "method detail or instructional"
  discrimination:
    mild: "stereotype that is challenged"
    moderate: "discriminatory language, not endorsed"
    strong: "endorsed or repeated, slurs"
    explicit: "legal flag (incitement)"
  theme:
    mild: ""
    moderate: "death, crime, betrayal"
    strong: "abuse, suicide, sustained trauma"
    explicit: ""
treatment_raise: ["glorified", "instructional"]
# House rule (not from the Schedule): content that is only talked about, not shown, sits one band lower,
# reflecting the general factors "context, theme, tone and impact". Remove "referenced" to disable.
mode_lower: ["referenced"]
verified: false
---
House rating matrix v1. Editable. Derived from the IT Rules 2021 Schedule category list; it is not the official per-band text.

- Band = the highest `matrix[category][severity]` over all findings. No findings at all gives U.
- A `glorified` or `instructional` treatment raises that finding's band by one step, capped at A.
- Discrimination at `explicit` also raises a legal risk flag (incitement).
- Severity `none` adds no band.
