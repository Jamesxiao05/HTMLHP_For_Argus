"""
A Flask application that serves dynamic HTML content based on templates and generates fake data for bots.
It uses Supabase for storing bot visits and user agents to detect bots.
The application reads a master HTML file, parses it into a nested structure, and generates HTML content
based on user requests.
"""


# --- Imports ---
import os
import random
import time
import logging
import re
import traceback
from flask import Flask, request, render_template, abort, Response
from supabase import create_client
from user_agents import parse
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from faker import Faker

# --- Load environment variables ---
""" The dotenv file should contain:
SUPABASE_URL=<your_supabase_url>
SUPABASE_KEY=<your_supabase_key>
IPINFO_TOKEN=<your_ipinfo_token>
"""
load_dotenv()

# --- Configuration ---
""" Configure logging to output to console with timestamps and log level """
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Global Variables ---
""" Configuration for the number of templates and cache duration.
This configuration is used to determine how many template types, templates per type,
and the total number of templates are available.
Also includes a cache duration for bot data to reduce database queries."""
CONFIG = {
    "NUM_TEMPLATE_TYPES": 5,  # Corresponds to the number of H1 sections to use
    "TEMPLATES_PER_TYPE": 3,  # Corresponds to the number of H2 sections per H1
    "TOTAL_TEMPLATES": 15,  # Total number of unique combinations
    "CACHE_DURATION_SECONDS": 600,
    "FAKE_DATA_VAR_COUNT": 12,  # Number of fake data variables per type
}

""" Cache for bot data to avoid frequent database queries.
This cache stores the template ID and seed for each bot, along with a timestamp
to determine if the cache is still valid based on CACHE_DURATION_SECONDS."""
BOT_CACHE = {}

""" A list of tuples defining the structure of fake data types.
Each tuple contains a type name and a list of fields that can be generated."""
FAKE_DATA_TYPES = (
    (
        "Companies",
        (
            "name",
            "year",
            "location",  # (country), (continent)
            "founder",
            "number",
            "product",
            "employee count",
            "product 1",
            "product 2",
            "product 3",
            "product",
            "dollars",
        ),
    ),
    (
        "Artists",
        (
            "name",
            "date",
            "location",  # (country)
            "year",
            "nickname",
            "concert 1",
            "concert 2",
            "concert 3",
            "song 1",
            "song 2",
            "song 3",
            "birth location",
        ),
    ),
    (
        "Products",
        (
            "product name",
            "year",
            "price number 1",
            "price number 2",
            "price number 3",
            "person name",
            "location",
            "company name",
            "collab name",
            "generic email",
            "phone number",
            "brand company",
        ),
    ),
    (
        "Politicians",
        (
            "birth date",
            "name",  # (last name)
            "allied faction",
            "main country",
            "other faction",
            "country 1",
            "country 2",
            "date 1",
            "date 2",
            "university name",
            "birth location",
            "date 3",
        ),
    ),
    (
        "Researchers",
        (
            "university 1",
            "date",
            "name",  # (last name)
            "science field 1",
            "science field 2",
            "birth date",
            "birth location",
            "researcher name",
            "prize name",
            "journal name 1",
            "university 2",
            "country",
        ),
    ),
)


