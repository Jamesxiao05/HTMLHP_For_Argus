import sys
import os
import random
import argparse

# Ensure the main module is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import (
    CONFIG,
    generate_complete_template,
    parse_master_html,
)

def load_templates_from_html(html_path="FakeData.html"):
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    nested_sections = parse_master_html(html_content)
    # Convert nested_sections to a list of templates (h1, h2, content)
    templates = []
    for h1, h2s in nested_sections.items():
        if isinstance(h2s, dict):
            for h2, content in h2s.items():
                templates.append((h1, h2, str(content)))
        else:
            templates.append((h1, str(h2s)))
    return templates

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def run_test(template_number, templates, seed=None, interactive=False, test_idx=None, total_tests=None):
    html = ""
    if seed is None:
        seed = random.randint(1, 2**31 - 1)
    try:
        html = generate_complete_template(template_number, templates, seed)
        assert "<h1>" in html, f"Template {template_number} missing <h1>"
        assert "{" not in html, f"Template {template_number} has unreplaced placeholders"
        result = f"Template {template_number} (seed={seed}): PASS"
    except Exception as e:
        result = f"Template {template_number} (seed={seed}): FAIL - {e}"
    if interactive:
        clear_screen()
        if test_idx is not None and total_tests is not None:
            print(f"Test {test_idx}/{total_tests}")
        print(result)
        print("-" * 60)
        print(html)
        input("Press Enter for next test...")
    else:
        print(result)

def test_comprehensive(templates, start=1, interactive=False):
    total_templates = CONFIG["TOTAL_TEMPLATES"]
    for idx, template_number in enumerate(range(start, total_templates + 1), 1):
        run_test(template_number, templates, interactive=interactive, test_idx=idx, total_tests=total_templates-start+1)

def test_random(templates, count=5, interactive=False):
    total_templates = CONFIG["TOTAL_TEMPLATES"]
    for idx in range(1, count + 1):
        template_number = random.randint(1, total_templates)
        run_test(template_number, templates, interactive=interactive, test_idx=idx, total_tests=count)

def test_single(templates, template_number, repeat=1, interactive=False):
    for idx in range(1, repeat + 1):
        run_test(template_number, templates, interactive=interactive, test_idx=idx, total_tests=repeat)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test all templates for HTML generation.")
    parser.add_argument("--mode", choices=["comprehensive", "random", "single"], default="comprehensive", help="Test mode")
    parser.add_argument("--start", type=int, default=1, help="Start index for comprehensive mode")
    parser.add_argument("--count", type=int, default=5, help="Number of random tests for random mode")
    parser.add_argument("--template", type=int, default=1, help="Template number for single mode")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat count for single mode")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode (wait for user input between tests)")
    parser.add_argument("--html", type=str, default="FakeData.html", help="Path to FakeData.html")

    args = parser.parse_args()
    templates = load_templates_from_html(args.html)

    if args.mode == "comprehensive":
        test_comprehensive(templates, start=args.start, interactive=args.interactive)
    elif args.mode == "random":
        test_random(templates, count=args.count, interactive=args.interactive)
    elif args.mode == "single":
        test_single(templates, template_number=args.template, repeat=args.repeat, interactive=args.interactive)