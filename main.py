#!/usr/bin/env python3
import asyncio
import argparse
import logging
from typing import List, Optional, Dict, Type

from crawl4ai import AsyncWebCrawler, BrowserConfig
from utils.sources.drushim import DrushimJobSource
from utils.sources.linkedin import LinkedInJobSource
from utils.sources.base_source import JobSource
from models.job import Job
from utils.data_utils import save_jobs_to_csv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Define available job sources
JOB_SOURCES: Dict[str, Type[JobSource]] = {
    "drushim": DrushimJobSource,
    "linkedin": LinkedInJobSource,
}

async def crawl_jobs(
    role: str,
    source_name: str = "drushim",
    limit: int = 20,
    headless: bool = False,
    verbose: bool = True,
    output_file: Optional[str] = None
) -> List[Job]:
    """
    Crawl job listings from the specified source based on the provided role.

    Args:
        role (str): The job role to search for.
        source_name (str): The name of the job source to use.
        limit (int): Maximum number of jobs to collect.
        headless (bool): Whether to run the browser in headless mode.
        verbose (bool): Whether to show verbose output.
        output_file (Optional[str]): Path to save the results as CSV.

    Returns:
        List[Job]: The list of collected jobs.
    """
    logger.info(f"Starting job crawl for role: {role} (limit: {limit}, source: {source_name})")

    # Initialize the browser configuration
    browser_config = BrowserConfig(
        browser_type="chromium",
        headless=headless,
        verbose=verbose
    )

    # Initialize the web crawler
    crawler = AsyncWebCrawler(browser_config=browser_config)

    # Generate a unique session ID for this crawl
    session_id = f"job-search-{source_name}-{role.replace(' ', '-')}"

    try:
        # Get the job source class and create an instance
        if source_name not in JOB_SOURCES:
            raise ValueError(f"Unknown job source: {source_name}. Available sources: {', '.join(JOB_SOURCES.keys())}")

        source_class = JOB_SOURCES[source_name]
        source = source_class()

        # Initialize crawling variables
        page = 1
        all_jobs = []
        seen_jobs = set()
        jobs_found = 0
        stop_crawling = False

        logger.info(f"Starting crawl using source: {source.name}")

        # Crawl until we reach the limit or have no more results
        while not stop_crawling and jobs_found < limit:
            jobs, stop_crawling, jobs_found = await source.extract_jobs(
                crawler=crawler,
                role=role,
                page=page,
                session_id=session_id,
                seen_jobs=seen_jobs,
                job_limit=limit,
                jobs_found=jobs_found
            )

            all_jobs.extend(jobs)
            logger.info(f"Crawled page {page}, found {len(jobs)} jobs, total: {jobs_found}")

            # Move to the next page
            page += 1

            # Sleep briefly between pages to avoid being blocked
            await asyncio.sleep(2)

        logger.info(f"Completed crawling, found {len(all_jobs)} jobs")

        # Save to CSV if output file is specified
        if output_file and all_jobs:
            save_jobs_to_csv(all_jobs, output_file)
            logger.info(f"Saved {len(all_jobs)} jobs to {output_file}")

        return all_jobs

    finally:
        # Clean up the crawler resources
        await crawler.close()

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Job crawler for multiple job sites")
    parser.add_argument("role", help="Job role to search for")
    parser.add_argument(
        "--source",
        choices=list(JOB_SOURCES.keys()),
        default="drushim",
        help=f"Job source to use (default: drushim). Available sources: {', '.join(JOB_SOURCES.keys())}"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of jobs to collect (default: 20)"
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run in headful mode (show browser)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable verbose output"
    )
    parser.add_argument(
        "--output",
        help="Save results to CSV file"
    )
    return parser.parse_args()

async def main():
    """Main entry point for the job crawler."""
    args = parse_arguments()

    jobs = await crawl_jobs(
        role=args.role,
        source_name=args.source,
        limit=args.limit,
        headless=not args.headful,
        verbose=not args.quiet,
        output_file=args.output
    )

    # Print the collected jobs
    print(f"\nFound {len(jobs)} jobs for '{args.role}' on {args.source}:")
    for i, job in enumerate(jobs, 1):
        print(f"\n{i}. {job.title}")
        print(f"   Company: {job.company}")
        print(f"   Location: {job.location}")
        print(f"   Type: {job.job_type}")
        print(f"   Posted: {job.posted_date}")
        print(f"   URL: {job.url}")

        # Print a truncated description if it exists
        if job.description:
            desc = job.description[:100] + "..." if len(job.description) > 100 else job.description
            print(f"   Description: {desc}")

if __name__ == "__main__":
    asyncio.run(main())
