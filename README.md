# Honeypot Logging Site used to understand bot scraping activity and how they interact with each other.

## Goals

The main goal of this project is to create human-written HTML homepage templates representing different categories of websites which include fingerprintable data. These templates will later be hosted dynamically on a honeypot website designed to attract and monitor AI web scrapers.
The research objective is to feed each AI web scraper distinct versions of these webpages, then query the scrapers afterward to extract the information they collected. By analyzing the scrapers' responses, we aim to better understand how different bots interact with each other, how they extract information, and how their behavior varies depending on website content and structure.

## Project Structure

1. Templates: Include all of the template pages of the website in one singular HTML file. Code parses through the file to break it up as needed.
2. github/workflow: Used to auto-deploy to the server every time the repository is updated.

## Credentials

1. Supabase Link: `SUPABASE_URL` The URL to the supabase tables and logs
2. Supabase Key:  `SUPABASE_KEY` The key to access and have the logs be logged in the table

These credentials should be in a .env environment file.

## Build

This is the instructions on how to build the project.

### Prerequisites

- python3.11
- gunicorn (optional)

1. Clone the github repository
2. Create a virtual environment using the terminal `python3.11 -m venv venv`
3. After activating the virtual environment using `source venv/bin/activate`
4. Install poetry `pip install poetry`
5. Install the required packages using poetry `poetry install`. Note: ignore the error about running the code.

## Running the Server

The server can be deployed directly on port 8080 using: `poetry run python main.py`.

However, it is recommended to use a WSGI like `gunicorn` to manage paralallism to make the server more efficient to not overload the server.
