---
type: emotion_taxonomy
emotions:
  - id: joy
    valence: positive
    description: "Happiness, relief or delight at a gain or reunion."
    cues: [smile, laugh, celebrate, khushi, hasna, mubarak]
  - id: trust
    valence: positive
    description: "Faith, loyalty or acceptance toward another person."
    cues: [promise, believe, vaada, bharosa, yakeen, saath]
  - id: fear
    valence: negative
    description: "Dread or alarm at a threat to self or loved ones."
    cues: [scared, threat, darr, bachao, kaanp, dhamki]
  - id: surprise
    valence: neutral
    description: "Shock at the unexpected; can turn positive or negative."
    cues: [shocked, stunned, "kya?", achanak, "yakeen nahi hota"]
  - id: sadness
    valence: negative
    description: "Grief, loss or hopelessness."
    cues: [tears, cry, aansu, rona, dukh, akela]
  - id: disgust
    valence: negative
    description: "Revulsion or contempt at a person or act."
    cues: [disgusting, shame, chhi, ghin, nafrat, sharam]
  - id: anger
    valence: negative
    description: "Rage or hostility at an injustice or obstacle."
    cues: [shout, slap, gussa, chillana, thappad, badla]
  - id: anticipation
    valence: neutral
    description: "Expectation of what comes next, eager or anxious."
    cues: [wait, plan, intezaar, kal, soon, "abhi pata chalega"]
arc_shapes:
  - id: rise
    description: "Emotional fortune climbs steadily (rags to riches)."
  - id: fall
    description: "Emotional fortune declines steadily (riches to rags, tragedy)."
  - id: fall_rise
    description: "A fall followed by recovery (man in a hole)."
  - id: rise_fall
    description: "A rise followed by a fall (Icarus)."
  - id: rise_fall_rise
    description: "Rise, fall, then rise again (Cinderella)."
  - id: fall_rise_fall
    description: "Fall, rise, then fall again (Oedipus)."
  - id: flat
    description: "No clear movement in emotional fortune (bundle addition, not one of the six shapes)."
sources:
  - https://doi.org/10.1140/epjds/s13688-016-0093-1
  - https://arxiv.org/abs/1606.07772
---
The eight basic emotions follow Plutchik's wheel of emotions (Plutchik 1980). Valence here is a working default: surprise and anticipation are neutral and take the sign of their context.

Arc shapes follow Reagan, Mitchell, Kiley, Danforth and Dodds (2016), "The emotional arcs of stories are dominated by six basic shapes", EPJ Data Science. Read the arc from the valence and intensity of beats in order. A micro-drama episode often ends mid-fall to set up the cliffhanger.