# --- HTML Parsing and Content Generation Functions ---
def parse_master_html(html_content):
    """
    Parses the master HTML file into a nested dictionary of H1 and H2 sections.
    The structure is:
    {
        "H1 Title": {
            "H2 Title 1": <H2 content>,
            "H2 Title 2": <H2 content>,
            ...
        },
        ...
    }

    @param html_content: The HTML content as a string.
    @return: A nested dictionary structure containing H1 and H2 sections.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    nested_data = {}

    for h1 in soup.find_all("h1"):
        h1_title = h1.get_text(strip=True)
        h2_sections = {}

        h1_content_soup = BeautifulSoup("", "html.parser")
        for sibling in h1.find_next_siblings():
            if sibling.name == "h1":  # type: ignore
                break
            h1_content_soup.append(sibling)

        for h2 in h1_content_soup.find_all("h2"):
            h2_title = h2.get_text(strip=True)
            h2_content_soup = BeautifulSoup("", "html.parser")
            for h2_sibling in h2.find_next_siblings():
                if h2_sibling.name == "h2":  # type: ignore
                    break
                h2_content_soup.append(h2_sibling)
            h2_sections[h2_title] = h2_content_soup

        if h2_sections:
            nested_data[h1_title] = h2_sections
        else:
            nested_data[h1_title] = h1_content_soup

    return nested_data


def get_content_from_nested_structure(nested_dict, num):
    """
    Selects and correctly reconstructs a specific H1 and H2 section based on the template number.
    This version is robust and will not crash if FakeData.html has fewer sections than configured.

    @param nested_dict: The nested dictionary structure containing H1 and H2 sections.
    @param num: The template number to select content for.
    @return: A BeautifulSoup object containing the selected H1 and H2 content.
    """
    top_keys = list(nested_dict.keys())
    if not top_keys:
        raise ValueError(
            "Cannot select content: The 'nested_sections' dictionary is empty. Check FakeData.html."
        )

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
            logging.warning(
                f"H1 section '{top_key}' has empty H2 sections. Using fallback content."
            )
            final_soup.append(
                BeautifulSoup("<p>Content not available.</p>", "html.parser")
            )
    else:
        # If no H2s, append the direct content of the H1 section.
        if h1_section_content:
            if isinstance(h1_section_content, (BeautifulSoup, str)):
                final_soup.append(h1_section_content)
            else:
                logging.warning(
                    f"H1 section '{top_key}' content is not appendable. Using fallback."
                )
                final_soup.append(
                    BeautifulSoup("<p>Content not available.</p>", "html.parser")
                )
        else:
            # Fallback if content is completely empty
            logging.warning(f"H1 section '{top_key}' has no content. Using fallback.")
            final_soup.append(
                BeautifulSoup("<p>Content not available.</p>", "html.parser")
            )

    return final_soup


def generate_fake_data_for_type(type_index: int, seed: int = 0):
    """
    Generate a tuple of faker data objects for the given type index and seed.
    If seed is 0, generate a random seed and use it.
    Returns a dictionary: {seed: tuple_of_faker_objects}

    @param type_index: Index of the type in FAKE_DATA_TYPES to generate data for.
    @param seed: Seed for Faker to generate consistent data. If 0, a random seed is generated.
    @return: A dictionary with the seed as key and a tuple of generated fake data objects as value.
    Raises ValueError if type_index is out of range.
    """

    # Pick/generate seed
    if seed == 0:
        seed = random.randint(1, 2**31 - 1)
    Faker.seed(seed)
    fake = Faker()

    type_name, fields = FAKE_DATA_TYPES[type_index]
    result = []

    for field_tuple in fields:
        # If there are multiple variations, pick the first for now
        field = field_tuple if isinstance(field_tuple, tuple) else (field_tuple,)
        field_name = field[0].lower()

        # Map field names to faker methods/objects

        # Check if the field name contains specific keywords to determine the type of data to generate

        # If the field name contains "name" but not "company" or "product", generate a fake name
        # This allows for more specific name generation, e.g., first and last names
        # This is to avoid generating company names or product names when the field is just a name
        if (
            "name" in field_name
            and "company" not in field_name
            and "product" not in field_name
        ):

            class FakeName:
                """A class to represent a fake name with first and last names.
                It generates a full name from first and last names.
                """
                def __init__(self, fake):
                    """Initialize with a Faker instance to generate names.
                    
                    @param fake: A Faker instance to generate names.
                    Generates first and last names, and combines them into a full name.
                    """
                    self.first_name = fake.first_name()
                    self.last_name = fake.last_name()
                    self.full_name = f"{self.first_name} {self.last_name}"

                def __repr__(self):
                    return self.full_name

            result.append(FakeName(fake))
        
        # If the field name contains "company" or "brand", generate a fake company name
        # This allows for more specific company generation, e.g., brand names or company names
        elif "company" in field_name or "brand" in field_name:
            result.append(fake.company())
        
        # If the field name contains "product", generate a fake product name
        elif "product" in field_name:
            result.append(fake.word())
        
        # If the field name contains "year", generate a random year
        # If it contains "date", generate a random date object
        elif "year" in field_name or "date" in field_name:
            result.append(fake.date_object())
        
        # If the field name contains "location", "country", "city", or "continent",
        # generate a fake location object with city, country, continent, and address
        elif (
            "location" in field_name
            or "country" in field_name
            or "city" in field_name
            or "continent" in field_name
        ):
            # Return the whole location object for later use
            class FakeLocation:
                """A class to represent a fake location with city, country, continent, and address.
                It generates a location object with these attributes."""
                def __init__(self, fake):
                    """Initialize with a Faker instance to generate location data.
                    
                    @param fake: A Faker instance to generate location data.
                    Generates city, country, continent, and address attributes.
                    """
                    self.city = fake.city()
                    self.country = fake.country()

                    # Since Faker does not provide continent directly,
                    # we randomly select a continent.
                    self.continent = fake.random_element(
                        elements=(
                            "Europe",
                            "Asia",
                            "Africa",
                            "North America",
                            "South America",
                            "Australia",
                            "Antarctica",
                        )
                    )
                    self.address = fake.address()

                def __repr__(self):
                    return f"{self.address} ({self.city}, {self.country}, {self.continent})"

            result.append(FakeLocation(fake))
        
        # If the field name contains "email", generate a fake email address
        elif "email" in field_name:
            result.append(fake.email())
        
        # If the field name contains "phone", generate a fake phone number
        elif "phone" in field_name:
            result.append(fake.phone_number())
        
        # If the field name contains "number", "count",
        # generate a random integer between 1 and 10000
        elif "number" in field_name or "count" in field_name:
            result.append(fake.random_int(min=1, max=10000))
        
        # If the field name contains "dollars" or "price", generate a fake decimal number
        elif "dollars" in field_name or "price" in field_name:
            result.append(fake.pydecimal(left_digits=5, right_digits=2, positive=True))
        elif "song" in field_name or "concert" in field_name or "collab" in field_name:
            result.append(fake.word())
        elif "nickname" in field_name:
            result.append(fake.user_name())
        elif "science field" in field_name:
            result.append(fake.job())
        elif "prize" in field_name:
            result.append(fake.word() + " Prize")
        elif "journal" in field_name:
            result.append(fake.word().capitalize() + " Journal")
        elif "university" in field_name:
            result.append(fake.company() + " University")
        elif "faction" in field_name:
            result.append(fake.word().capitalize() + " Faction")
        else:
            result.append(fake.word())

    return {seed: tuple(result)}


def stringify_fake_datum(fake_datum, type: str):
    """
    Converts a fake datum to a string based on its type.
    Handles complex types like location and returns a formatted string.

    @param fake_datum: The fake data object to convert.
    @param type: The type of data to convert to string
    @return: A string representation of the fake datum.
    """

    # If the type is a location then return the appropriate part of the location
    if type.startswith("location"):
        if "city" in type:
            return fake_datum.city
        elif "country" in type:
            return fake_datum.country
        elif "continent" in type:
            return fake_datum.continent
        else:
            return str(fake_datum.address)
    
    # If the type is a name, return the appropriate part of the name
    elif type.startswith("name"):
        if "last" in type:
            return fake_datum.last_name
        elif "first" in type:
            return fake_datum.first_name
        else:
            return fake_datum.full_name
    
    # If the type is a numeric type, handle math expressions or return as string
    elif (
        type.startswith("number")
        or type.startswith("count")
        or type.startswith("dollars")
        or type.startswith("price")
    ):
        # Support math in placeholder, e.g. {number + 23}, {count * 4}
        math_expr = re.match(r"^([a-zA-Z0-9 _-]+)\s*([\+\-\*/])\s*([0-9\.]+)$", type)
        if math_expr:
            op = math_expr.group(2)
            operand = math_expr.group(3)
            try:
                value = float(fake_datum)
                expr = f"{value} {op} {operand}"
                result = eval(expr)
                if isinstance(result, float) and result.is_integer():
                    return str(int(result))
                return str(result)
            except Exception:
                print(f"Error #1")
                traceback.print_exc()
                return str(fake_datum)
        return str(fake_datum)

    # If the type is a date, format it as 'nth of Month YYYY'
    elif type.startswith("date"):
        # Format date as 'nth of Month YYYY'
        if isinstance(fake_datum, (str, int)):
            return str(fake_datum)

        def ordinal(n):
            return "%d%s" % (
                n,
                "tsnrhtdd"[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10 :: 4],
            )

        return f"{ordinal(fake_datum.day)} of {fake_datum.strftime('%B %Y')}"
    
    # If the type is a year, return the year as a string
    elif type.startswith("year"):
        # Return year as a string
        if isinstance(fake_datum, (str, int)):
            return str(fake_datum)
        return str(fake_datum.year)
    else:
        return str(fake_datum)


def generate_complete_template(template_number: int, templates, seed: int = 0):
    """
    Generates a complete HTML template based on the template number and seed.
    Returns a string of HTML content.
    Replaces placeholders like {name}, {location (city)}, etc. with generated fake data.

    @param template_number: The number of the template to generate.
    @param templates: The nested dictionary structure containing H1 and H2 sections.
    @param seed: The seed for Faker to generate consistent data. If 0, a random seed is generated.
    @return: A string of HTML content with placeholders replaced by fake data.
    """

    def pronouns_helper(pronoun_type: str, seed: int):
        """
        Given a male pronoun form (e.g., 'he', 'Him', 'His'), use the seed to select
        male, female, or they/them, and return the correct pronoun with preserved case.

        @param pronoun_type: The pronoun type to convert (e.g., 'he', 'Him', 'His').
        @param seed: The seed to determine which pronoun set to use.
        @return: The converted pronoun with preserved case.
        """
        # Define pronoun sets
        pronoun_sets = {
            "male": {
                "he": "he",
                "him": "him",
                "his": "his",
                "himself": "himself",
            },
            "female": {
                "he": "she",
                "him": "her",
                "his": "her",
                "himself": "herself",
            },
            "they": {
                "he": "they",
                "him": "them",
                "his": "their",
                "himself": "themself",
            },
        }

        # Normalize input to lowercase for lookup
        base = pronoun_type.lower()
        # Pick which set to use based on seed
        choice = ["male", "female", "they"][seed % 3]
        pronoun = pronoun_sets[choice].get(base, base)

        # Preserve case
        if pronoun_type.islower():
            return pronoun
        elif pronoun_type.istitle():
            return pronoun.capitalize()
        elif pronoun_type.isupper():
            return pronoun.upper()
        else:
            # Mixed or unknown case, fallback to original casing
            return pronoun

    # Check if a seed is provided, if not generate a random one
    if seed == 0:
        seed = random.randint(1, 2**31 - 1)

    if template_number < 1 or template_number > CONFIG["TOTAL_TEMPLATES"]:
        raise ValueError(
            "Invalid template number: must be between 1 and TOTAL_TEMPLATES."
        )
    else:
        n = template_number - 1

    # Determine which type of data to generate
    type_index = n // CONFIG["TEMPLATES_PER_TYPE"]
    if type_index >= len(FAKE_DATA_TYPES):
        raise ValueError("Invalid template number: exceeds available types.")

    # Generate fake data for the selected type
    fake_data = generate_fake_data_for_type(type_index, seed)
    fake_tuple = fake_data[seed]
    field_names = FAKE_DATA_TYPES[type_index][1]

    # Create the HTML content
    final_soup = get_content_from_nested_structure(templates, template_number)
    template = (
        final_soup.h1.get_text(strip=True), # type: ignore
        str(final_soup),
    )  # mimic the (h1, content) format
    html_content = ""

    # Prepare a mapping from normalized field names to their index in fake_tuple
    def normalize_field(field):
        """Normalizes a field name for matching.
        
        @param field: The field name to normalize.
        @return: A normalized string suitable for matching.
        """
        # Lowercase and remove extra spaces for matching
        return re.sub(r"\s+", " ", field.strip().lower())

    # Create a mapping of normalized field names to their index in the fake_tuple
    field_map = {
        normalize_field(f if isinstance(f, str) else f[0]): i
        for i, f in enumerate(field_names)
    }

    # Replace placeholders in the template body
    def replace_placeholder(match):
        """Replaces a placeholder in the template with the corresponding fake data.
        
        @param match: The regex match object containing the placeholder.
        @return: The replacement string for the placeholder.
        """
        placeholder = match.group(1)
        norm_placeholder = normalize_field(placeholder)
        # Try to find the best match in field_map
        for field_key in field_map:
            if norm_placeholder == field_key or norm_placeholder.startswith(field_key):
                idx = field_map[field_key]
                return stringify_fake_datum(fake_tuple[idx], placeholder)
        # If not found, just return the original placeholder
        return match.group(0)

    # Replace all {field} in the template body (template[1] or template[1:])
    if len(template) > 1:
        body = "".join(template[1:])  # In case template is a tuple/list of lines
        html_content += re.sub(r"\{([^}]+)\}", replace_placeholder, body)

    # Apply pronouns replacement using pure Python (no regex)
    pronoun_keys = ["he", "him", "his", "himself"]

    # Add pronouns to the HTML content
    for key in pronoun_keys:
        for variant in [key, key.capitalize(), key.upper()]:
            placeholder = "{" + variant + "}"
            replacement = pronouns_helper(variant, int(seed))
            html_content = html_content.replace(placeholder, replacement)

    soup = BeautifulSoup(html_content, "html.parser")
    return wrap_soup_in_homepage(soup, title="Template")


# --- HTML Structure and Template Generation ---
def split_html_by_tag(html_content, tag_name):
    """Splits the HTML content into sections based on the specified tag name.
    Each section is a dictionary with the tag's text as the key and the section's HTML as the value.
    
    @param html_content: The HTML content as a string.
    @param tag_name: The name of the tag to split by (e.g., 'h1', 'h2').
    @return: A dictionary where keys are the tag's text and values are BeautifulSoup objects
    containing the section's HTML.
    """

    # Parse the HTML content and find all tags of the specified type
    soup = BeautifulSoup(html_content, "html.parser")
    tags = soup.find_all(tag_name)
    all_elements = list(soup.descendants)

    sections = {}

    # Iterate through the tags and extract the HTML content between them
    for i, tag in enumerate(tags):
        tag_index = all_elements.index(tag)
        if i + 1 < len(tags):
            next_tag = tags[i + 1]
            next_tag_index = all_elements.index(next_tag)
        else:
            next_tag_index = len(all_elements)
        section_html = "".join(
            str(elem) for elem in all_elements[tag_index + 1 : next_tag_index]
        )
        section_soup = BeautifulSoup(section_html, "html.parser")
        section_name = tag.get_text(strip=True)
        sections[section_name] = section_soup
    return sections


def wrap_soup_in_homepage(soup, title="Home"):
    """    Wraps the provided BeautifulSoup object in a full HTML template with a header and footer.
    
    @param soup: The BeautifulSoup object to wrap.
    @param title: The title of the page to be used in the HTML head.
    @return: A string containing the full HTML template with the provided soup content.
    """


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

    The dictionary structure is expected to be:
    {
        "H1 Title": {
            "H2 Title 1": <H2 content>,
            "H2 Title 2": <H2 content>,
            ...
        },
        ...
    }

    @param dic: The nested dictionary structure containing H1 and H2 sections.
    @param num: The template number to select content for.
    @return: The selected H2 content as a BeautifulSoup object.
    Raises ValueError if num is out of range.
    """
    global CONFIG

    top_keys = list(dic.keys())
    top_index = num % CONFIG["NUM_TEMPLATE_TYPES"]
    top_key = top_keys[top_index]

    bottom_keys = list(dic[top_key].keys())
    bottom_index = num % CONFIG["TEMPLATES_PER_TYPE"]
    bottom_key = bottom_keys[bottom_index]

    return dic[top_key][bottom_key]


