import json
import os
import re
from typing import List, Set, Tuple, Dict, Any

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    LLMExtractionStrategy,
)

from models.job import Job
from utils.data_utils import is_complete_job, is_duplicate_job


def get_browser_config() -> BrowserConfig:
    """
    Returns the browser configuration for the crawler.

    Returns:
        BrowserConfig: The configuration settings for the browser.
    """
    # https://docs.crawl4ai.com/core/browser-crawler-config/
    return BrowserConfig(
        browser_type="chromium",  # Type of browser to simulate
        headless=False,  # Whether to run in headless mode (no GUI)
        verbose=True,  # Enable verbose logging
    )


def get_llm_strategy() -> LLMExtractionStrategy:
    """
    Returns the configuration for the language model extraction strategy.

    Returns:
        LLMExtractionStrategy: The settings for how to extract data using LLM.
    """
    # https://docs.crawl4ai.com/api/strategies/#llmextractionstrategy
    return LLMExtractionStrategy(
        provider="groq/deepseek-r1-distill-llama-70b",  # Name of the LLM provider
        api_token=os.getenv("GROQ_API_KEY"),  # API token for authentication
        schema=Job.model_json_schema(),  # JSON schema of the data model
        extraction_type="schema",  # Type of extraction to perform
        instruction=(
            "Extract all job postings from the Microsoft careers website with the following fields: "
            "'title' (the job title, found in the job card heading), "
            "'company' (always set to 'Microsoft'), "
            "'location' (the job location, usually listed under the job title), "
            "'job_type' (the employment type such as Full-time, Part-time, etc.), "
            "'posted_date' (when the job was posted, may be in a format like 'Posted 2 days ago'), "
            "'description' (a brief 1-2 sentence description of the job from the job listing), "
            "and 'url' (the full URL to the job posting, extracted from the a href attribute). "
            "Look for job listings in cards, tiles, or sections containing job information. "
            "Look for job title elements, location elements, and job description elements. "
            "For URLs, find links that point to the full job description page. "
            "Make sure to extract as many job postings as possible from the page."
        ),  # Instructions for the LLM
        input_format="markdown",  # Format of the input content
        verbose=True,  # Enable verbose logging
    )


async def build_search_url(base_url: str, role: str, page: int) -> str:
    """
    Builds the search URL for Microsoft careers with the specified role and page.

    Args:
        base_url (str): The base URL for Microsoft careers search.
        role (str): The job role to search for.
        page (int): The page number.

    Returns:
        str: The complete search URL.
    """
    # Format the role for the URL (replace spaces with proper encoding)
    formatted_role = role.replace(" ", "%20")

    # For the jobs.careers.microsoft.com site
    # p=job categories (software engineering for software engineers)
    # l=language (en_us for US English)
    # pg=page number
    # pgSz=page size (20 results per page)
    # o=sorting order (relevance)
    return f"{base_url}?keywords={formatted_role}&l=en_us&pg={page}&pgSz=20&o=Relevance"


async def check_no_results(
    crawler: AsyncWebCrawler,
    url: str,
    session_id: str,
) -> bool:
    """
    Checks if there are no job results on the page.

    Args:
        crawler (AsyncWebCrawler): The web crawler instance.
        url (str): The URL to check.
        session_id (str): The session identifier.

    Returns:
        bool: True if no results are found, False otherwise.
    """
    # Fetch the page without any CSS selector or extraction strategy
    result = await crawler.arun(
        url=url,
        config=CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            session_id=session_id,
        ),
    )

    if result.success:
        # Check for common "no results" indicators
        no_results_indicators = [
            "No Results Found",
            "No jobs found",
            "We couldn't find any matches",
            "0 results",
            "No jobs match your search",
            "didn't return any results",
            "Try a different search"
        ]

        # Check if there's a jobs list but it's empty
        if "jobs-list" in result.cleaned_html and "job-card" not in result.cleaned_html:
            return True

        for indicator in no_results_indicators:
            if indicator in result.cleaned_html:
                return True
    else:
        print(
            f"Error fetching page for 'No Results Found' check: {result.error_message}"
        )

    return False


