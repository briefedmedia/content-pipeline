# images.py
import openai, requests, os, datetime
from drive import upload_file, get_or_create_story_folder
from dotenv import load_dotenv
from config import TMP

# Load environment variables from .env (optional)
load_dotenv()

# Use OPENAI_API_KEY from environment
api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY not set. Please set it in your environment or .env file.")

# Initialize OpenAI client with API key
client = openai.OpenAI(api_key=api_key)

# Style prefixes for image generation
STYLE_PREFIXES = {
    'history_old': (
        "Cinematic film still, oil painting aesthetic, dramatic chiaroscuro lighting, "
        "Rembrandt-style shadow and light, rich saturated color, museum quality composition, "
        "no text, no logos, no watermarks — "
    ),
    'history_mid': (
        "Cinematic film still, authentic vintage photograph, Kodachrome color palette, "
        "high contrast, photojournalism, period accurate details, grain texture, "
        "no text, no logos, no watermarks — "
    ),
    'history_modern': (
        "Cinematic film still, documentary photography, natural available light, "
        "high contrast, shallow depth of field, 35mm film look, "
        "no text, no logos, no watermarks — "
    ),
    'news': (
        "Authentic wire service photograph, shot on Canon EOS-1D Mark IV, 24-70mm lens, "
        "ISO 1600, slight motion blur, imperfect framing, journalist in the field, "
        "available light only, no studio lighting, muted desaturated color palette, "
        "slight grain, unposed and unstaged, gritty documentary realism, "
        "looks like it was actually taken, not generated, "
        "no text, no logos, no watermarks — "
    ),
}

def generate_image(scene_description, style_key, scene_num, slug, images_folder_id,
                   section="", visual_label=""):
    """Generate one image and upload it into the story's Drive subfolder."""
    base_prompt = STYLE_PREFIXES[style_key] + scene_description

    full_prompt = (
        f"{base_prompt}. "
        "Grainy, imperfect, authentic. Not a render, not staged, not polished. "
        "No text of any kind on any surface — no passport text, no ship names, "
        "no map labels, no signage, no readable writing anywhere in the frame."
    )

    response = client.images.generate(
        model   = "dall-e-3",
        prompt  = full_prompt,
        size    = "1024x1792",   # 9:16 vertical -- matches TikTok/Reels format
        quality = "hd",
        n       = 1
    )
    img_data = requests.get(response.data[0].url).content

    # Semantic filename if section + visual_label available, else fallback
    if section and visual_label:
        filename = f"{scene_num+1:02d}_{section}_{visual_label}.png"
    else:
        filename = f"scene_{scene_num:02d}.png"

    local_path = os.path.join(TMP, slug, filename)
    with open(local_path, "wb") as f:
        f.write(img_data)
    fid = upload_file(local_path, "images", folder_id=images_folder_id)
    return local_path, fid

def run_image_generation(script_data, style_key="history_old", tracker=None):
    # Slug flows from script_data -- single source of truth
    slug = script_data.get("slug")
    if not slug:
        slug = datetime.date.today().isoformat() + "_story"
        print(f"  WARNING: no slug in script_data, using fallback: {slug}")
    scenes = script_data["scenes"]

    # Ensure local slug subfolder exists
    slug_dir = os.path.join(TMP, slug)
    os.makedirs(slug_dir, exist_ok=True)

    # Find or create the story subfolder in Drive/images/
    images_folder_id = get_or_create_story_folder(slug, "images")

    image_paths = []
    for i, scene in enumerate(scenes):
        # Handle both new object format and old flat-string format
        if isinstance(scene, dict):
            scene_image   = scene.get("image", "")
            scene_motion  = scene.get("motion", "")
            scene_section = scene.get("section", "")
            visual_label  = scene.get("visual_label", "")
        else:
            scene_image   = scene
            scene_motion  = ""
            scene_section = ""
            visual_label  = ""

        print(f"Image {i+1}/{len(scenes)}: {scene_image[:50]}...")
        path, fid = generate_image(scene_image, style_key, i, slug, images_folder_id,
                                   section=scene_section, visual_label=visual_label)
        image_paths.append({
            "path":         path,
            "drive_id":     fid,
            "scene":        scene_image,
            "motion":       scene_motion,
            "section":      scene_section,
            "visual_label": visual_label,
            "slug":         slug,
        })
        if tracker:
            tracker.add_dalle(1, "hd")
    print(f"Generated {len(image_paths)} images → Drive/images/{slug}/")
    return image_paths

if __name__ == "__main__":
    import json, glob
    from config import TMP
    today   = datetime.date.today().isoformat()
    pattern = os.path.join(TMP, f"{today}_*", f"script_{today}_*.json")
    matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not matches:
        print(f"No script file found matching {pattern}")
        print("Run script.py first to generate today's script")
    else:
        script_path = matches[0]
        with open(script_path, encoding="utf-8") as f:
            script_data = json.load(f)
        print(f"Loaded script: {script_data['title']}")
        print(f"Scenes to generate: {len(script_data.get('scenes', []))}\n")
        image_paths = run_image_generation(script_data, style_key="news")
        print(f"\nAll done — {len(image_paths)} images generated")
        for i, img in enumerate(image_paths):
            print(f"  Scene {i+1}: {img['drive_id']}")
        print(f"Check Drive/03_images/{script_data['slug']}/ to confirm all appeared")