def generate_html_from_template_number(n):
    """ Generates a full HTML page from a template number.
    This function is used to generate the homepage with a specific template.
    
    @param n: The template number to generate the HTML for.
    @return: A string containing the full HTML page.
    Raises ValueError if n is out of range.
    """
    global nested_sections
    return wrap_soup_in_homepage(get_template(nested_sections, n - 1), title="Home")


def generate_page_for_bot(template_number, seed=0):
    """The main generator function that takes a number and seed and returns full HTML.
    
    @param template_number: The template number to generate the HTML for.
    @param seed: The seed for Faker to generate consistent data. If 0, a
    random seed is generated.
    @return: A string containing the full HTML page for the bot.
    """
    global nested_sections
    return generate_complete_template(template_number, nested_sections, seed=seed)


# --- Bot/DB Helper Functions (MODIFIED) ---
def get_bot_name(user_agent_string: str) -> str | None:
    """    Extracts the bot name from the user agent string if it is a bot.
    Returns the bot name or None if not a bot.

    @param user_agent_string: The user agent string from the request headers.
    @return: The bot name if detected, otherwise None.
    """

    user_agent = parse(user_agent_string)
    if user_agent.is_bot:
        return user_agent.browser.family
    return None


def create_new_bot_entry(bot_name: str) -> tuple[int, int]:
    """
    Creates a new entry for a bot in the database with a random template ID and seed.
    If the bot is new, it assigns a completely random template ID and seed.
    This function also updates the BOT_CACHE with the new template ID and seed.
    Raises an exception if the Supabase client is not initialized or if the insert fails.
    
    @param bot_name: The name of the bot to create an entry for.
    @return: A tuple containing the new template ID and seed.
    """
    logging.info(
        f"'{bot_name}' is a new bot. Assigning a completely random template and seed."
    )

    # Generate a random template ID and seed
    new_template_id = random.randint(1, CONFIG["TOTAL_TEMPLATES"])
    new_seed = random.randint(1, 2**31 - 1)
    logging.info(
        f"Randomly assigned template ID {new_template_id} and seed {new_seed} to '{bot_name}'."
    )

    # Check if Supabase client is initialized
    if supabase is None:
        raise Exception(
            "Supabase client is not initialized. Cannot save new bot entry."
        )

    # Insert the new bot entry into the database
    insert_response = (
        supabase.table("bot_visits")
        .insert(
            {"bot_name": bot_name, "template_id": new_template_id, "seed": new_seed}
        )
        .execute()
    )

    if not insert_response.data:
        raise Exception(f"Failed to save new bot '{bot_name}' to Supabase.")
    return new_template_id, new_seed


