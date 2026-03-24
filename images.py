# images.py
import openai, requests, os, datetime
from drive import upload_file
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
    "history_old":    "In the tradition of Rembrandts dramatic chiaroscuro, deep shadow, motivated candlelight, oil on canvas texture, Old Masters palette -- ",
    "history_mid":    "Steel engraving illustration, high contrast linework, period-accurate detail, historical documentary realism -- ",
    "history_photo":  "Period photojournalism, orthochromatic film, high contrast black and white, documentary quality -- ",
    "history_modern": "35mm documentary photography, Kodachrome palette, photojournalism composition -- ",
    "news":           "Clean editorial infographic illustration, flat design, bold geometric shapes, NYT graphics quality -- ",
}

def generate_image(scene_description, style_key, scene_num, today):
    prompt = STYLE_PREFIXES.get(style_key, STYLE_PREFIXES["news"]) + scene_description
    response = client.images.generate(
        model="dall-e-3", prompt=prompt,
        size="1024x1024", quality="standard", n=1
    )
    img_data = requests.get(response.data[0].url).content
    local_path = os.path.join(TMP, f"scene_{today}_{scene_num:02d}.png")
    with open(local_path, "wb") as f:
        f.write(img_data)
    fid = upload_file(local_path, "images")
    return local_path, fid

def run_image_generation(script_data, style_key="history_old"):
    today = datetime.date.today().isoformat()
    scenes = script_data["scenes"]
    image_paths = []
    for i, scene in enumerate(scenes):
        print(f"Image {i+1}/{len(scenes)}: {scene[:50]}...")
        path, fid = generate_image(scene, style_key, i, today)
        image_paths.append({"path": path, "drive_id": fid, "scene": scene})
    print(f"Generated {len(image_paths)} images")
    return image_paths