async def fetch_and_process_page(
    crawler: AsyncWebCrawler,
    page_number: int,
    base_url: str,
    role: str,
    css_selector: str,
    llm_strategy: LLMExtractionStrategy,
    session_id: str,
    required_keys: List[str],
    seen_jobs: Set[str],
    job_limit: int,
    jobs_found: int,
) -> Tuple[List[Dict[str, Any]], bool, int]:
    """
    Fetches and processes a single page of job data.

    Args:
        crawler (AsyncWebCrawler): The web crawler instance.
        page_number (int): The page number to fetch.
        base_url (str): The base URL of the website.
        role (str): The job role to search for.
        css_selector (str): The CSS selector to target the content.
        llm_strategy (LLMExtractionStrategy): The LLM extraction strategy.
        session_id (str): The session identifier.
        required_keys (List[str]): List of required keys in the job data.
        seen_jobs (Set[str]): Set of job identifiers that have already been seen.
        job_limit (int): Maximum number of jobs to collect.
        jobs_found (int): Current number of jobs found.

    Returns:
        Tuple[List[Dict[str, Any]], bool, int]:
            - List[Dict[str, Any]]: A list of processed jobs from the page.
            - bool: A flag indicating if crawling should stop.
            - int: Updated count of jobs found.
    """
    url = await build_search_url(base_url, role, page_number)
    print(f"Loading page {page_number} for role '{role}'...")

    # First, try to use the JSON API approach
    try:
        api_jobs = await fetch_jobs_json(crawler, role, page_number, session_id)
        if api_jobs:
            # Process jobs from API
            complete_jobs = []
            for job in api_jobs:
                # Skip processing if we've reached the job limit
                if jobs_found >= job_limit:
                    print(f"Reached job limit of {job_limit}. Stopping crawl.")
                    return complete_jobs, True, jobs_found

                # Create a properly formatted job dictionary
                processed_job = {
                    "title": job.get("title", ""),
                    "company": "Microsoft",
                    "location": job.get("location", {}).get("city", "") + ", " + job.get("location", {}).get("countryCode", ""),
                    "job_type": job.get("jobType", "Full-time"),
                    "posted_date": job.get("postingDate", "Recent"),
                    "description": job.get("description", "")[:200] + "...",  # Truncate long descriptions
                    "url": job.get("url", "") or f"https://careers.microsoft.com/us/en/job/{job.get('jobId', '')}"
                }

                # Debug: print the job data
                print(f"Processing job: {processed_job['title']} - {processed_job['location']}")

                # Check for duplicates
                job_identifier = f"{processed_job['title']}:{processed_job.get('url', '')}"
                if is_duplicate_job(processed_job["title"], processed_job.get("url", ""), seen_jobs):
                    print(f"Duplicate job '{processed_job['title']}' found. Skipping.")
                    continue  # Skip duplicate jobs

                # Add job to the list
                seen_jobs.add(job_identifier)
                complete_jobs.append(processed_job)
                jobs_found += 1
                print(f"Added job #{jobs_found}: {processed_job['title']}")

            if complete_jobs:
                print(f"Extracted {len(complete_jobs)} jobs from API on page {page_number}.")
                return complete_jobs, jobs_found >= job_limit, jobs_found
    except Exception as e:
        print(f"Error using JSON API approach: {str(e)}")

    # If the API approach fails, fall back to the HTML processing approach
    print("Falling back to HTML processing approach...")

    # Check if "No Results Found" message is present
    no_results = await check_no_results(crawler, url, session_id)
    if no_results:
        return [], True, jobs_found  # No more results, signal to stop crawling

    # Fetch page content with the extraction strategy
    result = await crawler.arun(
        url=url,
        config=CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,  # Do not use cached data
            extraction_strategy=llm_strategy,  # Strategy for data extraction
            css_selector=css_selector,  # Target specific content on the page
            session_id=session_id,  # Unique session ID for the crawl
        ),
    )

    if not (result.success and result.extracted_content):
        print(f"Error fetching page {page_number}: {result.error_message}")
        return [], False, jobs_found

    # Parse extracted content
    extracted_data = json.loads(result.extracted_content)
    if not extracted_data:
        print(f"No jobs found on page {page_number}.")
        return [], False, jobs_found

    # Process jobs
    complete_jobs = []
    for job in extracted_data:
        # Skip processing if we've reached the job limit
        if jobs_found >= job_limit:
            print(f"Reached job limit of {job_limit}. Stopping crawl.")
            return complete_jobs, True, jobs_found

        # Ignore the 'error' key if it's False
        if job.get("error") is False:
            job.pop("error", None)  # Remove the 'error' key if it's False

        # Debug: print the job data
        print(f"Processing job: {job.get('title', 'Unknown Title')} - {job.get('location', 'Unknown Location')}")

        # Ensure the company is Microsoft
        job["company"] = "Microsoft"

        # Make sure the URL is a full URL
        if job.get("url") and not job["url"].startswith("http"):
            job["url"] = f"https://careers.microsoft.com{job['url']}"

        # If job_type is missing, set to a default value
        if not job.get("job_type"):
            job["job_type"] = "Full-time"

        # If posted_date is missing, set to a default value
        if not job.get("posted_date"):
            job["posted_date"] = "Recent"

        if not is_complete_job(job, required_keys):
            print(f"Skipping incomplete job: {job.get('title', 'Unknown')}. Missing keys: {[k for k in required_keys if k not in job]}")
            continue  # Skip incomplete jobs

        # Check for duplicates using title and location as a unique identifier
        job_identifier = f"{job['title']}:{job.get('location', '')}"
        if is_duplicate_job(job["title"], job.get("url", ""), seen_jobs):
            print(f"Duplicate job '{job['title']}' found. Skipping.")
            continue  # Skip duplicate jobs

        # Add job to the list
        job_identifier = f"{job['title']}:{job.get('url', '')}"
        seen_jobs.add(job_identifier)
        complete_jobs.append(job)
        jobs_found += 1
        print(f"Added job #{jobs_found}: {job['title']}")

    if not complete_jobs:
        print(f"No complete jobs found on page {page_number}.")
        return [], False, jobs_found

    print(f"Extracted {len(complete_jobs)} jobs from page {page_number}.")

    # Check if we've reached the job limit
    if jobs_found >= job_limit:
        print(f"Reached job limit of {job_limit}. Stopping crawl.")
        return complete_jobs, True, jobs_found

    return complete_jobs, False, jobs_found  # Continue crawling


