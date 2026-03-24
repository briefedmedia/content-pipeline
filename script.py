# script.py -- four-call pipeline with word count validation
import anthropic, json, datetime, os
from drive import upload_file
from config import TMP

client = anthropic.Anthropic()

WORD_MIN      = 155   # 62 seconds -- hard floor, reject below this
WORD_TARGET   = 188   # 75 seconds -- natural aim
WORD_SOFT_CAP = 225   # 90 seconds -- log note if exceeded, do NOT reject
# No hard ceiling. Completeness comes before length.

SELECTOR_PROMPT = """You are a video content producer.
Given these story candidates, pick the SINGLE most compelling one
for a short-form video aimed at young adults (18-30).
Prioritize stories with strong current angle AND rich historical background.
Return JSON only: {"index": N, "reason": "...", "title": "..."}"""

HISTORY_SCRIPT_PROMPT = """You are writing narration for a cinematic short-form history video.

LENGTH RULES:
- Hard minimum: 155 words (62 seconds). Never go below this.
- Natural target: 175-200 words (70-80 seconds). Aim here for most stories.
- There is NO hard ceiling. If the story genuinely requires more, use them.
- Every word above 200 must carry information the viewer needs.
- Never pad. Never repeat. When cutting, remove style before substance.
- Historical background section has no ceiling -- never trimmed first.

STRUCTURE (continuous narration, do not label sections):
- Hook (8-10s): One surprising fact. No context yet.
- Setup (18-22s): Who, what, where -- vivid but efficient.
- The Turn (28-35s): The dramatic conflict or decision point.
- Resolution (12-15s): What happened and why it still matters.
- Kicker (6-8s): One line that reframes the whole story.

Return JSON only:
{"script": "...", "title": "...", "word_count": N,
 "estimated_seconds": N, "scenes": ["scene 1 desc", ...]}
Scene count = estimated_seconds / 5 (rounded up)."""

NEWS_SCRIPT_PROMPT = """You are writing narration for a non-partisan news explainer.

LENGTH RULES: Same as above. Historical background section has no ceiling.
If a story like foreign conflict or economic policy needs 50+ seconds of
background to be explained honestly, give it that time.

LANGUAGE RULES:
- No emotionally loaded language (radical, extreme, shameful, etc.)
- Steelman all positions -- strongest version of each argument
- Translate all jargon on first use
- Never attribute motive -- describe actions, not intent
- No conclusions -- present facts, let viewer decide

STRUCTURE: Hook --> Current facts --> Historical background --> Stakes --> What to watch

Return same JSON format as history prompt."""

BIAS_AUDIT_PROMPT = """You are a non-partisan fact-checker.
Flag: loaded language, missing perspectives, factual errors, political framing.
If you revise, maintain or expand word count as needed for accuracy.
Return JSON: {"clean": true/false, "flags": ["..."], "revised_script": "..."}"""

QUALITY_CHECK_PROMPT = """Quality reviewer for short-form video.
Evaluate TWO things:
1. COMPLETENESS: Could someone who knew nothing explain the full story after watching once?
2. LENGTH JUSTIFICATION (if over 200 words): Is every extra word carrying information?

Return JSON:
{"pass": true/false, "completeness_verdict": "...",
 "length_justified": true/false/"na",
 "passages_to_trim": ["..."],
 "revised_script": "..."}

Never trim content that is informationally necessary, even if script is long."""

def validate_word_count(script_text):
    count = len(script_text.split())
    if count < WORD_MIN:
        raise ValueError(f"Script too short: {count} words (min {WORD_MIN})")
    if count > WORD_SOFT_CAP:
        print(f"Note: {count} words -- above soft cap, quality checker will verify")
    return count

def select_story(candidates):
    msg = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=500,
        system=SELECTOR_PROMPT,
        messages=[{"role":"user","content":json.dumps(candidates)}])
    return json.loads(msg.content[0].text)

def write_script(story, account_type="history"):
    prompt = HISTORY_SCRIPT_PROMPT if account_type == "history" else NEWS_SCRIPT_PROMPT
    msg = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1500,
        system=prompt,
        messages=[{"role":"user","content":json.dumps(story)}])
    result = json.loads(msg.content[0].text)
    validate_word_count(result["script"])
    return result

def audit_bias(script_data, max_retries=3):
    for i in range(max_retries):
        msg = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1500,
            system=BIAS_AUDIT_PROMPT,
            messages=[{"role":"user","content":script_data["script"]}])
        audit = json.loads(msg.content[0].text)
        if audit["clean"]: return script_data
        script_data["script"] = audit["revised_script"]
        validate_word_count(script_data["script"])
    return script_data

def quality_check(script_data, max_retries=2):
    for i in range(max_retries):
        msg = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1500,
            system=QUALITY_CHECK_PROMPT,
            messages=[{"role":"user","content":script_data["script"]}])
        result = json.loads(msg.content[0].text)
        wc = len(script_data["script"].split())
        if not result["pass"]:
            script_data["script"] = result["revised_script"]
            validate_word_count(script_data["script"])
            continue
        if result.get("passages_to_trim") and result.get("revised_script"):
            script_data["script"] = result["revised_script"]
            continue
        print(f"Quality check passed ({wc} words)")
        return script_data
    return script_data

def check_for_breaking(story, account_type="news"):
    """Check if a story qualifies as breaking news (called by scanner)."""
    BREAKING_PROMPT = """You are a news editor. Does this story qualify as BREAKING?
    Criteria: happened in last 6 hours, genuinely significant, publishing in 12hrs gives
    first-mover advantage, fits our mission of context + historical background.
    Be conservative. Reserve urgent for genuine inflection points.
    Return JSON: {"breaking": true/false, "urgency": 1-10, "reason": "..."}"""
    msg = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=300,
        system=BREAKING_PROMPT,
        messages=[{"role":"user","content":json.dumps(story)}])
    result = json.loads(msg.content[0].text)
    if result["breaking"] and result["urgency"] >= 7:
        from breaking import handle_breaking
        handle_breaking(story, result["urgency"], account_type)

def run_scripting(candidates, account_type="history"):
    selected = select_story(candidates)
    story = candidates[selected["index"]]
    print(f"Selected: {selected['title']}")
    script_data = write_script(story, account_type)
    if account_type == "news":
        script_data = audit_bias(script_data)
    script_data = quality_check(script_data)
    today = datetime.date.today().isoformat()
    filename = f"script_{today}_{account_type}.json"
    with open(os.path.join(TMP, filename), "w") as f:
        json.dump(script_data, f, indent=2)
    fid = upload_file(os.path.join(TMP, filename), "scripts", filename)
    # Also save plain text for easy phone reading
    txt = os.path.join(TMP, f"script_{today}_{account_type}.txt")
    with open(txt, "w") as f:
        f.write(f"{script_data['title']}\n\n{script_data['script']}")
    upload_file(txt, "scripts")
    return script_data, fid

