import argparse
import requests
import os
from dotenv import load_dotenv # Added import

def fetch_content_from_jina_api(url: str, api_key: str) -> str:
    """
    Fetches content from the Jina AI Reader API.
    The API prepends the target URL to its own endpoint.
    Example: https://r.jina.ai/https://example.com
    """
    api_url = f"https://r.jina.ai/{url}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/markdown; charset=utf-8" # Request markdown
    }
    try:
        print(f"Fetching content from: {api_url}")
        response = requests.get(api_url, headers=headers, timeout=60) # Increased timeout
        response.raise_for_status()  # Raise an exception for HTTP errors
        
        # The API might return plain text or markdown. 
        # Forcing markdown via Accept header is a good practice.
        # If the content type is explicitly markdown, we can be more confident.
        content_type = response.headers.get("Content-Type", "")
        if "markdown" in content_type.lower():
            print("Received Markdown content.")
        elif "text/plain" in content_type.lower():
            print("Received plain text content. This might be Markdown or just text.")
        else:
            print(f"Received content with Content-Type: {content_type}. Assuming it's usable as Markdown.")
            
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url} via Jina API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response text: {e.response.text}")
        return None

def main():
    load_dotenv() # Added to load .env file

    parser = argparse.ArgumentParser(description="Convert a webpage to Markdown using the Jina AI Reader API (r.jina.ai).")
    parser.add_argument("url", help="The URL of the website to convert.")
    parser.add_argument("-o", "--output", default="output.md", help="The name of the output Markdown file (default: output.md).")
    parser.add_argument("--api_key", help="Jina AI API Key. If not provided, it will try to use the JINA_AI_API_KEY environment variable.")

    args = parser.parse_args()

    api_key = args.api_key or os.getenv("JINA_AI_API_KEY")

    if not api_key:
        print("Error: Jina AI API Key not found. Please provide it via the --api_key argument or set the JINA_AI_API_KEY environment variable.")
        return

    if not args.url.startswith("http://") and not args.url.startswith("https://"):
        print("Warning: URL does not start with http:// or https://. Prepending https://")
        target_url = "https://" + args.url
    else:
        target_url = args.url
        
    print(f"Using Jina AI Reader API to process URL: {target_url}")
    markdown_content = fetch_content_from_jina_api(target_url, api_key)

    if not markdown_content:
        print("Failed to retrieve content.")
        return

    print(f"Saving Markdown to {args.output}...")
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        print("Conversion complete.")
    except IOError as e:
        print(f"Error writing to file {args.output}: {e}")

if __name__ == "__main__":
    main()