async def fetch_jobs_json(
    crawler: AsyncWebCrawler,
    role: str,
    page: int,
    session_id: str,
) -> List[Dict[str, Any]]:
    """
    Fetch jobs data directly in JSON format by simulating an AJAX request.

    Args:
        crawler (AsyncWebCrawler): The web crawler instance.
        role (str): The job role to search for.
        page (int): The page number.
        session_id (str): The session identifier.

    Returns:
        List[Dict[str, Any]]: A list of job data dictionaries.
    """
    # Microsoft uses a different API endpoint for fetching job data
    formatted_role = role.replace(" ", "%20")
    api_url = f"https://careers.microsoft.com/us/widgets/search/results?keyword={formatted_role}&page={page}"

    print(f"Fetching jobs data from API: {api_url}")

    # Fetch JSON data from the API
    result = await crawler.arun(
        url=api_url,
        config=CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            session_id=session_id,
        ),
    )

    if not result.success:
        print(f"Error fetching JSON data: {result.error_message}")
        return []

    try:
        # Try to extract JSON data from the response
        json_match = re.search(r'({.*})', result.cleaned_html)
        if json_match:
            json_data = json.loads(json_match.group(1))
            if "jobs" in json_data:
                print(f"Successfully fetched {len(json_data['jobs'])} jobs from API")
                return json_data["jobs"]
    except Exception as e:
        print(f"Error parsing JSON data: {str(e)}")

    return []
