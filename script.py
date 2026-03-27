# script.py -- four-call pipeline with word count validation
import anthropic, json, datetime, os, re
from dotenv import load_dotenv
from drive import upload_file, get_or_create_story_folder
from config import TMP, CLAUDE_MODEL_FAST, CLAUDE_MODEL_BEST, MIN_EXPLAINABILITY_SCORE

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
WORD_MIN      = 155   # 62 seconds -- hard floor, reject below this
WORD_TARGET   = 188   # 75 seconds -- natural aim
WORD_SOFT_CAP = 225   # 90 seconds -- absolute ceiling enforced by quality checker


# ── Selector prompt ────────────────────────────────────────────────────────────

SELECTOR_PROMPT = """You are a video content producer for Briefed, a nonpartisan
current events channel for young adults.

Given these story candidates, pick the SINGLE most compelling one for a
60-90 second explainer video.

Rules:
- NEVER select a story with explainability_score below {min_score}
- Prefer stories with scores of 8 or higher
- A story without rich historical context cannot educate our audience
- If multiple stories score equally, prefer the one most relevant to US audiences

Tiebreaker priority when scores are equal:
1. Story with the most surprising suggested_hook
2. Story most directly affecting US viewers today
3. Story with the most recent key_event in its timeline

Return JSON only, no markdown fences: {{"index": N, "reason": "...", "title": "..."}}
""".format(min_score=MIN_EXPLAINABILITY_SCORE)


# ── Script writing prompts ─────────────────────────────────────────────────────

HISTORY_SCRIPT_PROMPT = """You are writing narration for a cinematic short-form history video for Briefed.

ABSOLUTE MAXIMUM: 225 words. Non-negotiable. Cut ruthlessly -- every sentence earns its place.
Hard minimum: 155 words. Natural target: 175-200 words.

STRUCTURE (write as continuous narration -- do not label sections):

1. HOOK (1-2 sentences)
   One surprising or counterintuitive historical fact. No context yet.
   Make someone stop scrolling. Start with the most unexpected thing.

2. SETUP (2-3 sentences)
   Who, what, where -- vivid but efficient. Essential context only.

3. THE TURN (3-4 sentences)
   The dramatic conflict or decision point. The moment everything changed.
   Draw from the historical_context provided in the story data.

4. HIDDEN CONTEXT (1-2 sentences)
   One verified fact from the provided historical_context data that mainstream
   coverage consistently omits or underreports.
   Frame as: "What most coverage misses..." or "Here's what the headlines leave out..."
   or "But here is what you probably have not heard..."
   CRITICAL: Must come directly from the research provided. Never invent or fabricate.
   This should reframe everything the viewer just heard.

5. STAKES (1-2 sentences)
   Concrete impact on ordinary lives today. Not abstract geopolitics --
   real impact: prices, jobs, safety, rights.

6. KICKER (1 sentence -- the most important sentence in the script)
   Do NOT use "watch for", "time will tell", "only time will tell", or any
   wire service convention. Those are lazy and forgettable.
   Instead choose ONE of these three approaches:
   - THE REFRAME: One sentence that makes everything mean something different
     than the viewer thought. "X is not about Y. It is about Z."
   - THE UNRESOLVED QUESTION: A question the video raised but cannot answer --
     one with no easy resolution that demands further thought.
   - THE CALLBACK WITH TWIST: Return to the hook but with new meaning now that
     the viewer has the full context.
   Model: NYT Opinion TikTok endings -- curious, slightly unsettling, memorable.
   The viewer should feel something unresolved that makes them want to keep thinking.

PRE-OUTPUT SELF-CHECK:
Before returning, read your script once and confirm:
- No words that imply judgment rather than describe facts
- Every position described includes its strongest justification
- No motive attributed to any person or group -- actions only
- Hook and kicker are both intact and strong
Apply any fixes before returning.

SCENE DIRECTIONS — TWO FIELDS PER SCENE, BOTH REQUIRED:

Each scene is an object with two fields: "image" and "motion".
Write them as separate briefs for two different systems.
Do not repeat yourself between them.

─────────────────────────────────────────────
"image" — PHOTOGRAPHY BRIEF FOR DALL-E
─────────────────────────────────────────────
Write as if briefing a photographer before the shoot. Be exact. Be physical.

Required in every image brief:
1. SHOT DISTANCE: extreme close-up / close-up / medium / medium-wide / wide /
   aerial. Include lens if relevant (85mm portrait, 24mm wide, overhead drone).
2. EXACT SUBJECT: Not "a diplomat" -- "a Pakistani foreign ministry official,
   late 40s, dark charcoal suit, right hand flat on a document". Name what
   is in the frame with physical specificity.
3. FOREGROUND / BACKGROUND: What is sharp, what is soft. What is visible
   behind the subject and how far out of focus.
4. LIGHT SOURCE: Where is it coming from, what angle, what quality.
   "Overhead fluorescent casting hard downward shadows" not "institutional lighting".
   "Late afternoon sun from camera left, golden, raking across surface texture"
   not "warm lighting".
5. ONE STORY-SPECIFIC DETAIL: Something that could only appear in this story.
   A Pakistani flag pin. A spreadsheet with Farsi column headers. A map with
   a specific border circled. If you cannot name one, the scene is too generic.

Never describe mood, atmosphere, or color palette -- those are outputs not inputs.
Describe physical facts only. No text, signs, logos, or readable labels in any scene.

─────────────────────────────────────────────
"image" — AVOID LIST (apply to every scene)
─────────────────────────────────────────────
AVOID as primary subject -- these render badly in video and break credibility:
- Hands, fingers, or fine motor detail as the focal point -- if hand action
  is story-relevant, pull back to at least medium shot so hands are secondary
- Faces in extreme close-up -- medium close-up maximum, never fill-frame face
- Crowds of more than 4-5 people -- individuals distort and merge in video
- Animals as primary subject -- fur and movement degrade badly
- Water in extreme close-up -- use mid-distance or wider
- Text on any surface -- especially avoid scenes where text would be the
  natural focal point (maps, documents, screens, signs)
- Fine mechanical detail -- gears, instruments, circuitry

─────────────────────────────────────────────
"motion" — CINEMATOGRAPHER'S SHOT NOTE FOR PIKA/RUNWAY
─────────────────────────────────────────────
Write as a shot-by-shot sequence of physical events with implied timing.
Be sequential, not impressionistic. The model executes these in order.

Required in every motion brief:
1. CAMERA: Does it move? If yes: direction, speed, distance.
   If no: say "Camera completely static." Never leave this ambiguous.
2. SUBJECT MOTION: What does the person or object do, in sequence.
   Describe full-body or large-object movement only -- not hand or finger
   movement. "He turns slowly toward the window" not "his fingers trace the map".
3. SECONDARY MOTION: What else moves -- wind in fabric, visible breath,
   distant water, smoke at distance, leaves, flag movement.
   At least one secondary motion per scene.
4. TIMING ANCHORS: At least two timing notes per scene.
   "2-second pause before he looks up." "Hold on empty chair for final 3 seconds."
5. WHAT STAYS STILL: Name one thing explicitly that does not move.
   Stillness creates tension.

AVOID in motion brief -- these render badly and break credibility:
- Any hand, finger, or fine motor movement as the directed action
- Lip movement, speech, or facial expression changes
- Eye contact directed at camera or blinking close-up
- Fast movement of any kind -- all motion must be slow and deliberate
- Multiple people moving simultaneously
- Objects appearing or disappearing mid-clip
- Rapid or handheld-style camera movement

SAFE motion elements -- prefer these:
- Slow camera push, pull, or drift
- Wind moving fabric, hair, or foliage
- Distant water movement
- Breath visible in cold air
- Single person shifting weight, turning, or walking from medium distance
- Vehicles or large objects moving slowly
- Atmospheric particles -- dust, smoke at distance, steam rising

No aesthetic labels: no "cinematic", "smooth", "dramatic", "clean".
Describe physical events only.

─────────────────────────────────────────────
GOOD EXAMPLE:
─────────────────────────────────────────────
{
  "image": "Medium close-up, slight low angle across conference table.
  Pakistani foreign ministry official, late 40s, dark charcoal suit,
  right hand flat on single white document centered on table. Left hand
  at table edge. Overhead fluorescent, hard downward shadow under jaw.
  Condensation glass of water 8 inches to his right, untouched. Empty
  chair opposite, top edge only, slightly soft focus. Plain off-white
  wall behind, out of focus. Pakistani flag pin on lapel.",

  "motion": "Camera completely static. After 1 second, official's right
  hand slowly slides document 6 inches forward and lifts away. Eyes
  remain downcast. 2-second pause, nothing moves. Left hand pulls back
  off table into lap. Water glass stays completely still throughout.
  Hold on document and empty chair for final 3 seconds. Only movement
  in final hold: barely perceptible rise and fall of breathing under jacket."
}

─────────────────────────────────────────────
BAD EXAMPLE:
─────────────────────────────────────────────
{
  "image": "Diplomatic meeting room, tense atmosphere, muted tones",
  -- No shot distance. No physical specificity. Describes mood not facts.

  "motion": "Slow cinematic push. Dramatic and considered."
  -- No subject motion. No timing. Aesthetic labels only.
}

Scene count: 8-10 scenes per video. One scene every 8-10 seconds.
Minimum 7, maximum 12.

SCENE METADATA — TWO ADDITIONAL REQUIRED FIELDS PER SCENE:

Each scene object must also include "section" and "visual_label":

"section" — exactly one of: hook, setup, turn, context, stakes, kicker
  hook    = opening scene that grabs attention
  setup   = establishes the situation or characters
  turn    = the pivot or complication
  context = historical or background framing
  stakes  = what is at risk or what this means
  kicker  = closing scene, the resonant final image

"visual_label" — 2-3 lowercase hyphenated words describing what is visually
  in the scene. Used as the image and clip filename.
  Examples: "strait-aerial", "tanker-patrol", "1973-oilcrisis", "official-signing"
  Rules: lowercase only, hyphens between words, no special characters, no dates.

SLUG: Pick 2-3 keywords that uniquely identify this story.
Rules: lowercase, hyphens between words, no dates, no special characters.
Example: "trump-greenland" or "fed-rate-cut" or "ukraine-ceasefire"

CRITICAL JSON RULES — follow these exactly or the response cannot be parsed:
* Use only straight double quotes inside JSON strings, never curly/smart quotes
* No literal newlines inside string values -- use a single space instead of line breaks
* No em-dashes (—) inside JSON strings -- use a regular hyphen (-) instead
* Every string value must open and close on the same logical line

Return JSON only, no markdown fences:
{"script": "...", "title": "...", "word_count": N,
 "estimated_seconds": N,
 "scenes": [{"image": "...", "motion": "...", "section": "hook", "visual_label": "strait-aerial"}, ...],
 "slug": "keyword1-keyword2"}"""


