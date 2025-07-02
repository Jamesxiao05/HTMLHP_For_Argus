import os
import random
import time
import logging
from flask import Flask, request, render_template, abort, Response
from supabase import create_client, Client
from user_agents import parse
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# Load environment variables from .env file for local development
load_dotenv()

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CONFIG = {
    "NUM_TEMPLATE_TYPES": 5,    # Corresponds to the number of H1 sections to use
    "TEMPLATES_PER_TYPE": 3,    # Corresponds to the number of H2 sections per H1
    "TOTAL_TEMPLATES": 15,      # Total number of unique combinations
    "CACHE_DURATION_SECONDS": 600
}
BOT_CACHE = {}
app = Flask(__name__)

# --- Supabase Client Initialization ---
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
if not supabase_url or not supabase_key:
    logging.error("Supabase URL and Key must be set.")
    supabase: Client = None
else:
    supabase: Client = create_client(supabase_url, supabase_key)

# --- HTML Parsing and Content Generation Functions ---

def parse_master_html(html_content):
    """
    Parses the master HTML file into a nested dictionary of H1 and H2 sections.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    nested_data = {}

    for h1 in soup.find_all("h1"):
        h1_title = h1.get_text(strip=True)
        h2_sections = {}

        h1_content_soup = BeautifulSoup("", "html.parser")
        for sibling in h1.find_next_siblings():
            if sibling.name == "h1":
                break
            h1_content_soup.append(sibling)

        for h2 in h1_content_soup.find_all("h2"):
            h2_title = h2.get_text(strip=True)
            h2_content_soup = BeautifulSoup("", "html.parser")
            for h2_sibling in h2.find_next_siblings():
                if h2_sibling.name == "h2":
                    break
                h2_content_soup.append(h2_sibling)
            h2_sections[h2_title] = h2_content_soup

        if h2_sections:
            nested_data[h1_title] = h2_sections
        else:
            nested_data[h1_title] = h1_content_soup

    return nested_data

def wrap_soup_in_homepage(soup, title="Home"):
    """Wraps a BeautifulSoup object in a styled HTML page template."""
    html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f8f9fa; margin: 0; padding: 0; }}
        .container {{ max-width: 900px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); padding: 32px 40px; }}
        h1, h2, h3 {{ color: #2c3e50; margin-top: 1.5em; }}
        h1 {{ border-bottom: 2px solid #3498db; padding-bottom: 0.3em; }}
        h2 {{ border-left: 4px solid #3498db; padding-left: 0.5em; margin-top: 1.2em; }}
        p {{ color: #444; line-height: 1.7; }}
        a {{ color: #3498db; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        @media (max-width: 600px) {{ .container {{ padding: 20px 15px; }} }}
    </style>
</head>
<body>
    <div class="container">
        {soup.prettify()}
    </div>
</body>
</html>
"""
    return html_template

def get_content_from_nested_structure(nested_dict, num):
    """
    Selects and correctly reconstructs a specific H1 and H2 section based on the template number.
    This version is robust and will not crash if FakeData.html has fewer sections than configured.
    """
    top_keys = list(nested_dict.keys())
    if not top_keys:
        raise ValueError("Cannot select content: The 'nested_sections' dictionary is empty. Check FakeData.html.")

    # Calculate which H1 section to use.
    # The formula (num - 1) // 3 gives us groups of 3 (0, 1, 2, 3, 4).
    top_index_calc = (num - 1) // CONFIG["TEMPLATES_PER_TYPE"]

    # Use modulo on the *actual number of available H1s* to prevent index errors.
    # If we need the 5th H1 but only 4 exist, this will wrap around to the 1st.
    top_index = top_index_calc % len(top_keys)
    top_key = top_keys[top_index]

    h1_section_content = nested_dict[top_key]
    final_soup = BeautifulSoup(f"<h1>{top_key}</h1>", "html.parser")

    # Check if the h1 section has nested h2 sections
    if isinstance(h1_section_content, dict) and h1_section_content:
        bottom_keys = list(h1_section_content.keys())
        
        # Only proceed if there are actually H2 sections
        if bottom_keys:
            # Calculate which H2 section to use within the H1.
            # The formula (num - 1) % 3 gives us the position within the group (0, 1, 2).
            bottom_index_calc = (num - 1) % CONFIG["TEMPLATES_PER_TYPE"]

            # Use modulo on the *actual number of H2s in this specific section*.
            # If we need the 3rd H2 but only 2 exist, this wraps to the 1st.
            bottom_index = bottom_index_calc % len(bottom_keys)
            bottom_key = bottom_keys[bottom_index]

            final_soup.append(BeautifulSoup(f"<h2>{bottom_key}</h2>", "html.parser"))
            final_soup.append(h1_section_content[bottom_key])
        else:
            # If the dict is empty, treat it as direct content
            logging.warning(f"H1 section '{top_key}' has empty H2 sections. Using fallback content.")
            final_soup.append(BeautifulSoup("<p>Content not available.</p>", "html.parser"))
    else:
        # If no H2s, append the direct content of the H1 section.
        if h1_section_content:
            final_soup.append(h1_section_content)
        else:
            # Fallback if content is completely empty
            logging.warning(f"H1 section '{top_key}' has no content. Using fallback.")
            final_soup.append(BeautifulSoup("<p>Content not available.</p>", "html.parser"))

    return final_soup



