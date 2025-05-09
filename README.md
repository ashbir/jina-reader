# Jina Reader HTML to Markdown Converter

This script converts a website, particularly those structured like ReadTheDocs pages, into a collection of Markdown files. It uses the Jina AI Reader API to fetch and convert HTML content to Markdown.

## Features

- **Crawls Websites**: Discovers internal links on a website up to a specified depth.
- **Converts HTML to Markdown**: Uses Jina AI's `https://r.jina.ai/` service to convert HTML content to Markdown.
- **Local File Output**: Saves each converted page as a separate Markdown file in a specified output directory.
- **Relative Link Conversion**: Converts absolute internal links in the Markdown content to relative paths, suitable for static site generators or local browsing.
- **Flexible Crawling**:
    - `--crawl-depth`: Control how many levels deep the crawler goes.
    - `--parent`: Allow the crawler to go up a specified number of parent directories from the starting URL.
- **Link Listing Mode**: Can list all discoverable internal links without performing conversion.
- **Handles URL Normalization**:
    - Removes URL fragments.
    - Standardizes trailing slashes.
    - Ignores common index files (e.g., `index.html`).
    - Strips revision-related query parameters (e.g., `?rev=`, `?do=revisions`) to fetch the latest version of a page.

## Prerequisites

- Python 3.x
- Dependencies listed in `requirements.txt`

## Setup

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **API Key**:
    You need a Jina AI API key. You can provide this key in one of two ways:
    *   Create a `.env` file in the same directory as the script with the following content:
        ```
        JINA_AI_API_KEY="your_api_key_here"
        ```
    *   Pass the API key directly using the `--api_key` command-line argument.

## Usage

### Converting a Website to Markdown

```bash
python html_to_markdown_converter.py <START_URL> [OPTIONS]
```

**Arguments**:

*   `url`: The starting URL for conversion (required unless `--list-links` is used).

**Options**:

*   `-o OUTPUT_DIR`, `--output OUTPUT_DIR`: The output directory for Markdown files (default: `markdown_output`).
*   `--api_key API_KEY`: Jina AI API Key. Overrides the key in `.env` if provided.
*   `--crawl-depth DEPTH`: Depth for link discovery. `0` means only the initial page, `1` means links on those pages too, etc. (default: `0`).
*   `--parent LEVEL`: Number of parent directories to allow links to go up to from the `START_URL` (default: `0`, meaning only URLs under the `START_URL`'s path).

**Example**:

```bash
python html_to_markdown_converter.py "https://docs.example.com/guides/" --crawl-depth 2 --output my_markdown_docs
```
This command will start crawling from `https://docs.example.com/guides/`, go two levels deep, and save the Markdown files in the `my_markdown_docs` directory.

### Listing Internal Links

To list all discoverable internal links without converting them:

```bash
python html_to_markdown_converter.py --list-links <START_URL> [OPTIONS]
```

**Options for `--list-links`**:

*   `--crawl-depth DEPTH`: Same as for conversion (default: `0`).
*   `--parent LEVEL`: Same as for conversion (default: `0`).

**Example**:

```bash
python html_to_markdown_converter.py --list-links "https://www.example.com/docs/" --crawl-depth 1 --parent 1
```
This will list all links found starting from `https://www.example.com/docs/`, going one level deep, and allowing links to go one parent directory up (e.g., to `https://www.example.com/`).

## How it Works

1.  **Link Discovery (`_get_discovered_links`)**:
    *   Starts from the initial URL.
    *   Normalizes URLs for consistent tracking (e.g., adds trailing slashes, removes fragments and revision parameters).
    *   Calculates an `effective_crawl_root_prefix` based on the `--parent` argument. Only links starting with this prefix are considered.
    *   Fetches HTML content of the current page.
    *   Uses BeautifulSoup to parse the HTML and find all `<a>` tags.
    *   Filters for internal links that are within the `effective_crawl_root_prefix`.
    *   Adds newly discovered (and normalized) links to a queue and a set of visited URLs to avoid redundant fetching and processing.
    *   Continues until the queue is empty or `max_depth` is reached.

2.  **Content Fetching (`fetch_content_from_jina_api`)**:
    *   For each unique discovered URL, it makes a request to the Jina AI Reader API (`https://r.jina.ai/YOUR_TARGET_URL`).
    *   The API returns the content of the URL converted to Markdown.

3.  **File Naming (`generate_local_filepath`)**:
    *   Generates a safe local filename from each normalized URL to store the Markdown content. It replaces special characters and structures the name based on the URL's domain and path.

4.  **Markdown Link Conversion (`convert_markdown_links`)**:
    *   After fetching the Markdown content for a page, this function parses the Markdown.
    *   It finds all Markdown links `[text](url)`.
    *   For each link, it resolves the `url` against the current page's URL to get an absolute URL.
    *   This absolute URL is then normalized.
    *   If the normalized linked URL corresponds to one of the pages that were downloaded (i.e., it's an internal link within the crawled set), the link's `url` is converted to a relative file path.
    *   For example, a link from `markdown_output/docs_page1.md` to `https://example.com/docs/page2` (which becomes `markdown_output/docs_page2.md`) would be converted to `[link text](docs_page2.md)` or `[link text](../section/other_page.md)` depending on the directory structure.
    *   External links or links to pages not in the crawled set are left unchanged.

5.  **Main Process**:
    *   Parses command-line arguments.
    *   If `--list-links` is used, it calls `crawl_and_list_internal_links` and exits.
    *   Otherwise, it proceeds with conversion:
        *   Calls `_get_discovered_links` to get all URLs to convert.
        *   Creates a mapping from these normalized URLs to their future local file paths.
        *   Iterates through the discovered URLs:
            *   Fetches Markdown content using Jina AI.
            *   Converts internal links in the fetched Markdown to relative paths using the URL-to-filepath map.
            *   Saves the processed Markdown to the corresponding local file.

## Error Handling

*   The script includes basic error handling for network requests and file operations.
*   If the Jina AI API returns an error or fails to fetch content, the script will print an error message and skip that URL.

## User-Agent

*   The script uses distinct User-Agent strings for link discovery and content conversion to help identify the crawler's purpose:
    *   Link Discovery: `Mozilla/5.0 (compatible; PythonLinkCrawler/1.1)`
    *   Content Conversion (via Jina API, though Jina might use its own): `Mozilla/5.0 (compatible; PythonDocsCrawler/1.0)` (This is the agent used for the initial HTML fetch if Jina were not used directly for conversion from URL)

## Future Improvements / Considerations

*   More robust retry mechanisms for network requests.
*   Option to control request timeouts.
*   Support for sitemaps.
*   More sophisticated filtering of unwanted links (e.g., by regex patterns).
*   Caching of fetched content to speed up repeated runs.