NEWS_SCRIPT_PROMPT = """You are writing narration for a non-partisan news explainer for Briefed.

ABSOLUTE MAXIMUM: 225 words. Non-negotiable. Cut ruthlessly -- every sentence earns its place.
Hard minimum: 155 words. Natural target: 175-200 words.

LANGUAGE RULES:
- No emotionally loaded language (radical, extreme, shameful, crisis, alarming, etc.)
- Steelman all positions -- present the strongest version of each argument
- Translate all jargon on first use
- Never attribute motive -- describe actions, not intent
- No conclusions -- present facts and let the viewer decide

STRUCTURE (write as continuous narration -- do not label sections):

1. HOOK (1-2 sentences)
   One surprising or counterintuitive fact about this story.
   Not the obvious angle -- the thing that reframes the whole situation.
   Make someone stop scrolling.

2. CURRENT FACTS (2-3 sentences)
   What happened today, stated plainly. No opinion, no framing.

3. HISTORICAL BACKGROUND (3-4 sentences)
   The context that makes today's event make sense.
   Draw from the historical_context provided in the story data.
   If this story requires 4-5 sentences of background to be explained
   honestly, use them -- background has more flexibility than other sections.

4. HIDDEN CONTEXT (1-2 sentences)
   One verified fact from the provided historical_context data that mainstream
   coverage consistently omits or underreports.
   Frame as: "What most coverage misses..." or "Here is what the headlines leave out..."
   or "But here is what you probably have not heard..."
   CRITICAL: Must come directly from the research provided. Never invent or fabricate.
   This is the most important element of the script -- the inside scoop.
   It should reframe everything the viewer just heard.

5. STAKES (1-2 sentences)
   Concrete impact on ordinary lives. Not abstract policy --
   real impact: prices, jobs, safety, rights, daily life.

6. KICKER (1 sentence -- the most important sentence in the script)
   Do NOT use "watch for", "time will tell", or any wire service convention.
   Those are lazy and signal AI-generated slop. Avoid them completely.
   Instead choose ONE of these three approaches:
   - THE REFRAME: One sentence that makes everything mean something different.
     "X is not about Y. It is about Z."
   - THE UNRESOLVED QUESTION: A question raised but not answered -- one with
     no easy resolution that leaves the viewer sitting with something.
   - THE CALLBACK WITH TWIST: Return to the hook with new meaning now that
     the viewer has the full context.
   Model: NYT Opinion TikTok endings. Curious, slightly unsettling, memorable.
   The viewer should feel something unresolved that makes them want to keep thinking.

PRE-OUTPUT SELF-CHECK (apply before returning):
Before returning, read your script once and ask:
- Did I use any of these words: radical, extreme, crisis, shameful, alarming,
  dangerous, controversial, slammed, blasted, defended, attacked, vowed?
  If yes, replace with neutral descriptive language.
- Did I describe any political action without explaining the reasoning
  behind it from that side's perspective?
  If yes, add one clause steelmanning that position.
- Did I attribute intent or motive to any person or group?
  If yes, replace with a description of the action only.
Apply these fixes before returning. A clean first draft needs no auditor.

SCENE DIRECTIONS — TWO FIELDS PER SCENE, BOTH REQUIRED:

Each scene is an object with two fields: "image" and "motion".
Write them as separate briefs for two different systems.
Do not repeat yourself between them.

─────────────────────────────────────────────
"image" — PHOTOGRAPHY BRIEF FOR DALL-E
─────────────────────────────────────────────
Write as if briefing a photographer before the shoot. Be exact. Be physical.

Required in every image brief:
1. SHOT DISTANCE: extreme close-up / close-up / medium / medium-wide / wide /
   aerial. Include lens if relevant (85mm portrait, 24mm wide, overhead drone).
2. EXACT SUBJECT: Not "a diplomat" -- "a Pakistani foreign ministry official,
   late 40s, dark charcoal suit, right hand flat on a document". Name what
   is in the frame with physical specificity.
3. FOREGROUND / BACKGROUND: What is sharp, what is soft. What is visible
   behind the subject and how far out of focus.
4. LIGHT SOURCE: Where is it coming from, what angle, what quality.
   "Overhead fluorescent casting hard downward shadows" not "institutional lighting".
   "Late afternoon sun from camera left, golden, raking across surface texture"
   not "warm lighting".
5. ONE STORY-SPECIFIC DETAIL: Something that could only appear in this story.
   A Pakistani flag pin. A spreadsheet with Farsi column headers. A map with
   a specific border circled. If you cannot name one, the scene is too generic.

Never describe mood, atmosphere, or color palette -- those are outputs not inputs.
Describe physical facts only. No text, signs, logos, or readable labels in any scene.

Never specify a world map or regional map as a scene unless you specify that there is to be no text, only verified historically accurate geographic shapes — DALL-E renders readable text on maps which violates the no-text rule. Use a physical corkboard map with no country outlines, or replace with a different scene entirely.

─────────────────────────────────────────────
"image" — AVOID LIST (apply to every scene)
─────────────────────────────────────────────
AVOID as primary subject -- these render badly in video and break credibility:
- Hands, fingers, or fine motor detail as the focal point -- if hand action
  is story-relevant, pull back to at least medium shot so hands are secondary
- Faces in extreme close-up -- medium close-up maximum, never fill-frame face
- Crowds of more than 4-5 people -- individuals distort and merge in video
- Animals as primary subject -- fur and movement degrade badly
- Water in extreme close-up -- use mid-distance or wider
- Text on any surface -- especially avoid scenes where text would be the
  natural focal point (maps, documents, screens, signs)
- Fine mechanical detail -- gears, instruments, circuitry

─────────────────────────────────────────────
"motion" — CINEMATOGRAPHER'S SHOT NOTE FOR PIKA/RUNWAY
─────────────────────────────────────────────
Write as a shot-by-shot sequence of physical events with implied timing.
Be sequential, not impressionistic. The model executes these in order.

Required in every motion brief:
1. CAMERA: Does it move? If yes: direction, speed, distance.
   If no: say "Camera completely static." Never leave this ambiguous.
2. SUBJECT MOTION: What does the person or object do, in sequence.
   Describe full-body or large-object movement only -- not hand or finger
   movement. "He turns slowly toward the window" not "his fingers trace the map".
3. SECONDARY MOTION: What else moves -- wind in fabric, visible breath,
   distant water, smoke at distance, leaves, flag movement.
   At least one secondary motion per scene.
4. TIMING ANCHORS: At least two timing notes per scene.
   "2-second pause before he looks up." "Hold on empty chair for final 3 seconds."
5. WHAT STAYS STILL: Name one thing explicitly that does not move.
   Stillness creates tension.

AVOID in motion brief -- these render badly and break credibility:
- Any hand, finger, or fine motor movement as the directed action
- Lip movement, speech, or facial expression changes
- Eye contact directed at camera or blinking close-up
- Fast movement of any kind -- all motion must be slow and deliberate
- Multiple people moving simultaneously
- Objects appearing or disappearing mid-clip
- Rapid or handheld-style camera movement

SAFE motion elements -- prefer these:
- Slow camera push, pull, or drift
- Wind moving fabric, hair, or foliage
- Distant water movement
- Breath visible in cold air
- Single person shifting weight, turning, or walking from medium distance
- Vehicles or large objects moving slowly
- Atmospheric particles -- dust, smoke at distance, steam rising

No aesthetic labels: no "cinematic", "smooth", "dramatic", "clean".
Describe physical events only.

─────────────────────────────────────────────
GOOD EXAMPLE:
─────────────────────────────────────────────
{
  "image": "Medium close-up, slight low angle across conference table.
  Pakistani foreign ministry official, late 40s, dark charcoal suit,
  right hand flat on single white document centered on table. Left hand
  at table edge. Overhead fluorescent, hard downward shadow under jaw.
  Condensation glass of water 8 inches to his right, untouched. Empty
  chair opposite, top edge only, slightly soft focus. Plain off-white
  wall behind, out of focus. Pakistani flag pin on lapel.",

  "motion": "Camera completely static. After 1 second, official's right
  hand slowly slides document 6 inches forward and lifts away. Eyes
  remain downcast. 2-second pause, nothing moves. Left hand pulls back
  off table into lap. Water glass stays completely still throughout.
  Hold on document and empty chair for final 3 seconds. Only movement
  in final hold: barely perceptible rise and fall of breathing under jacket."
}

─────────────────────────────────────────────
BAD EXAMPLE:
─────────────────────────────────────────────
{
  "image": "Diplomatic meeting room, tense atmosphere, muted tones",
  -- No shot distance. No physical specificity. Describes mood not facts.

  "motion": "Slow cinematic push. Dramatic and considered."
  -- No subject motion. No timing. Aesthetic labels only.
}

Scene count: 8-10 scenes per video. One scene every 8-10 seconds.
Minimum 7, maximum 12.

SCENE METADATA — TWO ADDITIONAL REQUIRED FIELDS PER SCENE:

Each scene object must also include "section" and "visual_label":

"section" — exactly one of: hook, setup, turn, context, stakes, kicker
  hook    = opening scene that grabs attention
  setup   = establishes the situation or characters
  turn    = the pivot or complication
  context = historical or background framing
  stakes  = what is at risk or what this means
  kicker  = closing scene, the resonant final image

"visual_label" — 2-3 lowercase hyphenated words describing what is visually
  in the scene. Used as the image and clip filename.
  Examples: "strait-aerial", "tanker-patrol", "1973-oilcrisis", "official-signing"
  Rules: lowercase only, hyphens between words, no special characters, no dates.

SLUG: Pick 2-3 keywords that uniquely identify this story.
Rules: lowercase, hyphens between words, no dates, no special characters.
Example: "trump-greenland" or "fed-rate-cut" or "ukraine-ceasefire"

CRITICAL JSON RULES — follow these exactly or the response cannot be parsed:
* Use only straight double quotes inside JSON strings, never curly/smart quotes
* No literal newlines inside string values -- use a single space instead of line breaks
* No em-dashes (—) inside JSON strings -- use a regular hyphen (-) instead
* Every string value must open and close on the same logical line

Return JSON only, no markdown fences:
{"script": "...", "title": "...", "word_count": N,
 "estimated_seconds": N,
 "scenes": [{"image": "...", "motion": "...", "section": "hook", "visual_label": "strait-aerial"}, ...],
 "slug": "keyword1-keyword2"}"""


