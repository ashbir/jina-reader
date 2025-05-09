import argparse
import requests
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse, urldefrag # Added urlunparse, urldefrag
import collections

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

def normalize_url_for_tracking(url_str: str) -> str:
    """Normalizes a URL for tracking and comparison purposes.
    - Removes fragments.
    - Removes common index files (index.html, index.htm).
    - Ensures consistent trailing slashes for directory-like paths.
    """
    url_no_frag, _ = urldefrag(url_str) 
    parsed = urlparse(url_no_frag)
    path = parsed.path

    # Remove /index.html or /index.htm from the end of the path
    if path.lower().endswith("/index.html"):
        path = path[:-10] # len("index.html")
    elif path.lower().endswith("/index.htm"):
        path = path[:-9] # len("index.htm")
    
    # If path becomes empty after removing index.html (e.g. "http://example.com/index.html"), set to "/"
    if not path:
        path = "/"
    
    # Add trailing slash if it's directory-like (not root, doesn't end with slash, last segment has no dot)
    if path != "/" and not path.endswith("/"):
        last_segment = path.split('/')[-1]
        # Only add slash if last_segment is not empty (e.g. not for "http://example.com") and has no dot
        if last_segment and '.' not in last_segment: 
            path += "/"
            
    return urlunparse(parsed._replace(path=path))

def find_internal_links(html_content: str, base_url: str, crawl_root_url_prefix: str) -> set[str]: # Added crawl_root_url_prefix
    """Parses HTML and extracts internal links relevant for documentation sites."""
    links = set()
    soup = BeautifulSoup(html_content, 'html.parser')
    parsed_base_url = urlparse(base_url) 

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        full_url = urljoin(base_url, href)
        normalized_full_url = normalize_url_for_tracking(full_url)
        parsed_normalized_full_url = urlparse(normalized_full_url)

        if (parsed_normalized_full_url.scheme in ['http', 'https'] and
                parsed_normalized_full_url.netloc == parsed_base_url.netloc and
                normalized_full_url != base_url and # Compare normalized forms
                # Ensure the URL is truly under the crawl_root_url_prefix.
                # crawl_root_url_prefix is already normalized (e.g., "https://example.com/docs/"),
                # so startswith is sufficient.
                normalized_full_url.startswith(crawl_root_url_prefix)
            ):
            
            path_part = parsed_normalized_full_url.path.strip('/')
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
    
    # Normalize the initial start_url
    normalized_start_url = normalize_url_for_tracking(start_url)
    print(f"Starting link discovery crawl from: {normalized_start_url} up to depth: {max_depth}")

    # (url, current_depth) - url here is normalized
    urls_to_visit = collections.deque([(normalized_start_url, 0)]) 
    # URLs we have added to queue to fetch its content (normalized), to avoid re-fetching for link extraction
    visited_urls_for_fetching = {normalized_start_url} 
    # All unique normalized links encountered during the crawl
    all_discovered_links = set()

    while urls_to_visit:
        current_url, current_depth = urls_to_visit.popleft() # current_url is already normalized
        all_discovered_links.add(current_url) # Add the normalized page being processed

        print(f"Fetching links from: {current_url} (depth {current_depth}) ")
        try:
            html_response_headers = {"User-Agent": "Mozilla/5.0 (compatible; PythonLinkCrawler/1.1)"}
            # Fetch using the current_url (which is normalized). Web servers typically ignore fragments for GET.
            response = requests.get(current_url, timeout=30, headers=html_response_headers)
            response.raise_for_status()
            page_html_content = response.text
            
            # find_internal_links expects the base_url for urljoin (current_url is fine as it's normalized)
            # and crawl_root_url_prefix (normalized_start_url).
            # Links returned by find_internal_links are raw (can have fragments).
            raw_links_on_page = find_internal_links(page_html_content, current_url, normalized_start_url) 
            
            current_page_normalized_links = set()
            for raw_link in raw_links_on_page:
                normalized_link = normalize_url_for_tracking(raw_link)
                current_page_normalized_links.add(normalized_link)
                # Add to all_discovered_links as well, ensuring it only contains normalized URLs
                all_discovered_links.add(normalized_link)


            # If we haven't reached max_depth, add new unvisited normalized links to the queue
            if current_depth < max_depth:
                for norm_link in current_page_normalized_links: # Iterate over normalized links from current page
                    if norm_link not in visited_urls_for_fetching:
                        # Ensure the link is truly under the crawl_root_url_prefix before adding to queue
                        # normalized_start_url is the normalized root prefix (e.g., "https://example.com/docs/")
                        if norm_link.startswith(normalized_start_url): # Corrected condition
                            visited_urls_for_fetching.add(norm_link)
                            urls_to_visit.append((norm_link, current_depth + 1))
                            # print(f"  Queued for depth {current_depth + 1}: {norm_link}")
                        
        except requests.exceptions.RequestException as e:
            print(f"  Failed to fetch HTML from {current_url}: {e}")
        except Exception as e:
            print(f"  An unexpected error occurred while processing {current_url}: {e}")

    if all_discovered_links:
        # Print all the discovered links first
        print(f"\n--- Listing {len(all_discovered_links)} unique internal links discovered up to depth {max_depth} for {normalized_start_url} ---")
        for link in sorted(list(all_discovered_links)): # Links are already normalized here
            print(link)
        
        # Print a clear summary at the very end
        print(f"\n--- Summary of Link Discovery ---")
        print(f"Starting URL: {normalized_start_url}") # Use normalized_start_url for consistency
        print(f"Requested Crawl Depth: {max_depth}")
        print(f"Total Unique Internal Links Discovered: {len(all_discovered_links)}")
        print("--- End of Link Discovery Report ---")
    else:
        print(f"\n--- Summary of Link Discovery ---")
        print(f"Starting URL: {normalized_start_url}") # Use normalized_start_url
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
                
                # Pass start_url (which is the normalized root for this crawl) as crawl_root_url_prefix
                # For the main markdown generation, we also need to ensure that the links we follow are normalized
                # and that we use normalized URLs for visited_urls tracking.
                
                raw_internal_links = find_internal_links(page_html_content, current_url, normalize_url_for_tracking(start_url)) 
                print(f"Found {len(raw_internal_links)} potential links on {current_url}.")
                for raw_link in raw_internal_links: 
                    normalized_link = normalize_url_for_tracking(raw_link)
                    if normalized_link not in visited_urls: # visited_urls should store normalized URLs
                        # Ensure the link is truly under the crawl_root_url_prefix before adding to queue
                        normalized_crawl_root = normalize_url_for_tracking(start_url)
                        if normalized_link.startswith(normalized_crawl_root): # Corrected condition
                            visited_urls.add(normalized_link) # Add normalized link to visited_urls
                            urls_to_visit.append(normalized_link) # Add normalized link to queue
                            # print(f"  Queued: {normalized_link}")
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
