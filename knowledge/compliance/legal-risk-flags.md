---
type: legal_risk_flags
flags:
  - id: defamation_real_person_or_brand
    name: Real person or brand shown negatively
    description: "A real, identifiable person, company or brand is named or clearly implied and shown committing crimes, lying or failing. Defamation exposure."
    severity: high
  - id: religious_caste_regional_hurt
    name: Religious, caste or regional hurt
    description: "Slurs, mockery or demeaning portrayal of a religion, caste, community or region, including caste slurs that may attract the SC/ST (Prevention of Atrocities) Act 1989."
    severity: high
  - id: national_symbols_misuse
    name: Misuse of national symbols
    description: "Disrespect to or misuse of the national flag, anthem, emblem or similar symbols."
    severity: medium
  - id: minors_sexual_or_violent
    name: Minors in sexual or violent content
    description: "Any sexual content involving a minor, or serious violence against a minor. POCSO Act 2012 exposure. Always the highest severity."
    severity: critical
  - id: code_of_ethics_general
    name: Code of Ethics general principles
    description: "Content that may be prohibited by law or a court, or that touches the sovereignty and integrity of India, state security, friendly relations with foreign countries, incitement to violence or public order, or racial and religious groups without due caution."
    severity: medium
sources:
  - https://www.meity.gov.in/static/uploads/2024/02/Information-Technology-Intermediary-Guidelines-and-Digital-Media-Ethics-Code-Rules-2021-updated-06.04.2023-.pdf
verified: false
---
These are flags for legal review, never legal determinations. Raise a flag only with line IDs and a one-line reason. A flag does not change the rating band by itself, except that `minors_sexual_or_violent` must always be surfaced first.

The Code of Ethics general principles (IT Rules 2021, Appendix, II(A)) are from the official MeitY text. The statute names in the descriptions are for reviewer orientation and are not verified.