# ── Bias audit prompt ──────────────────────────────────────────────────────────

BIAS_AUDIT_PROMPT = """You are a non-partisan fact-checker reviewing a news explainer script.

Flag any of the following:
- Emotionally loaded language (words that imply judgment rather than describe facts)
- Missing perspectives (a significant viewpoint that is absent or misrepresented)
- Factual errors or unverifiable claims
- Political framing that favors one side

IMPORTANT: The hook (first 1-2 sentences) is protected. Do not flag or
revise the hook unless it contains a factual error. A surprising or
uncomfortable fact used as a hook is not bias -- it is journalism.
Reframing the lead as wire-service neutral is not an improvement, it is
a regression. Leave the hook alone.

HARD LENGTH LIMIT: Your revised script must stay within the same word count as
the original, plus or minus 10 words. Do not add explanatory content.
Fix bias by replacing loaded words and reframing sentences -- not by adding new ones.

If the script is clean, say so. If not, provide a revised version that fixes
the issues within the word count constraint.

Do not write any analysis, explanation, or prose. Start your response with { and end with }.\n

Return JSON only, no markdown fences:
{"clean": true/false, "flags": ["issue 1", "issue 2"], "revised_script": "..."}

Always include revised_script -- either the original if clean, or corrected version."""


# ── Quality check prompt ───────────────────────────────────────────────────────

