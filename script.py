# script.py -- four-call pipeline with word count validation
import anthropic, json, datetime, os, re
from dotenv import load_dotenv
from drive import upload_file, get_or_create_story_folder
from config import TMP, CLAUDE_MODEL, MIN_EXPLAINABILITY_SCORE

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

Each scene must be written as a cinematic still image description --
not a camera direction. Describe what is IN the frame as if briefing
a documentary photographer on exactly what to shoot.
Include: main subject, perspective (close-up/wide/overhead),
lighting quality, and emotional atmosphere.
Every scene should feel like it belongs in the same film.

Good: "Weathered hands of an elderly fisherman holding a torn map,
close-up, harsh side-lighting casting deep shadows, muted blue tones"

Good: "Aerial view looking straight down at a coastline where black rock
meets white ice meets dark ocean, geometric and abstract, cold blue palette"

Bad: "Aerial footage of Greenland" -- too vague, produces illustrations
Bad: "Show the shipping lanes" -- camera direction, not image description
Bad: "Map of the Arctic region" -- produces infographics not photography

No text, signs, logos, or readable labels in any scene.
Scene count = estimated_seconds / 5 (rounded up).

SLUG: Pick 2-3 keywords that uniquely identify this story.
Rules: lowercase, hyphens between words, no dates, no special characters.
Example: "trump-greenland" or "fed-rate-cut" or "ukraine-ceasefire"

Return JSON only, no markdown fences:
{"script": "...", "title": "...", "word_count": N,
 "estimated_seconds": N, "scenes": ["scene 1 desc", ...], "slug": "keyword1-keyword2"}"""


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

Each scene must be written as a cinematic still image description --
not a camera direction. Describe what is IN the frame as if briefing
a documentary photographer on exactly what to shoot.
Include: main subject, perspective (close-up/wide/overhead),
lighting quality, and emotional atmosphere.
Every scene should feel like it belongs in the same film.

Good: "Weathered hands of an elderly fisherman holding a torn map,
close-up, harsh side-lighting casting deep shadows, muted blue tones"

Good: "Aerial view looking straight down at a coastline where black rock
meets white ice meets dark ocean, geometric and abstract, cold blue palette"

Bad: "Aerial footage of Greenland" -- too vague, produces illustrations
Bad: "Show the shipping lanes" -- camera direction, not image description
Bad: "Map of the Arctic region" -- produces infographics not photography

No text, signs, logos, or readable labels in any scene.
Scene count = estimated_seconds / 5 (rounded up).

SLUG: Pick 2-3 keywords that uniquely identify this story.
Rules: lowercase, hyphens between words, no dates, no special characters.
Example: "trump-greenland" or "fed-rate-cut" or "ukraine-ceasefire"

Return JSON only, no markdown fences:
{"script": "...", "title": "...", "word_count": N,
 "estimated_seconds": N, "scenes": ["scene 1 desc", ...], "slug": "keyword1-keyword2"}"""


# ── Bias audit prompt ──────────────────────────────────────────────────────────

BIAS_AUDIT_PROMPT = """You are a non-partisan fact-checker reviewing a news explainer script.

Flag any of the following:
- Emotionally loaded language (words that imply judgment rather than describe facts)
- Missing perspectives (a significant viewpoint that is absent or misrepresented)
- Factual errors or unverifiable claims
- Political framing that favors one side

HARD LENGTH LIMIT: Your revised script must stay within the same word count as
the original, plus or minus 10 words. Do not add explanatory content.
Fix bias by replacing loaded words and reframing sentences -- not by adding new ones.

If the script is clean, say so. If not, provide a revised version that fixes
the issues within the word count constraint.

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

Return JSON only, no markdown fences:
{"pass": true/false, "word_count": N, "completeness_verdict": "...",
 "revised_script": "..."}

Always return revised_script -- trimmed version if over 225 words,
original unchanged if already within limit."""


# ── Utility: strip markdown code fences ───────────────────────────────────────