"-----"

TOP_LEVEL_COUNT = 5  # Number of top-level sections (e.g., h1 sections)
BOTTOM_LEVEL_COUNT = 3  # Number of bottom-level sections per top-level (e.g., h2 sections)

def split_html_by_tag(html_content, tag_name):
    soup = BeautifulSoup(html_content, "html.parser")
    tags = soup.find_all(tag_name)
    all_elements = list(soup.descendants)
    sections = {}
    for i, tag in enumerate(tags):
        tag_index = all_elements.index(tag)
        if i + 1 < len(tags):
            next_tag = tags[i + 1]
            next_tag_index = all_elements.index(next_tag)
        else:
            next_tag_index = len(all_elements)
        section_html = ''.join(str(elem) for elem in all_elements[tag_index + 1:next_tag_index])
        section_soup = BeautifulSoup(section_html, "html.parser")
        section_name = tag.get_text(strip=True)
        sections[section_name] = section_soup
    return sections

def wrap_soup_in_homepage(soup, title="Home"):
    html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            background: #f8f9fa;
            margin: 0;
            padding: 0;
        }}
        .container {{
            max-width: 900px;
            margin: 40px auto;
            background: #fff;
            border-radius: 12px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.08);
            padding: 32px 40px;
        }}
        h1, h2, h3 {{
            color: #2c3e50;
            margin-top: 1.5em;
        }}
        h1 {{
            border-bottom: 2px solid #3498db;
            padding-bottom: 0.3em;
        }}
        h2 {{
            border-left: 4px solid #3498db;
            padding-left: 0.5em;
            margin-top: 1.2em;
        }}
        p {{
            color: #444;
            line-height: 1.7;
        }}
        ul, ol {{
            margin-left: 2em;
        }}
        a {{
            color: #3498db;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        @media (max-width: 600px) {{
            .container {{
                padding: 16px 8px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        {soup.prettify()}
    </div>
</body>
</html>
"""
    return html_template

def get_template(dic, num):
    """
    Selects and returns a value from the nested dictionary based on num.
    """
    global TOP_LEVEL_COUNT
    global BOTTOM_LEVEL_COUNT

    top_keys = list(dic.keys())
    top_index = num % TOP_LEVEL_COUNT
    top_key = top_keys[top_index]

    bottom_keys = list(dic[top_key].keys())
    bottom_index = num % BOTTOM_LEVEL_COUNT
    bottom_key = bottom_keys[bottom_index]

    return dic[top_key][bottom_key]

def generate_html_from_template_number(n):
    global nested_sections
    return wrap_soup_in_homepage(get_template(nested_sections, n-1), title="Home")

# Example usage:
with open("FakeData.html", "r", encoding="utf-8") as f:
    html = f.read()
# First split by h1
h1_sections = split_html_by_tag(html, "h1")
# Now, for each h1 section, split by h2 and nest
nested_sections = {}
for h1_name, h1_soup in h1_sections.items():
    h2_sections = split_html_by_tag(str(h1_soup), "h2")
    nested_sections[h1_name] = h2_sections if h2_sections else h1_soup

"-----"





def generate_page_for_bot(template_number):
    """The main generator function that takes a number and returns full HTML."""
    global nested_sections
    return generate_html_from_template_number(template_number)
    
    print(f"{len(nested_sections) = }")
    selected_soup = get_content_from_nested_structure(nested_sections, template_number)
    return wrap_soup_in_homepage(selected_soup, title="Bot Information Page")

# --- HTML Parsing at Startup ---
nested_sections = {}
try:
    with open("FakeData.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    nested_sections = parse_master_html(html_content)
    logging.info(f"Successfully parsed FakeData.html into {len(nested_sections)} top-level sections.")
except FileNotFoundError:
    logging.error("CRITICAL: FakeData.html not found. The application cannot serve bot content.")
except Exception as e:
    logging.error(f"CRITICAL: Failed to parse FakeData.html: {e}")


# --- Bot/DB Helper Functions (MODIFIED) ---

def get_bot_name(user_agent_string: str) -> str | None:
    user_agent = parse(user_agent_string)
    if user_agent.is_bot:
        return user_agent.browser.family
    return None

def create_new_bot_entry(bot_name: str) -> int:
    """
    Generates a completely random template ID for a new bot and saves it.
    """
    logging.info(f"'{bot_name}' is a new bot. Assigning a completely random template.")

    # Generate a random template ID from 1 to the total number of templates
    new_template_id = random.randint(1, CONFIG["TOTAL_TEMPLATES"])
    logging.info(f"Randomly assigned template ID {new_template_id} to '{bot_name}'.")

    insert_response = supabase.table('bot_visits').insert({
        'bot_name': bot_name, 
        'template_id': new_template_id
    }).execute()

    if not insert_response.data:
        raise Exception(f"Failed to save new bot '{bot_name}' to Supabase.")
    return new_template_id

def get_or_create_bot_template_id(bot_name: str) -> int:
    """
    Checks cache or DB for a bot's template ID. If not found, creates a new random one.
    """
    print("here 1")
    if bot_name in BOT_CACHE and (time.time() - BOT_CACHE[bot_name]['timestamp']) < CONFIG["CACHE_DURATION_SECONDS"]:
        logging.info(f"'{bot_name}' found in cache. Serving cached template.")
        print("here 2")
        print(f"{bot_name}...")
        print(f"{BOT_CACHE[bot_name]}")
        print(f"{BOT_CACHE[bot_name]['template_id']}")
        return BOT_CACHE[bot_name]['template_id']
    try:
        print("here 3")
        response = supabase.table('bot_visits').select('template_id').eq('bot_name', bot_name).execute()
        if response.data:
            template_id = response.data[0]['template_id']
            logging.info(f"'{bot_name}' is a returning bot. Found template: {template_id} in DB.")
            print("here 4")
        else:
            print("here 5")
            template_id = create_new_bot_entry(bot_name)
        BOT_CACHE[bot_name] = {'template_id': template_id, 'timestamp': time.time()}
        print("here 6")
        return template_id
    except Exception as e:
        print("here 7")
        logging.error(f"Database query/update failed for bot '{bot_name}': {e}")
        raise

# --- Main Application Route (Unchanged) ---

@app.route('/')
def serve_content():
    user_agent_string = request.headers.get('User-Agent', '')
    bot_name = get_bot_name(user_agent_string)

    if bot_name:
        logging.info(f"Bot detected: '{bot_name}'")
        if not nested_sections:
            logging.error(f"Cannot serve '{bot_name}' because FakeData.html was not parsed.")
            abort(500, description="Server content source is not available.")
        try:
            template_id = get_or_create_bot_template_id(bot_name)
            print("here 11")

            print(f"{template_id}")
            html_content = generate_page_for_bot(template_id)
            print("here 12")
            return Response(html_content, mimetype='text/html')

        except Exception as e:
            logging.critical(f"A critical error occurred while processing bot request: {e}")
            abort(500, description="A server error occurred.")
    else:
        logging.info("Human user detected. Serving default page.")
        return render_template('index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081)