QUALITY_CHECK_PROMPT = """You are a quality reviewer for short-form video scripts.

HARD LENGTH LIMIT: 225 words maximum. This is non-negotiable.
If the script exceeds 225 words, you MUST trim it. No exceptions.

When trimming, follow this priority order:
1. Cut adjectives and qualifiers first (they add words, not information)
2. Cut redundant explanations (if a fact is clear, do not restate it)
3. Cut background detail before cutting stakes or hook
4. NEVER cut the hook (first 1-2 sentences)
5. NEVER cut the kicker (last sentence)
6. NEVER cut a fact that changes the meaning of the story

Also evaluate COMPLETENESS: could someone who knew nothing about this topic
explain the full story after watching once? If not, note what is missing --
but do not add words that push over 225. Flag it instead.

Do not write any analysis, explanation, or prose. Start your response with { and end with }.\n

Return JSON only, no markdown fences:
{"pass": true/false, "word_count": N, "completeness_verdict": "...",
 "revised_script": "..."}

Always return revised_script -- trimmed version if over 225 words,
original unchanged if already within limit."""


# ── Utility: strip markdown code fences ───────────────────────────────────────

def strip_fences(text):
    """Remove ```json ... ``` wrappers and any prose before the first { or [."""
    text = text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    # If Claude added prose before the JSON, find the first { or [
    first_brace = min(
        (text.find("{") if text.find("{") != -1 else len(text)),
        (text.find("[") if text.find("[") != -1 else len(text))
    )
    if first_brace > 0:
        text = text[first_brace:]
    # Find the last } or ] and truncate anything after it
    last_brace = max(text.rfind("}"), text.rfind("]"))
    if last_brace != -1:
        text = text[:last_brace + 1]
    return text.strip()


# ── Word count validation ──────────────────────────────────────────────────────

def validate_word_count(script_text):
    count = len(script_text.split())
    if count < WORD_MIN:
        raise ValueError(f"Script too short: {count} words (min {WORD_MIN})")
    if count > WORD_SOFT_CAP:
        print(f"  Note: {count} words -- above soft cap, quality checker will trim")
    return count


# ── Force trim -- must be defined before audit_bias and quality_check ──────────

def force_trim(script_data, tracker=None):
    """
    Emergency trim when script exceeds soft cap.
    Called before audit_bias and quality_check to prevent token overflow.
    Preserves hook and kicker. Cuts from middle sections only.
    """
    wc = len(script_data["script"].split())
    print(f"  Force trimming {wc} words to target 200")
    msg = client.messages.create(
        model      = CLAUDE_MODEL_FAST,
        max_tokens = 4000,
        system     = (
            "You are an editor. Trim the following script to exactly 200 words. "
            "Keep the first 1-2 sentences (hook) and last sentence (kicker) intact. "
            "Cut from the middle -- remove qualifiers, redundant phrases, and "
            "background detail before cutting facts. "
            "Return JSON only, no markdown fences: {\"script\": \"...\"}"
        ),
        messages   = [{"role": "user", "content": script_data["script"]}]
    )
    if tracker:
        tracker.add_claude("force_trim", CLAUDE_MODEL_FAST,
                           msg.usage.input_tokens, msg.usage.output_tokens)
    raw = msg.content[0].text.strip()
    if not raw:
        print(f"  Force trim returned empty -- keeping original")
        return script_data
    try:
        result = json.loads(strip_fences(raw))
        if "script" in result:
            script_data["script"] = result["script"]
            print(f"  Force trimmed to {len(result['script'].split())} words")
    except Exception:
        print(f"  Force trim parse failed -- keeping original")
    return script_data


# ── Four Claude calls ──────────────────────────────────────────────────────────