def strip_fences(text):
    """Remove ```json ... ``` wrappers Claude sometimes adds despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
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

def force_trim(script_data):
    """
    Emergency trim when script exceeds soft cap.
    Called before audit_bias and quality_check to prevent token overflow.
    Preserves hook and kicker. Cuts from middle sections only.
    """
    wc = len(script_data["script"].split())
    print(f"  Force trimming {wc} words to target 200")
    msg = client.messages.create(
        model      = CLAUDE_MODEL,
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

def select_story(candidates):
    msg = client.messages.create(
        model       = CLAUDE_MODEL,
        max_tokens  = 500,
        temperature = 0,   # deterministic -- same input always picks same story
        system      = SELECTOR_PROMPT,
        messages    = [{"role": "user", "content": json.dumps(candidates)}]
    )
    return json.loads(strip_fences(msg.content[0].text))


def write_script(story, account_type="history"):
    prompt = HISTORY_SCRIPT_PROMPT if account_type == "history" else NEWS_SCRIPT_PROMPT
    msg = client.messages.create(
        model      = CLAUDE_MODEL,
        max_tokens = 2000,
        system     = prompt,
        messages   = [{"role": "user", "content": json.dumps(story)}]
    )
    result = json.loads(strip_fences(msg.content[0].text))

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


def audit_bias(script_data, max_retries=2):
    # Pre-trim if over word limit -- prevents auditor receiving bloated script
    if len(script_data["script"].split()) > WORD_SOFT_CAP:
        script_data = force_trim(script_data)

    for i in range(max_retries):
        wc = len(script_data["script"].split())
        msg = client.messages.create(
            model      = CLAUDE_MODEL,
            max_tokens = 5000,
            system     = BIAS_AUDIT_PROMPT,
            messages   = [{"role": "user", "content": script_data["script"]}]
        )

        raw = msg.content[0].text.strip()

        # Handle empty response -- annotate and return rather than crash
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
        except Exception:
            print(f"  Bias audit parse failed -- annotating as unreviewed")
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
        print(f"  Bias audit flagged {len(flags)} issues")

        # Apply revision only if it stays within word limit
        if audit.get("revised_script"):
            new_wc = len(audit["revised_script"].split())
            if new_wc <= wc + 15:
                script_data["script"] = audit["revised_script"]
                print(f"  Revision applied ({new_wc} words)")
            else:
                # Revision inflated the script -- keep original, annotate flags
                print(f"  Revision inflated to {new_wc} words -- keeping original, annotating flags")
                script_data["bias_check"] = {
                    "passed":   False,
                    "flags":    flags,
                    "reviewed": False,
                }
                return script_data

    # Exhausted retries -- store flags for manual review
    script_data["bias_check"] = {
        "passed":   False,
        "flags":    audit.get("flags", ["Unknown bias issues -- manual review required"]),
        "reviewed": False,
    }
    return script_data


def quality_check(script_data, max_retries=2):
    # Pre-trim if over word limit before quality check
    if len(script_data["script"].split()) > WORD_SOFT_CAP:
        script_data = force_trim(script_data)

    for i in range(max_retries):
        msg = client.messages.create(
            model      = CLAUDE_MODEL,
            max_tokens = 4000,
            system     = QUALITY_CHECK_PROMPT,
            messages   = [{"role": "user", "content": script_data["script"]}]
        )

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
        except Exception:
            print(f"  Quality check parse failed -- annotating as unreviewed")
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

        # Always apply revised_script -- catches length trimming
        if result.get("revised_script"):
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


def check_for_breaking(story, account_type="news"):
    """Check if a story qualifies as breaking news (called by scanner)."""
    BREAKING_PROMPT = """You are a news editor. Does this story qualify as BREAKING?
Criteria: happened in last 6 hours, genuinely significant, publishing within
12 hours gives a meaningful first-mover advantage, fits our mission of
context plus historical background. Be conservative.
Reserve urgent for genuine inflection points.
Return JSON only, no markdown fences:
{"breaking": true/false, "urgency": 1-10, "reason": "..."}"""
    msg = client.messages.create(
        model      = CLAUDE_MODEL,
        max_tokens = 300,
        system     = BREAKING_PROMPT,
        messages   = [{"role": "user", "content": json.dumps(story)}]
    )
    result = json.loads(strip_fences(msg.content[0].text))
    if result["breaking"] and result["urgency"] >= 7:
        from breaking import handle_breaking
        handle_breaking(story, result["urgency"], account_type)


# ── Main entry point ───────────────────────────────────────────────────────────

def run_scripting(candidates, account_type="history"):
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

    selected    = select_story(qualified)
    story       = qualified[selected["index"]]
    print(f"  Selected: {selected['title']}")

    script_data = write_script(story, account_type)

    if account_type == "news":
        script_data = audit_bias(script_data)

    script_data = quality_check(script_data)

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

    return script_data, fid


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
        script_data, fid = run_scripting(candidates, account_type="news")

        print(f"\n{'─' * 65}")
        print(f"Title:      {script_data['title']}")
        print(f"Word count: {len(script_data['script'].split())}")
        print(f"Scenes:     {len(script_data.get('scenes', []))}")
        print(f"Drive ID:   {fid}")
        print(f"Bias check: {script_data.get('bias_check', {}).get('passed', 'not run')}")
        print(f"Quality:    {script_data.get('quality_check', {}).get('passed', 'not run')}")
        print(f"\n{'─' * 65}\n")
        print(script_data["script"])