import argparse
import requests
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup  # Added
from urllib.parse import urljoin, urlparse  # Added
import collections # Added

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

def find_internal_links(html_content: str, base_url: str) -> set[str]:
    """Parses HTML and extracts internal links relevant for documentation sites."""
    links = set()
    soup = BeautifulSoup(html_content, 'html.parser')
    parsed_base_url = urlparse(base_url)

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        full_url = urljoin(base_url, href)
        parsed_full_url = urlparse(full_url)

        # Filter for relevant links:
        # 1. Must be http or https
        # 2. Must be on the same domain as the base_url
        # 3. Not a fragment link on the same page (e.g., #section)
        # 4. Path should not be identical (already processed or is base_url itself)
        # 5. Typically documentation links end with .html, no extension, or /
        if (parsed_full_url.scheme in ['http', 'https'] and
                parsed_full_url.netloc == parsed_base_url.netloc and
                full_url != base_url and
                not parsed_full_url.fragment):
            
            # Check if it looks like a document page
            path_part = parsed_full_url.path.strip('/')
            if not path_part: # Root path, if different from base_url, could be relevant
                 links.add(full_url)
                 continue

            # Allow if it ends with .html or has no file extension in the last path segment
            last_segment = path_part.split('/')[-1]
            if '.' not in last_segment or last_segment.endswith('.html'):
                links.add(full_url)
    return links

