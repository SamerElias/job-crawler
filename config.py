# config.py

# Use the job search directly from jobs.careers.microsoft.com
BASE_URL = "https://jobs.careers.microsoft.com/global/en/search"
CSS_SELECTOR = ".job-card"
REQUIRED_KEYS = [
    "title",
    "company",
    "location",
    "job_type",
    "posted_date",
    "description",
    "url",
]