def get_or_create_bot_template_id(bot_name: str) -> tuple[int, int]:
    """
    Retrieves the template ID and seed for a bot from the database or creates a new entry if it doesn't exist.
    This function first checks the BOT_CACHE for a cached entry. If found, it returns the cached values.
    If not found in the cache, it queries the database for the bot's template ID and seed.
    If the bot is new, it creates a new entry in the database and updates the cache.
    Raises an exception if the Supabase client is not initialized or if the query/update fails.
    
    
    @param bot_name: The name of the bot to get or create a template ID and seed for.
    @return: A tuple containing the template ID and seed for the bot.
    """
    if (
        bot_name in BOT_CACHE
        and (time.time() - BOT_CACHE[bot_name]["timestamp"])
        < CONFIG["CACHE_DURATION_SECONDS"]
    ):
        logging.info(f"'{bot_name}' found in cache. Serving cached template and seed.")
        cache = BOT_CACHE[bot_name]
        return cache["template_id"], cache["seed"]
    try:
        if supabase is None:
            raise Exception(
                "Supabase client is not initialized. Cannot query bot template ID."
            )

        response = (
            supabase.table("bot_visits")
            .select("template_id", "seed")
            .eq("bot_name", bot_name)
            .execute()
        )
        if response.data:
            template_id = response.data[0]["template_id"]
            seed = response.data[0].get("seed")
            if not seed:
                # If seed is missing (old entry), generate and update it
                seed = random.randint(1, 2**31 - 1)
                supabase.table("bot_visits").update({"seed": seed}).eq(
                    "bot_name", bot_name
                ).execute()
            logging.info(
                f"'{bot_name}' is a returning bot. Found template: {template_id}, seed: {seed} in DB."
            )
        else:
            template_id, seed = create_new_bot_entry(bot_name)
        BOT_CACHE[bot_name] = {
            "template_id": template_id,
            "seed": seed,
            "timestamp": time.time(),
        }
        return template_id, seed
    except Exception as e:
        print(f"Error #2")
        traceback.print_exc()
        logging.error(f"Database query/update failed for bot '{bot_name}': {e}")
        raise