def crawl_and_list_internal_links(start_url: str, max_depth: int):
    """Crawls a website starting from start_url up to max_depth and lists all unique internal links found."""
    print(f"Starting link discovery crawl from: {start_url} up to depth: {max_depth}")

    # (url, current_depth)
    urls_to_visit = collections.deque([(start_url, 0)]) 
    # URLs we have added to queue to fetch its content, to avoid re-fetching for link extraction
    visited_urls_for_fetching = {start_url} 
    # All unique links encountered during the crawl (includes pages visited and links found on them)
    all_discovered_links = set()

    while urls_to_visit:
        current_url, current_depth = urls_to_visit.popleft()
        all_discovered_links.add(current_url) # Add the page being processed as a discovered link

        print(f"Fetching links from: {current_url} (depth {current_depth}) ")
        try:
            html_response_headers = {"User-Agent": "Mozilla/5.0 (compatible; PythonLinkCrawler/1.1)"}
            response = requests.get(current_url, timeout=30, headers=html_response_headers)
            response.raise_for_status()
            page_html_content = response.text
            
            # Find links on the current page
            links_on_page = find_internal_links(page_html_content, current_url)
            all_discovered_links.update(links_on_page) # Add all links found on this page

            # If we haven't reached max_depth, add new unvisited links to the queue
            if current_depth < max_depth:
                for link in links_on_page:
                    if link not in visited_urls_for_fetching:
                        visited_urls_for_fetching.add(link)
                        urls_to_visit.append((link, current_depth + 1))
                        # print(f"  Queued for depth {current_depth + 1}: {link}")
                        
        except requests.exceptions.RequestException as e:
            print(f"  Failed to fetch HTML from {current_url}: {e}")
        except Exception as e:
            print(f"  An unexpected error occurred while processing {current_url}: {e}")

    if all_discovered_links:
        # Print all the discovered links first
        print(f"\n--- Listing {len(all_discovered_links)} unique internal links discovered up to depth {max_depth} for {start_url} ---")
        for link in sorted(list(all_discovered_links)):
            print(link)
        
        # Print a clear summary at the very end
        print(f"\n--- Summary of Link Discovery ---")
        print(f"Starting URL: {start_url}")
        print(f"Requested Crawl Depth: {max_depth}")
        print(f"Total Unique Internal Links Discovered: {len(all_discovered_links)}")
        print("--- End of Link Discovery Report ---")
    else:
        print(f"\n--- Summary of Link Discovery ---")
        print(f"Starting URL: {start_url}")
        print(f"Requested Crawl Depth: {max_depth}")
        print("No internal links found.")
        print("--- End of Link Discovery Report ---")

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Convert a ReadTheDocs-like website to Markdown or list internal links with crawling."
    )
    parser.add_argument("url", nargs='?', default=None, help="The starting URL for conversion (required if not using --list-links).")
    parser.add_argument("-o", "--output", default="output.md", help="The name of the output Markdown file (default: output.md).")
    parser.add_argument("--api_key", help="Jina AI API Key. If not provided, it will try to use the JINA_AI_API_KEY environment variable.")
    parser.add_argument("--max_pages", type=int, default=10, help="Maximum number of pages to crawl and convert for Markdown generation (default: 10).")
    parser.add_argument("--list-links", metavar="URL", help="Fetch the specified URL and list all discoverable internal links by crawling, then exit.")
    parser.add_argument("--crawl-depth", type=int, default=0, help="Depth for link discovery when using --list-links. 0 means only links on the initial page, 1 means links on those pages too, etc. (default: 0).")

    args = parser.parse_args()

    if args.list_links:
        # Ensure URL starts with http/https for list-links mode as well
        list_start_url = args.list_links
        if not list_start_url.startswith("http://") and not list_start_url.startswith("https://"):
            print(f"Warning: URL for --list-links ({list_start_url}) does not start with http:// or https://. Prepending https://")
            list_start_url = "https://" + list_start_url
        
        crawl_and_list_internal_links(list_start_url, args.crawl_depth)
        return

    if not args.url:
        parser.error("the following arguments are required: url (unless --list-links is used)")

    api_key = args.api_key or os.getenv("JINA_AI_API_KEY")

    if not api_key:
        print("Error: Jina AI API Key not found. Please provide it via the --api_key argument or set the JINA_AI_API_KEY environment variable.")
        return

    if not args.url.startswith("http://") and not args.url.startswith("https://"):
        print("Warning: URL does not start with http:// or https://. Prepending https://")
        start_url = "https://" + args.url
    else:
        start_url = args.url

    all_markdown_content = []
    # Use a deque for BFS traversal
    urls_to_visit = collections.deque([start_url])
    # Set to keep track of URLs that have been added to the queue (to avoid re-adding)
    # or have been processed.
    visited_urls = {start_url} 

    print(f"Starting crawl from: {start_url}. Max pages: {args.max_pages}")

    processed_pages_count = 0
    while urls_to_visit and processed_pages_count < args.max_pages:
        current_url = urls_to_visit.popleft()
        
        print(f"Processing page ({processed_pages_count + 1}/{args.max_pages}): {current_url}")

        # 1. Fetch Markdown content for the current page using Jina API
        markdown_page_content = fetch_content_from_jina_api(current_url, api_key)
        
        if markdown_page_content:
            all_markdown_content.append(f"\n\n--- Page Source: {current_url} ---\n\n{markdown_page_content}")
            processed_pages_count += 1
        else:
            print(f"Skipping {current_url} due to fetch error or empty content from Jina API.")
            # If Jina fails, we might still want to crawl its links if we can get raw HTML
            # For now, if Jina fails, we don't try to get links from it.

        # 2. Fetch raw HTML of the current page to find new links (only if we need more pages)
        if processed_pages_count < args.max_pages:
            try:
                # Use a common user-agent
                html_response_headers = {"User-Agent": "Mozilla/5.0 (compatible; PythonDocsCrawler/1.0)"}
                response = requests.get(current_url, timeout=30, headers=html_response_headers)
                response.raise_for_status()
                page_html_content = response.text
                
                internal_links = find_internal_links(page_html_content, current_url)
                print(f"Found {len(internal_links)} potential links on {current_url}.")
                for link in internal_links:
                    if link not in visited_urls:
                        visited_urls.add(link)
                        urls_to_visit.append(link)
                        # print(f"  Queued: {link}")
            except requests.exceptions.RequestException as e:
                print(f"Failed to fetch HTML for link discovery from {current_url}: {e}")
        
        if not urls_to_visit and processed_pages_count < args.max_pages:
            print("No more URLs to visit.")

    if not all_markdown_content:
        print("No content was successfully retrieved and converted.")
        return

    final_markdown = "\n".join(all_markdown_content)
    print(f"\nTotal pages processed and content appended: {processed_pages_count}")
    print(f"Saving aggregated Markdown to {args.output}...")
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(final_markdown)
        print("Conversion complete.")
    except IOError as e:
        print(f"Error writing to file {args.output}: {e}")

if __name__ == "__main__":
    main()