def select_story(candidates, tracker=None):
    msg = client.messages.create(
        model       = CLAUDE_MODEL_FAST,
        max_tokens  = 500,
        system      = SELECTOR_PROMPT,
        messages    = [{"role": "user", "content": json.dumps(candidates)}]
    )
    if tracker:
        tracker.add_claude("select_story", CLAUDE_MODEL_FAST,
                           msg.usage.input_tokens, msg.usage.output_tokens)
    raw = msg.content[0].text
    try:
        return json.loads(strip_fences(raw))
    except Exception as e:
        print(f"  Selector parse failed: {e}")
        return None


def _repair_script_json(cleaned, raw, story):
    """
    Emergency JSON repair for write_script() responses.

    Strategy 1: clean known bad characters (smart quotes, em-dashes) and re-parse.
    Strategy 2: extract scalar fields via targeted regex; reconstruct a valid dict.
    On total failure: dump raw to TMP/script_parse_error.txt and re-raise.
    """
    # Strategy 1 -- clean known bad Unicode and retry
    s1 = cleaned
    for bad, good in [('\u201c', '"'), ('\u201d', '"'),   # curly double quotes
                      ('\u2018', "'"), ('\u2019', "'"),   # curly single quotes
                      ('\u2014', '-'), ('\u2013', '-')]:  # em/en dashes
        s1 = s1.replace(bad, good)
    try:
        result = json.loads(s1)
        print("  JSON repaired via character cleaning")
        return result
    except json.JSONDecodeError:
        pass

    # Strategy 2 -- field-by-field regex extraction
    result = {}

    m = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', s1)
    result["title"] = m.group(1) if m else story.get("title", "Untitled")

    m = re.search(r'"script"\s*:\s*"((?:[^"\\]|\\.)*)"', s1, re.DOTALL)
    if m:
        result["script"] = m.group(1).replace("\\n", " ").replace("\\t", " ")

    for key in ("word_count", "estimated_seconds"):
        m = re.search(rf'"{key}"\s*:\s*(\d+)', s1)
        if m:
            result[key] = int(m.group(1))

    m = re.search(r'"slug"\s*:\s*"((?:[^"\\]|\\.)*)"', s1)
    result["slug"] = m.group(1) if m else ""

    # Try to parse scenes array by finding matching brackets
    result["scenes"] = []
    m = re.search(r'"scenes"\s*:\s*(\[)', s1)
    if m:
        bstart = m.start(1)
        depth, in_str, esc = 0, False, False
        end = bstart
        for idx in range(bstart, len(s1)):
            ch = s1[idx]
            if esc:          esc = False; continue
            if ch == '\\':   esc = True;  continue
            if ch == '"':    in_str = not in_str; continue
            if not in_str:
                if ch == '[':   depth += 1
                elif ch == ']': depth -= 1
                if depth == 0:  end = idx; break
        if depth == 0:
            try:
                result["scenes"] = json.loads(s1[bstart:end + 1])
            except json.JSONDecodeError:
                pass  # leave as empty list

    if "script" not in result or not result["script"]:
        error_path = os.path.join(TMP, "script_parse_error.txt")
        with open(error_path, "w", encoding="utf-8") as fh:
            fh.write(raw)
        print(f"  JSON repair failed -- raw response saved to {error_path}")
        raise json.JSONDecodeError(
            f"write_script: could not extract 'script' field. See {error_path}",
            cleaned, 0)

    print(f"  JSON repair partial success: {len(result.get('scenes', []))} scenes extracted")
    return result