# --- Flask Application Routes ---
app = Flask(__name__)


@app.route("/")
def serve_content():
    """Serves the content based on the user agent string.
    If a bot is detected, it generates a page for the bot using the template ID and seed.
    If a human user is detected, it serves the default index.html page."""
    
    # Get the user agent string from the request headers
    user_agent_string = request.headers.get("User-Agent", "")
    bot_name = get_bot_name(user_agent_string)


    # If a bot is detected, generate the page for the bot
    # If no bot is detected, serve the default index.html page
    if bot_name:
        logging.info(f"Bot detected: '{bot_name}'")
        if not nested_sections:
            logging.error(
                f"Cannot serve '{bot_name}' because FakeData.html was not parsed."
            )
            abort(500, description="Server content source is not available.")
        try:
            template_id, seed = get_or_create_bot_template_id(bot_name)
            logging.info(
                f"Serving template {template_id} with seed {seed} for bot '{bot_name}'"
            )
            html_content = generate_page_for_bot(template_id, seed)
            return Response(html_content, mimetype="text/html")

        except Exception as e:
            print(f"Error #3")
            traceback.print_exc()
            logging.critical(
                f"A critical error occurred while processing bot request: {e}"
            )
            abort(500, description="A server error occurred.")
    else:
        logging.info("Human user detected. Serving default page.")
        return render_template("index.html")


if __name__ == "__main__":
    # --- HTML Parsing at Startup ---
    nested_sections = {}
    try:
        with open("FakeData.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        nested_sections = parse_master_html(html_content)
        logging.info(
            f"Successfully parsed FakeData.html into {len(nested_sections)} top-level sections."
        )
    except FileNotFoundError:
        print(f"Error #4")
        traceback.print_exc()
        logging.error(
            "CRITICAL: FakeData.html not found. The application cannot serve bot content."
        )
    except Exception as e:
        print(f"Error #5")
        traceback.print_exc()
        logging.error(f"CRITICAL: Failed to parse FakeData.html: {e}")

    # --- Supabase Client Initialization ---

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        logging.error("Supabase URL and Key must be set.")
        supabase = None
    else:
        supabase = create_client(supabase_url, supabase_key)

    # --- Main Application Route (Unchanged) ---

    app.run(host="0.0.0.0", port=8081)
