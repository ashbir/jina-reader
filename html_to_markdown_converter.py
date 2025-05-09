import argparse
import requests
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse, urldefrag, parse_qs, urlencode # Added urlunparse, urldefrag, parse_qs, urlencode
import collections
import re # Added import re

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
    - Removes specific query parameters like 'rev', and 'do' (e.g. 'do=revisions', 'do=diff').
    """
    url_no_frag, _ = urldefrag(url_str) 
    parsed = urlparse(url_no_frag)
    path = parsed.path
    query_original = parsed.query

    # Process query parameters to remove revision-related ones
    query_new = ''
    if query_original:
        params = parse_qs(query_original, keep_blank_values=True)
        # Parameters to remove. 'rev' for revision numbers, 'do' for actions like 'revisions' or 'diff'.
        keys_to_remove = ['rev', 'do']
        filtered_params = {k: v for k, v in params.items() if k not in keys_to_remove}
        query_new = urlencode(filtered_params, doseq=True)
    
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
            
    return urlunparse(parsed._replace(path=path, query=query_new)) # Use new query

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

# New helper function to calculate parent-aware crawl root
def get_parent_aware_crawl_root(normalized_url: str, parent_level: int) -> str:
    if parent_level <= 0:
        return normalized_url

    parsed = urlparse(normalized_url)
    # normalized_url is expected to have a trailing slash for directories,
    # e.g., "https://example.com/docs/foo/" or "https://example.com/"
    
    path_segments = [seg for seg in parsed.path.split('/') if seg] # Filters out empty strings

    num_segments_to_keep = max(0, len(path_segments) - parent_level)
    kept_segments = path_segments[:num_segments_to_keep]

    new_path = "/"
    if kept_segments:
        new_path += "/".join(kept_segments) + "/"
    # If kept_segments is empty, new_path remains "/" which is correct for the domain root.
    
    return urlunparse(parsed._replace(path=new_path))

# New helper function to discover links
def _get_discovered_links(
    initial_url: str, 
    max_depth: int, 
    parent_level: int, # Added parent_level
    user_agent: str,
    enable_logging: bool = True
) -> set[str]:
    
    normalized_start_url = normalize_url_for_tracking(initial_url)
    effective_crawl_root_prefix = get_parent_aware_crawl_root(normalized_start_url, parent_level)
    
    if enable_logging and parent_level > 0:
        print(f"Effective crawl root for link discovery: {effective_crawl_root_prefix}")

    urls_to_visit = collections.deque([(normalized_start_url, 0)]) 
    visited_urls_for_fetching = {normalized_start_url} 
    all_discovered_links = set()

    while urls_to_visit:
        current_url, current_depth = urls_to_visit.popleft() # current_url is already normalized
        
        # Only add current_url to all_discovered_links if it's within the effective root
        if not current_url.startswith(effective_crawl_root_prefix):
            if enable_logging:
                print(f"Skipping {current_url} as it's outside the effective crawl root {effective_crawl_root_prefix}")
            continue
        all_discovered_links.add(current_url) 

        if enable_logging:
            # This log matches the original one in crawl_and_list_internal_links
            print(f"Fetching links from: {current_url} (depth {current_depth})")
        
        try:
            html_response_headers = {"User-Agent": user_agent}
            response = requests.get(current_url, timeout=30, headers=html_response_headers)
            response.raise_for_status()
            page_html_content = response.text
            
            # find_internal_links expects the base_url for urljoin (current_url is fine as it's normalized)
            # and crawl_root_url_prefix (effective_crawl_root_prefix).
            raw_links_on_page = find_internal_links(page_html_content, current_url, effective_crawl_root_prefix) 
            
            current_page_normalized_links = set()
            for raw_link in raw_links_on_page:
                normalized_link = normalize_url_for_tracking(raw_link)
                current_page_normalized_links.add(normalized_link)
                # Add to all_discovered_links as well, ensuring it only contains normalized URLs
                # that are within the effective_crawl_root_prefix (guaranteed by find_internal_links)
                all_discovered_links.add(normalized_link)

            # If we haven't reached max_depth, add new unvisited normalized links to the queue
            if current_depth < max_depth:
                for norm_link in current_page_normalized_links: # Iterate over normalized links from current page
                    if norm_link not in visited_urls_for_fetching:
                        # Ensure the link is truly under the effective_crawl_root_prefix before adding to queue
                        if norm_link.startswith(effective_crawl_root_prefix): 
                            visited_urls_for_fetching.add(norm_link)
                            urls_to_visit.append((norm_link, current_depth + 1))
                            # The original commented-out print for "Queued for depth..." is kept commented out.
                        
        except requests.exceptions.RequestException as e:
            if enable_logging: # These logs match the original ones
                print(f"  Failed to fetch HTML from {current_url}: {e}")
        except Exception as e:
            if enable_logging: # These logs match the original ones
                print(f"  An unexpected error occurred while processing {current_url}: {e}")
                
    return all_discovered_links

def crawl_and_list_internal_links(start_url: str, max_depth: int, parent_level: int): # Added parent_level
    """Crawls a website starting from start_url up to max_depth and lists all unique internal links found."""
    
    # Normalize the initial start_url for the introductory print message
    normalized_start_url_for_print = normalize_url_for_tracking(start_url)
    print(f"Starting link discovery crawl from: {normalized_start_url_for_print} up to depth: {max_depth}, parent level: {parent_level}")

    # Call the refactored helper function to get the links.
    # Logging within _get_discovered_links is enabled to maintain original behavior.
    # User agent for this mode is "Mozilla/5.0 (compatible; PythonLinkCrawler/1.1)"
    all_discovered_links = _get_discovered_links(
        start_url,
        max_depth,
        parent_level, # Pass parent_level
        user_agent="Mozilla/5.0 (compatible; PythonLinkCrawler/1.1)",
        enable_logging=True 
    )
    
    if all_discovered_links:
        # Print all the discovered links first
        print(f"\n--- Listing {len(all_discovered_links)} unique internal links discovered up to depth {max_depth} for {normalized_start_url_for_print} ---")
        for link in sorted(list(all_discovered_links)): # Links are already normalized here
            print(link)
        
        # Print a clear summary at the very end
        print(f"\n--- Summary of Link Discovery ---")
        print(f"Starting URL: {normalized_start_url_for_print}") # Use normalized_start_url for consistency
        print(f"Requested Crawl Depth: {max_depth}")
        print(f"Total Unique Internal Links Discovered: {len(all_discovered_links)}")
        print("--- End of Link Discovery Report ---")
    else:
        print(f"\n--- Summary of Link Discovery ---")
        print(f"Starting URL: {normalized_start_url_for_print}") # Use normalized_start_url
        print(f"Requested Crawl Depth: {max_depth}")
        print("No internal links found.")
        print("--- End of Link Discovery Report ---")

# New function to generate a safe local filepath from a URL
def generate_local_filepath(normalized_url: str, output_dir: str) -> str:
    parsed_url = urlparse(normalized_url)
    
    filename_base = parsed_url.netloc
    path_cleaned = parsed_url.path.strip('/') 
    
    if path_cleaned:
        path_segments = path_cleaned.split('/')
        last_segment = path_segments[-1]
        
        # Check if the last segment has a common web extension
        if '.' in last_segment:
            name_part, ext_part = os.path.splitext(last_segment)
            if ext_part.lower() in ['.html', '.htm']:
                if name_part: # If "index.html" becomes "index"
                    path_segments[-1] = name_part
                else: # If ".html" was the segment or became empty after stripping
                    path_segments.pop() # Remove empty segment
                    if not path_segments: # If path becomes empty (e.g. /index.html)
                         filename_base += "_index" # Handled by else block later if path_cleaned is now empty
        
        # Reconstruct cleaned path part
        # Filter out empty segments that might arise if a segment was e.g. "index.html" and became empty
        valid_segments = [seg for seg in path_segments if seg]
        if valid_segments:
            filename_base += "_" + "_".join(valid_segments)
        elif parsed_url.path.strip('/'): # Original path was not empty, but segments are now (e.g. /index.html)
            filename_base += "_index"
            
    else: # Root URL (e.g. http://example.com/)
        filename_base += "_index"
        
    # Sanitize the entire base name
    # Allow alphanumeric, underscore, hyphen. Replace others with underscore.
    safe_filename_base = re.sub(r'[^a-zA-Z0-9_-]', '_', filename_base)
    # Replace multiple underscores with a single underscore
    safe_filename_base = re.sub(r'_+', '_', safe_filename_base)
    # Remove leading/trailing underscores
    safe_filename_base = safe_filename_base.strip('_')

    if not safe_filename_base: # Should be rare, but as a fallback
        safe_filename_base = "untitled_page"

    final_filename = safe_filename_base + ".md"
    return os.path.join(output_dir, final_filename)

# New function to convert internal links in Markdown to relative paths
def convert_markdown_links(
    markdown_content: str, 
    current_page_normalized_url: str, 
    url_to_filepath_map: dict
) -> str:
    
    def replace_link(match):
        link_text = match.group(1)
        original_href = match.group(2)

        # Resolve the href against the current page's URL to get an absolute URL
        # current_page_normalized_url is the base for resolving relative links in its content
        absolute_href = urljoin(current_page_normalized_url, original_href)
        
        # Separate fragment
        abs_url_no_frag, fragment = urldefrag(absolute_href)
        
        # Normalize this absolute URL to match the style of keys in url_to_filepath_map
        normalized_linked_url = normalize_url_for_tracking(abs_url_no_frag)

        if normalized_linked_url in url_to_filepath_map:
            # This is an internal link that we have downloaded
            target_local_abs_path = url_to_filepath_map[normalized_linked_url]
            
            # current_page_normalized_url is already normalized and is a key in url_to_filepath_map
            current_page_abs_path = url_to_filepath_map[current_page_normalized_url]
            current_page_dir = os.path.dirname(current_page_abs_path)
            
            if not current_page_dir: # If current page is in the root of output_dir
                current_page_dir = "." # os.path.relpath needs a start dir

            relative_path = os.path.relpath(target_local_abs_path, start=current_page_dir)
            # Ensure POSIX-style separators for Markdown links, even on Windows
            relative_path = relative_path.replace(os.sep, '/')

            new_href = relative_path
            if fragment:
                new_href += "#" + fragment
            return f"[{link_text}]({new_href})"
        else:
            # External link or link to a page not in our set, leave as is
            return match.group(0)

    # Regex to find Markdown links: [text](url)
    # It handles various characters in link text and URL.
    link_pattern = r'\\[([^\\]\\[\\]]*)\\]\\(([^\\)]*)\\)' # Escaped for Python string
    # Simpler pattern if complex link texts are not an issue: r'\[([^\]]*)\]\(([^)]+)\)'
    # Using a more robust pattern for common markdown links:
    link_pattern = r'\[(.*?)\]\((.*?)\)'


    try:
        processed_content = re.sub(link_pattern, replace_link, markdown_content)
        return processed_content
    except Exception as e:
        print(f"  Error during link conversion for {current_page_normalized_url}: {e}")
        return markdown_content # Return original content if conversion fails


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Convert a ReadTheDocs-like website to Markdown or list internal links with crawling."
    )
    parser.add_argument("url", nargs='?', default=None, help="The starting URL for conversion (required if not using --list-links).")
    parser.add_argument("-o", "--output", default="markdown_output", help="The output directory for Markdown files (default: markdown_output).")
    parser.add_argument("--api_key", help="Jina AI API Key. If not provided, it will try to use the JINA_AI_API_KEY environment variable.")
    parser.add_argument("--list-links", metavar="URL", help="Fetch the specified URL and list all discoverable internal links by crawling, then exit.")
    parser.add_argument("--crawl-depth", type=int, default=0, help="Depth for link discovery when using --list-links or for Markdown conversion. 0 means only links on the initial page, 1 means links on those pages too, etc. (default: 0).")
    parser.add_argument("--parent", type=int, default=0, help="Number of parent directories to allow links to go up to (default: 0).") # Added --parent argument

    args = parser.parse_args()

    if args.list_links:
        # Ensure URL starts with http/https for list-links mode as well
        list_start_url = args.list_links
        if not list_start_url.startswith("http://") and not list_start_url.startswith("https://"):
            print(f"Warning: URL for --list-links ({list_start_url}) does not start with http:// or https://. Prepending https://")
            list_start_url = "https://" + list_start_url
        
        crawl_and_list_internal_links(list_start_url, args.crawl_depth, args.parent) # Pass args.parent
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

    # Create output directory
    output_dir = args.output
    try:
        os.makedirs(output_dir, exist_ok=True)
        print(f"Markdown files will be saved in: {os.path.abspath(output_dir)}")
    except OSError as e:
        print(f"Error creating output directory {output_dir}: {e}")
        return

    # all_markdown_content = [] # Removed: content will be saved to individual files

    print(f"Starting conversion for: {start_url}, with crawl depth: {args.crawl_depth}, parent level: {args.parent}")
    
    print("Discovering all pages to convert...")
    links_to_convert = _get_discovered_links(
        start_url,
        args.crawl_depth,
        args.parent, # Pass args.parent
        user_agent="Mozilla/5.0 (compatible; PythonDocsCrawler/1.0)", 
        enable_logging=True 
    )

    if not links_to_convert:
        print("No links discovered for conversion based on the crawl depth. Exiting.")
        return

    print(f"Found {len(links_to_convert)} unique pages to convert.")

    # Build URL to local filepath map
    url_to_filepath_map = {}
    for norm_url in links_to_convert:
        url_to_filepath_map[norm_url] = generate_local_filepath(norm_url, output_dir)

    processed_pages_count = 0
    for current_url_to_convert in sorted(list(links_to_convert)):
        print(f"Processing page ({processed_pages_count + 1}/{len(links_to_convert)}): {current_url_to_convert}")
        
        local_filepath = url_to_filepath_map[current_url_to_convert]

        markdown_page_content = fetch_content_from_jina_api(current_url_to_convert, api_key)
        
        if markdown_page_content:
            # Convert internal links to relative paths
            print(f"  Converting internal links for: {current_url_to_convert}")
            converted_markdown = convert_markdown_links(
                markdown_page_content, 
                current_url_to_convert, # This is already normalized from _get_discovered_links
                url_to_filepath_map
            )
            
            try:
                with open(local_filepath, "w", encoding="utf-8") as f:
                    f.write(converted_markdown)
                print(f"  Successfully saved Markdown to: {local_filepath}")
                processed_pages_count += 1
            except IOError as e:
                print(f"  Error writing Markdown to file {local_filepath}: {e}")
        else:
            print(f"  Skipping {current_url_to_convert} due to fetch error or empty content from Jina API.")
        
    if processed_pages_count == 0:
        print("\nNo content was successfully retrieved and converted.")
        return

    # final_markdown = "\n".join(all_markdown_content) # Removed
    print(f"\nTotal pages processed and saved: {processed_pages_count}")
    # print(f"Saving aggregated Markdown to {args.output}...") # Removed
    # try: # Removed
    #     with open(args.output, "w", encoding="utf-8") as f: # Removed
    #         f.write(final_markdown) # Removed
    print("Conversion complete. Markdown files are in:", os.path.abspath(output_dir))
    # except IOError as e: # Removed
    #     print(f"Error writing to file {args.output}: {e}") # Removed

if __name__ == "__main__":
    main()