def write_script(story, account_type="history", tracker=None):
    prompt = HISTORY_SCRIPT_PROMPT if account_type == "history" else NEWS_SCRIPT_PROMPT
    msg = client.messages.create(
        model      = CLAUDE_MODEL_BEST,
        max_tokens = 4000,      # increased from 2000: new scene object format is token-heavy
        system     = prompt,
        messages   = [{"role": "user", "content": json.dumps(story)}]
    )
    if tracker:
        tracker.add_claude("write_script", CLAUDE_MODEL_BEST,
                           msg.usage.input_tokens, msg.usage.output_tokens)
    raw     = msg.content[0].text
    cleaned = strip_fences(raw)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"  write_script JSON parse error: {e}")
        result = _repair_script_json(cleaned, raw, story)

    # Remap alternative key names Claude sometimes uses despite instructions
    if "script" not in result:
        for alt_key in ["narration", "text", "content", "body"]:
            if alt_key in result:
                result["script"] = result.pop(alt_key)
                break
        # If Claude returned sections dict, flatten into one string
        if "script" not in result and "sections" in result:
            parts = []
            for s in result["sections"]:
                if isinstance(s, dict):
                    parts.append(s.get("text", s.get("content", str(s))))
                else:
                    parts.append(str(s))
            result["script"] = " ".join(parts)

    # Ensure all required keys exist with safe defaults
    result.setdefault("title", story.get("title", "Untitled"))
    result.setdefault("scenes", [])
    result.setdefault("word_count", len(result.get("script", "").split()))
    result.setdefault("estimated_seconds", result["word_count"] * 60 // 155)

    # Build full slug: YYYY-MM-DD_keyword1-keyword2
    # Claude returns just the keyword portion; Python prepends today's date.
    today_str = datetime.date.today().isoformat()
    raw_kw    = result.get("slug", "")
    # Strip any date prefix Claude might have added (e.g. "2026-03-24_trump-greenland")
    raw_kw    = re.sub(r"^\d{4}-\d{2}-\d{2}[_-]?", "", raw_kw)
    # Normalise: lowercase, hyphens only, no leading/trailing hyphens
    raw_kw    = re.sub(r"[^a-z0-9]+", "-", raw_kw.lower()).strip("-")
    if not raw_kw:
        # Fallback: derive keywords from the title (skip very short words)
        words  = re.sub(r"[^a-z0-9\s]", "", result["title"].lower()).split()
        raw_kw = "-".join(w for w in words if len(w) > 2)[:40].strip("-") or "story"
    result["slug"] = f"{today_str}_{raw_kw}"

    validate_word_count(result["script"])
    return result

def write_shorts_script(script_data, tracker=None):
    """
    Trim existing script to YouTube Shorts length (50-58 seconds, ~145 words max).
    One Claude call -- no new story research, reuses existing script_data.
    Keeps: hook, hidden context, kicker.
    Cuts: most historical background, reduces stakes to one sentence.
    """
    SHORTS_PROMPT = """You are editing a news explainer script down to a YouTube Shorts version.

HARD LIMIT: 145 words maximum. Target: 130-145 words. This is non-negotiable.
The Shorts version must be 50-58 seconds when read aloud at natural pace.

WHAT TO KEEP (in order of priority):
1. HOOK -- first 1-2 sentences, keep exactly as written
2. HIDDEN CONTEXT -- the "what most coverage misses" section, keep exactly as written
3. KICKER -- last sentence, keep exactly as written
4. ONE sentence of current facts
5. ONE sentence of stakes

WHAT TO CUT:
- Most historical background -- reduce to one bridging sentence maximum
- Redundant context
- Any sentence that restates something already said

Do not rewrite the kept sections -- preserve their exact wording.
Do not add new content.
Do not write any analysis, explanation, or prose. Start your response with { and end with }.

Return JSON only, no markdown fences:
{"shorts_script": "...", "shorts_word_count": N, "shorts_estimated_seconds": N}"""

    msg = client.messages.create(
        model      = CLAUDE_MODEL_FAST,
        max_tokens = 1000,
        system     = SHORTS_PROMPT,
        messages   = [{"role": "user", "content": script_data["script"]}]
    )
    if tracker:
        tracker.add_claude("write_shorts_script", CLAUDE_MODEL_FAST,
                           msg.usage.input_tokens, msg.usage.output_tokens)
    raw = msg.content[0].text.strip()
    try:
        result = json.loads(strip_fences(raw))
        script_data["shorts_script"]            = result["shorts_script"]
        script_data["shorts_word_count"]        = result.get("shorts_word_count", len(result["shorts_script"].split()))
        script_data["shorts_estimated_seconds"] = result.get("shorts_estimated_seconds", 55)
        print(f"  Shorts script: {script_data['shorts_word_count']} words ({script_data['shorts_estimated_seconds']}s)")
    except Exception as e:
        print(f"  Shorts script generation failed: {e} -- skipping Shorts")
        script_data["shorts_script"] = None
    return script_data

def audit_bias(script_data, max_retries=2, tracker=None):
    # Pre-trim if over word limit
    if len(script_data["script"].split()) > WORD_SOFT_CAP:
        script_data = force_trim(script_data, tracker)

    original_hook   = script_data["script"].split(".")[0]
    prev_flag_count = None

    for i in range(max_retries):
        wc = len(script_data["script"].split())
        msg = client.messages.create(
            model      = CLAUDE_MODEL_BEST,
            max_tokens = 5000,
            system     = BIAS_AUDIT_PROMPT,
            messages   = [{"role": "user", "content": script_data["script"]}]
        )
        if tracker:
            tracker.add_claude("audit_bias", CLAUDE_MODEL_BEST,
                               msg.usage.input_tokens, msg.usage.output_tokens)

        raw = msg.content[0].text.strip()

        if not raw:
            print(f"  Bias audit returned empty -- annotating as unreviewed")
            script_data["bias_check"] = {
                "passed":   False,
                "flags":    ["AUDIT FAILED -- empty response from auditor"],
                "reviewed": False,
            }
            return script_data

        try:
            audit = json.loads(strip_fences(raw))
        except Exception as e:
            print(f"  Bias audit parse failed: {e}")
            print(f"  Raw response was: {raw[:500]}")
            script_data["bias_check"] = {
                "passed":   False,
                "flags":    ["AUDIT FAILED -- response could not be parsed"],
                "reviewed": False,
            }
            return script_data

        # Remap alternative key names
        if "revised_script" not in audit and "script" in audit:
            audit["revised_script"] = audit["script"]
        if "clean" not in audit:
            audit["clean"] = not bool(audit.get("flags", []))

        if audit["clean"]:
            print(f"  Bias audit passed (attempt {i+1})")
            script_data["bias_check"] = {"passed": True, "flags": [], "reviewed": True}
            return script_data

        flags = audit.get("flags", [])
        flag_count = len(flags)
        print(f"  Bias audit flagged {flag_count} issues")

        # Diminishing returns -- if flag count didn't improve, stop looping
        if prev_flag_count is not None and flag_count >= prev_flag_count:
            print(f"  Flags not reducing ({prev_flag_count} -> {flag_count}) -- accepting with annotation")
            script_data["bias_check"] = {
                "passed":   False,
                "flags":    flags,
                "reviewed": False,
            }
            return script_data
        prev_flag_count = flag_count

        # Apply revision only if it passes all three guards
        if audit.get("revised_script"):
            new_wc       = len(audit["revised_script"].split())
            revised_hook = audit["revised_script"].split(".")[0]

            # Guard 1 -- word count
            if new_wc > WORD_SOFT_CAP:
                print(f"  Revision inflated to {new_wc} words -- keeping original")
                script_data["bias_check"] = {
                    "passed":   False,
                    "flags":    flags,
                    "reviewed": False,
                }
                return script_data

            # Guard 2 -- hook protection
            if revised_hook.lower() != original_hook.lower():
                print(f"  Auditor changed the hook -- restoring original hook")
                # Keep the body of the revision but restore the original hook
                revised_sentences = audit["revised_script"].split(". ")
                original_sentences = script_data["script"].split(". ")
                revised_sentences[0] = original_sentences[0]
                audit["revised_script"] = ". ".join(revised_sentences)

            script_data["script"] = audit["revised_script"]
            print(f"  Revision applied ({len(audit['revised_script'].split())} words)")

    # Exhausted retries -- store flags for manual review
    script_data["bias_check"] = {
        "passed":   False,
        "flags":    audit.get("flags", ["Unknown bias issues -- manual review required"]),
        "reviewed": False,
    }
    return script_data


def quality_check(script_data, max_retries=2, tracker=None):
    # Pre-trim if over word limit before quality check
    if len(script_data["script"].split()) > WORD_SOFT_CAP:
        script_data = force_trim(script_data, tracker)

    for i in range(max_retries):
        msg = client.messages.create(
            model      = CLAUDE_MODEL_BEST,
            max_tokens = 4000,
            system     = QUALITY_CHECK_PROMPT,
            messages   = [{"role": "user", "content": script_data["script"]}]
        )
        if tracker:
            tracker.add_claude("quality_check", CLAUDE_MODEL_BEST,
                               msg.usage.input_tokens, msg.usage.output_tokens)

        raw = msg.content[0].text.strip()

        # Handle empty response
        if not raw:
            print(f"  Quality check returned empty -- annotating as unreviewed")
            script_data["quality_check"] = {
                "passed":            False,
                "completeness_note": "QUALITY CHECK FAILED -- empty response",
                "reviewed":          False,
            }
            return script_data

        try:
            result = json.loads(strip_fences(raw))
        except Exception as e:
            print(f"  Quality check parse failed: {e}")
            print(f"  Raw response was:\n{raw[:1000]}")
            script_data["quality_check"] = {
                "passed":            False,
                "completeness_note": "QUALITY CHECK FAILED -- parse error",
                "reviewed":          False,
            }
            return script_data

        # Remap alternative key names
        if "pass" not in result:
            for alt_key in ["passed", "approved", "ok"]:
                if alt_key in result:
                    result["pass"] = result[alt_key]
                    break
            result.setdefault("pass", True)
        if "revised_script" not in result and "script" in result:
            result["revised_script"] = result["script"]

        # Apply revised_script only when non-trivially long (guards against empty/stub responses)
        if result.get("revised_script") and len(result["revised_script"].split()) > 50:
            new_wc = len(result["revised_script"].split())
            old_wc = len(script_data["script"].split())
            if new_wc != old_wc:
                print(f"  Quality check trimmed: {old_wc} -> {new_wc} words")
            script_data["script"]     = result["revised_script"]
            script_data["word_count"] = new_wc

        if result["pass"] and len(script_data["script"].split()) <= WORD_SOFT_CAP:
            print(f"  Quality check passed ({len(script_data['script'].split())} words)")
            script_data["quality_check"] = {
                "passed":            True,
                "completeness_note": result.get("completeness_verdict", ""),
                "reviewed":          True,
            }
            return script_data

    # Failed after retries -- annotate for manual review
    script_data["quality_check"] = {
        "passed":            False,
        "completeness_note": result.get("completeness_verdict", "Manual review required"),
        "reviewed":          False,
    }
    return script_data


def check_for_breaking(story, account_type="news", tracker=None):
    """Check if a story qualifies as breaking news (called by scanner)."""
    BREAKING_PROMPT = """You are a news editor. Does this story qualify as BREAKING?
Criteria: happened in last 6 hours, genuinely significant, publishing within
12 hours gives a meaningful first-mover advantage, fits our mission of
context plus historical background. Be conservative.
Reserve urgent for genuine inflection points.
Return JSON only, no markdown fences:
{"breaking": true/false, "urgency": 1-10, "reason": "..."}"""
    msg = client.messages.create(
        model      = CLAUDE_MODEL_FAST,
        max_tokens = 300,
        system     = BREAKING_PROMPT,
        messages   = [{"role": "user", "content": json.dumps(story)}]
    )
    if tracker:
        tracker.add_claude("check_for_breaking", CLAUDE_MODEL_FAST,
                           msg.usage.input_tokens, msg.usage.output_tokens)
    result = json.loads(strip_fences(msg.content[0].text))
    if result["breaking"] and result["urgency"] >= 7:
        from breaking import handle_breaking
        handle_breaking(story, result["urgency"], account_type)


# ── PDF teleprompter ───────────────────────────────────────────────────────────

def generate_script_pdf(script_data, slug_dir, account_type="news"):
    """Generate a formatted teleprompter PDF using reportlab with Courier Prime."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                     HRFlowable, Table, TableStyle)
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Register Courier Prime fonts
    fonts_dir = os.path.join(os.path.dirname(__file__), "fonts")
    try:
        pdfmetrics.registerFont(TTFont("CourierPrime", os.path.join(fonts_dir, "CourierPrime-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("CourierPrime-Bold", os.path.join(fonts_dir, "CourierPrime-Bold.ttf")))
        pdfmetrics.registerFont(TTFont("CourierPrime-Italic", os.path.join(fonts_dir, "CourierPrime-Italic.ttf")))
        FONT      = "CourierPrime"
        FONT_BOLD = "CourierPrime-Bold"
    except Exception:
        FONT      = "Courier"
        FONT_BOLD = "Courier-Bold"

    slug             = script_data["slug"]
    title            = script_data["title"]
    full_script      = script_data["script"]
    word_count       = script_data.get("word_count", len(full_script.split()))
    est_seconds      = script_data.get("estimated_seconds", word_count * 0.4)
    scenes           = script_data.get("scenes", [])
    date             = slug[:10]

    pdf_path = os.path.join(slug_dir, f"script_{slug}_teleprompter.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2.5*cm, bottomMargin=2.5*cm)

    # Styles — Courier Prime throughout
    header_style = ParagraphStyle("header", fontSize=9, textColor=colors.HexColor("#888888"),
                                  fontName=FONT)
    title_style  = ParagraphStyle("title", fontSize=18, fontName=FONT_BOLD,
                                  alignment=TA_CENTER, leading=26, spaceAfter=12)
    scene_hdr    = ParagraphStyle("scene_hdr", fontSize=9, fontName=FONT_BOLD,
                                  textColor=colors.HexColor("#555555"))
    body_style   = ParagraphStyle("body", fontSize=13, fontName=FONT,
                                  leading=22, spaceAfter=8)
    footer_style = ParagraphStyle("footer", fontSize=9, textColor=colors.HexColor("#888888"),
                                  fontName=FONT, alignment=TA_CENTER)

    # Split script into scene chunks proportionally by word count
    words = full_script.split()
    n_scenes = max(len(scenes), 1)
    chunk_size = max(len(words) // n_scenes, 1)
    scene_texts = []
    for i in range(n_scenes):
        start = i * chunk_size
        end   = start + chunk_size if i < n_scenes - 1 else len(words)
        scene_texts.append(" ".join(words[start:end]))

    # Per-scene timestamp offsets
    def fmt_ts(seconds):
        m, s = divmod(int(seconds), 60)
        return f"{m}:{s:02d}"

    secs_per_word = est_seconds / max(len(words), 1)

    story_elements = []

    # Page header (repeated via onFirstPage / onLaterPages via SimpleDocTemplate header)
    hdr_left  = f"BRIEFED  |  {account_type.upper()}"
    hdr_right = f"{date}  |  {word_count} words  |  est. {int(est_seconds)}s"
    story_elements.append(
        Table([[Paragraph(hdr_left, header_style), Paragraph(hdr_right, header_style)]],
              colWidths=["60%", "40%"],
              style=TableStyle([("ALIGN", (1,0), (1,0), "RIGHT"),
                                ("BOTTOMPADDING", (0,0), (-1,-1), 8)]))
    )
    story_elements.append(HRFlowable(width="100%", thickness=0.5,
                                     color=colors.HexColor("#cccccc")))
    story_elements.append(Spacer(1, 0.4*cm))

    # Title
    story_elements.append(Paragraph(title, title_style))
    story_elements.append(Spacer(1, 0.3*cm))

    # Scenes
    elapsed_words = 0
    for i, scene in enumerate(scenes):
        if isinstance(scene, dict):
            section      = scene.get("section", f"scene{i+1}")
            visual_label = scene.get("visual_label", "")
        else:
            section      = f"scene{i+1}"
            visual_label = ""

        ts = fmt_ts(elapsed_words * secs_per_word)
        scene_text = scene_texts[i] if i < len(scene_texts) else ""
        elapsed_words += len(scene_text.split())

        label_left  = f"SCENE {i+1} — {section.upper()}"
        if visual_label:
            label_left += f"   |   {visual_label}"
        label_right = f"[{ts}]"

        story_elements.append(
            Table([[Paragraph(label_left, scene_hdr), Paragraph(label_right, scene_hdr)]],
                  colWidths=["75%", "25%"],
                  style=TableStyle([("ALIGN", (1,0), (1,0), "RIGHT"),
                                    ("BOTTOMPADDING", (0,0), (-1,-1), 2)]))
        )
        story_elements.append(Paragraph(scene_text, body_style))
        story_elements.append(HRFlowable(width="100%", thickness=0.5,
                                         color=colors.HexColor("#dddddd"),
                                         spaceAfter=10))
        story_elements.append(Spacer(1, 0.3*cm))

    # Footer
    story_elements.append(Spacer(1, 0.5*cm))
    story_elements.append(Paragraph(
        f"Record your VO and drop it in Drive/05_audio/pending/{slug}/",
        footer_style))
    story_elements.append(Paragraph(
        f"Name your file: voiceover_{slug}_{account_type}.mp3",
        footer_style))

    doc.build(story_elements)
    print(f"  PDF teleprompter: {os.path.basename(pdf_path)}")
    return pdf_path


# ── Main entry point ───────────────────────────────────────────────────────────

def run_scripting(candidates, account_type="history", tracker=None):
    # Hard filter -- remove stories below minimum explainability threshold
    qualified = [
        c for c in candidates
        if c.get("historical_context") and
        c["historical_context"].get("explainability_score", 0) >= MIN_EXPLAINABILITY_SCORE
    ]

    if not qualified:
        print(f"  WARNING: No candidates met minimum score of {MIN_EXPLAINABILITY_SCORE}. Using all.")
        qualified = candidates
    else:
        print(f"  {len(qualified)}/{len(candidates)} candidates qualify (score >= {MIN_EXPLAINABILITY_SCORE})")

    selected = select_story(qualified, tracker=tracker)
    if selected is None:
        raise ValueError("Story selection failed -- check selector raw response above")
    story       = qualified[selected["index"]]
    print(f"  Selected: {selected['title']}")

    script_data = write_script(story, account_type, tracker=tracker)
    print(f"  Slug: {script_data['slug']}")   # confirm slug matches selected story

    if account_type == "news":
        script_data = audit_bias(script_data, tracker=tracker)

    script_data = quality_check(script_data, tracker=tracker)

    script_data = write_shorts_script(script_data, tracker=tracker)

    # ── Slug-based paths ───────────────────────────────────────────────────────
    slug     = script_data["slug"]           # e.g. "2026-03-24_trump-greenland"
    slug_dir = os.path.join(TMP, slug)
    os.makedirs(slug_dir, exist_ok=True)

    script_folder_id = get_or_create_story_folder(slug, "scripts")

    filename   = f"script_{slug}.json"
    local_json = os.path.join(slug_dir, filename)
    with open(local_json, "w", encoding="utf-8") as f:
        json.dump(script_data, f, indent=2, ensure_ascii=False)
    fid = upload_file(local_json, "scripts", filename, folder_id=script_folder_id)

    # Plain text version for easy phone reading before recording VO
    local_txt = os.path.join(slug_dir, f"script_{slug}.txt")
    with open(local_txt, "w", encoding="utf-8") as f:

        # Write warning banner if any checks failed
        bias_result    = script_data.get("bias_check", {})
        quality_result = script_data.get("quality_check", {})

        if not bias_result.get("passed", True) or not quality_result.get("passed", True):
            f.write("=" * 65 + "\n")
            f.write("WARNING -- THIS SCRIPT DID NOT PASS FULL AUTOMATED REVIEW\n")
            f.write("Review flagged items below before recording voiceover.\n")
            f.write("=" * 65 + "\n\n")

            if not bias_result.get("passed", True):
                f.write("BIAS / ACCURACY FLAGS:\n")
                for flag in bias_result.get("flags", []):
                    f.write(f"  >> {flag}\n")
                f.write("\n")

            if not quality_result.get("passed", True):
                f.write("COMPLETENESS FLAGS:\n")
                f.write(f"  >> {quality_result.get('completeness_note', 'Manual review required')}\n")
                f.write("\n")

            f.write("-" * 65 + "\n\n")

        f.write(f"{script_data['title']}\n\n{script_data['script']}")

    upload_file(local_txt, "scripts", folder_id=script_folder_id)

    # Shorts plain text version
    if script_data.get("shorts_script"):
        local_shorts_txt = os.path.join(slug_dir, f"script_{slug}_shorts.txt")
        with open(local_shorts_txt, "w", encoding="utf-8") as f:
            f.write(f"{script_data['title']} #Shorts\n\n")
            f.write(script_data["shorts_script"])
        upload_file(local_shorts_txt, "scripts", folder_id=script_folder_id)

    # PDF teleprompter
    try:
        pdf_path = generate_script_pdf(script_data, slug_dir, account_type)
        upload_file(pdf_path, "scripts", folder_id=script_folder_id)
    except Exception as e:
        print(f"  PDF generation failed (non-fatal): {e}")

    return script_data, fid, tracker


# ── Test block ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    today           = datetime.date.today().isoformat()
    # discover.py saves into a dated subfolder: TMP/YYYY-MM-DD/candidates_YYYY-MM-DD.json
    candidates_path = os.path.join(TMP, today, f"candidates_{today}.json")

    if not os.path.exists(candidates_path):
        print(f"No candidates file found at {candidates_path}")
        print("Run discover.py first to generate today's candidates")
    else:
        with open(candidates_path, encoding="utf-8") as f:
            data = json.load(f)

        candidates = data["candidates"]
        print(f"Loaded {len(candidates)} candidates from {candidates_path}\n")

        # Change account_type to "history" to test the history branch
        script_data, fid, _ = run_scripting(candidates, account_type="news")

        print(f"\n{'─' * 65}")
        print(f"Title:      {script_data['title']}")
        print(f"Word count: {len(script_data['script'].split())}")
        print(f"Scenes:     {len(script_data.get('scenes', []))}")
        print(f"Drive ID:   {fid}")
        print(f"Bias check: {script_data.get('bias_check', {}).get('passed', 'not run')}")
        print(f"Quality:    {script_data.get('quality_check', {}).get('passed', 'not run')}")
        print(f"\n{'─' * 65}\n")
        print(script_data["script"])